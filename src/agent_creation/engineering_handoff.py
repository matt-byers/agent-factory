from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any


HANDOFFS_PATH = Path("agent-lifecycle/handoffs")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{7,64}$")
RECEIPT_FIELDS = {
    "version",
    "handoff_id",
    "manifest_sha256",
    "result_status",
    "changed_files",
    "test_evidence",
    "review_outcome",
    "commit_sha",
    "architecture_changed",
}
REQUIRED_GATE_KINDS = {"focused_tests", "full_suite", "acceptance_evals", "review"}
REQUIRED_SOURCE_PATHS = {
    "agent-lifecycle/agent-definition/project-brief.md",
    "agent-lifecycle/architecture/agent-architecture.md",
    "agent-lifecycle/architecture/decisions.md",
    "agent-lifecycle/evals/suite.yaml",
    "docs/references/agent-building-best-practices.md",
}
SURFACE_PREFIXES = {
    "prompts": "agent/prompts/",
    "context": "agent/context/",
    "workflow": "agent/workflow/",
    "model_configuration": "agent/model/",
    "agent_state": "agent/state/",
    "memory_orchestration": "agent/memory/",
    "agent_tool_contracts": "agent/tools/",
    "middleware": "agent/middleware/",
    "skills": "agent/skills/",
    "subagents": "agent/subagents/",
}


class EngineeringHandoffError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def non_empty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(non_empty(item) for item in value)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EngineeringHandoffError([f"{label} is missing or invalid: {error}"]) from error
    if not isinstance(payload, dict):
        raise EngineeringHandoffError([f"{label} must contain an object"])
    return payload


def reference_path(root: Path, reference: str) -> tuple[str | None, str | None]:
    if not non_empty(reference) or "#" not in reference:
        return None, "evidence reference must be a repository path with an anchor"
    relative, anchor = reference.split("#", 1)
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not anchor:
        return None, f"invalid evidence reference: {reference}"
    path = root / relative
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return None, f"evidence reference leaves the repository: {reference}"
    if not path.is_file():
        return None, f"referenced evidence does not exist: {reference}"
    return relative, None


def eval_ids(root: Path) -> set[str]:
    suite = read_json(root / "agent-lifecycle/evals/suite.yaml", "eval suite")
    cases = suite.get("cases")
    if suite.get("status") != "complete" or not isinstance(cases, list):
        raise EngineeringHandoffError(["eval suite must be complete before creating a handoff"])
    return {
        item["id"]
        for item in cases
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def validate_editable_paths(value: Any) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(value, list) or not value:
        return [], ["editable paths must contain at least one exact agent-surface file"]
    normalized: list[dict[str, str]] = []
    issues: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        label = f"editable path {index + 1}"
        if not isinstance(item, dict):
            issues.append(f"{label} must contain path and surface")
            continue
        path = item.get("path")
        surface = item.get("surface")
        if not non_empty(path):
            issues.append(f"{label} path is required")
            continue
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts or "\\" in path:
            issues.append(f"{label} must be repository-relative")
            continue
        if any(character in path for character in "*?[]{}") or path.endswith("/"):
            issues.append(f"{label} must be an exact file path without globs")
            continue
        if surface not in SURFACE_PREFIXES:
            issues.append(f"{label} uses an unsupported agent surface: {surface}")
            continue
        if not path.startswith(SURFACE_PREFIXES[surface]) or path == SURFACE_PREFIXES[surface]:
            issues.append(f"{label} does not belong to the declared {surface} agent surface")
            continue
        if path in seen:
            issues.append(f"duplicate editable path: {path}")
            continue
        seen.add(path)
        normalized.append({"path": path, "surface": surface})
    return normalized, issues


def validate_recommendations(
    root: Path, value: Any, available_evals: set[str]
) -> tuple[list[dict[str, Any]], set[str], set[str], list[str]]:
    if not isinstance(value, list) or not value:
        return [], set(), set(), ["at least one recommendation is required"]
    issues: list[str] = []
    sources: set[str] = set()
    acceptance: set[str] = set()
    identifiers: set[str] = set()
    for index, recommendation in enumerate(value):
        label = f"recommendation {index + 1}"
        if not isinstance(recommendation, dict):
            issues.append(f"{label} must be an object")
            continue
        identifier = recommendation.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            issues.append(f"{label} id must use lowercase hyphen-case")
        elif identifier in identifiers:
            issues.append(f"duplicate recommendation id: {identifier}")
        else:
            identifiers.add(identifier)
        evidence = recommendation.get("requirement_or_evidence")
        if not non_empty_strings(evidence):
            issues.append(f"{label} requirement or evidence is required")
        else:
            for reference in evidence:
                relative, error = reference_path(root, reference)
                if error:
                    issues.append(error)
                elif relative:
                    sources.add(relative)
        for field in ("likely_cause_or_design_need", "proposed_change"):
            if not non_empty(recommendation.get(field)):
                issues.append(f"{label} {field.replace('_', ' ')} is required")
        rationale = recommendation.get("source_rationale")
        if not isinstance(rationale, dict) or not non_empty(rationale.get("summary")):
            issues.append(f"{label} source rationale is required")
        elif not non_empty_strings(rationale.get("references")):
            issues.append(f"{label} source rationale references are required")
        else:
            for reference in rationale["references"]:
                relative, error = reference_path(root, reference)
                if error:
                    issues.append(error)
                elif relative:
                    sources.add(relative)
        effect = recommendation.get("expected_effect")
        if not isinstance(effect, dict) or not non_empty(effect.get("user")) or not non_empty(effect.get("business")):
            issues.append(f"{label} expected effect requires user and business outcomes")
        recommendation_evals = recommendation.get("acceptance_eval_ids")
        if not non_empty_strings(recommendation_evals):
            issues.append(f"{label} acceptance eval ids are required")
        else:
            for identifier in recommendation_evals:
                if identifier not in available_evals:
                    issues.append(f"{label} links unknown acceptance eval: {identifier}")
                else:
                    acceptance.add(identifier)
    return value, sources, acceptance, issues


def validate_gates(
    value: Any, available_evals: set[str], required_evals: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list) or not value:
        return [], ["acceptance gates must not be empty"]
    issues: list[str] = []
    kinds: set[str] = set()
    identifiers: set[str] = set()
    gated_evals: set[str] = set()
    for index, gate in enumerate(value):
        label = f"acceptance gate {index + 1}"
        if not isinstance(gate, dict):
            issues.append(f"{label} must be an object")
            continue
        identifier = gate.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            issues.append(f"{label} id must use lowercase hyphen-case")
        elif identifier in identifiers:
            issues.append(f"duplicate acceptance gate id: {identifier}")
        else:
            identifiers.add(identifier)
        kind = gate.get("kind")
        if kind not in REQUIRED_GATE_KINDS:
            issues.append(f"{label} kind is unsupported: {kind}")
        else:
            kinds.add(kind)
        if not non_empty(gate.get("success_criteria")):
            issues.append(f"{label} success criteria is required")
        if kind in {"focused_tests", "full_suite"} and not non_empty(gate.get("command")):
            issues.append(f"{label} command is required")
        if kind == "acceptance_evals":
            values = gate.get("eval_ids")
            if not non_empty_strings(values):
                issues.append(f"{label} eval ids are required")
            else:
                for eval_identifier in values:
                    if eval_identifier not in available_evals:
                        issues.append(f"{label} links unknown eval: {eval_identifier}")
                    else:
                        gated_evals.add(eval_identifier)
    for kind in sorted(REQUIRED_GATE_KINDS - kinds):
        issues.append(f"acceptance gate kind is required: {kind}")
    for identifier in sorted(required_evals - gated_evals):
        issues.append(f"acceptance eval is not gated: {identifier}")
    return value, issues


def validate_request(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if request.get("version") != 1:
        issues.append("handoff request version must be 1")
    handoff_id = request.get("handoff_id")
    if not isinstance(handoff_id, str) or not IDENTIFIER.fullmatch(handoff_id):
        issues.append("handoff id must use lowercase hyphen-case")
    if request.get("kind") not in {"build", "improvement"}:
        issues.append("handoff kind must be build or improvement")
    if request.get("approval_status") != "approved":
        issues.append("handoff must be approved before creation")
    editable_paths, path_issues = validate_editable_paths(request.get("editable_paths"))
    issues.extend(path_issues)
    try:
        available_evals = eval_ids(root)
    except EngineeringHandoffError as error:
        available_evals = set()
        issues.extend(error.issues)
    recommendations, sources, acceptance, recommendation_issues = validate_recommendations(
        root, request.get("recommendations"), available_evals
    )
    issues.extend(recommendation_issues)
    for relative in sorted(REQUIRED_SOURCE_PATHS):
        source = root / relative
        if source.is_symlink() or not source.is_file():
            issues.append(f"required handoff source does not exist: {relative}")
        else:
            sources.add(relative)
    gates, gate_issues = validate_gates(request.get("acceptance_gates"), available_evals, acceptance)
    issues.extend(gate_issues)
    if issues:
        raise EngineeringHandoffError(list(dict.fromkeys(issues)))
    return {
        **request,
        "editable_paths": editable_paths,
        "recommendations": recommendations,
        "acceptance_gates": gates,
        "source_paths": sorted(sources),
        "acceptance_eval_ids": sorted(acceptance),
    }


def render_specification(request: dict[str, Any]) -> str:
    lines = [
        "# Engineering Implementation Specification",
        "",
        f"Handoff: `{request['handoff_id']}`",
        "",
        "Only the exact editable paths in the manifest may change.",
    ]
    for recommendation in request["recommendations"]:
        rationale = recommendation["source_rationale"]
        effect = recommendation["expected_effect"]
        lines.extend(
            [
                "",
                f"## {recommendation['id']}",
                "",
                "### Requirement or observed evidence",
                "",
                *[f"- `{reference}`" for reference in recommendation["requirement_or_evidence"]],
                "",
                "### Likely cause or design need",
                "",
                recommendation["likely_cause_or_design_need"],
                "",
                "### Proposed change",
                "",
                recommendation["proposed_change"],
                "",
                "### Source-linked rationale",
                "",
                rationale["summary"],
                "",
                *[f"- `{reference}`" for reference in rationale["references"]],
                "",
                "### Expected user and business effect",
                "",
                f"- User: {effect['user']}",
                f"- Business: {effect['business']}",
                "",
                "### Acceptance evals",
                "",
                *[f"- `{identifier}`" for identifier in recommendation["acceptance_eval_ids"]],
            ]
        )
    return "\n".join(lines) + "\n"


def receipt_template(handoff_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "handoff_id": handoff_id,
        "manifest_sha256": "<manifest-sha256>",
        "result_status": "pending",
        "changed_files": [],
        "test_evidence": [],
        "review_outcome": "pending",
        "commit_sha": None,
        "architecture_changed": None,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def atomic_route(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    write_json(temporary, payload)
    temporary.replace(path)


def create_handoff(root: Path, raw_request: dict[str, Any]) -> dict[str, Path]:
    request = validate_request(root, raw_request)
    parent = root / HANDOFFS_PATH
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / request["handoff_id"]
    route_name = "build-handoff.yaml" if request["kind"] == "build" else "improvement-handoff.yaml"
    route = parent / route_name
    if target.exists() or target.is_symlink():
        raise EngineeringHandoffError([f"handoff identifier already exists: {request['handoff_id']}"])
    if route.exists() or route.is_symlink():
        raise EngineeringHandoffError([f"active {request['kind']} handoff route already exists: {route_name}"])
    temporary = Path(tempfile.mkdtemp(prefix=f".{request['handoff_id']}-", dir=parent))
    try:
        specification = temporary / "implementation-spec.md"
        gates = temporary / "acceptance-gates.json"
        receipt = temporary / "receipt-template.json"
        specification.write_text(render_specification(request), encoding="utf-8")
        write_json(
            gates,
            {
                "version": 1,
                "handoff_id": request["handoff_id"],
                "gates": request["acceptance_gates"],
            },
        )
        write_json(receipt, receipt_template(request["handoff_id"]))
        manifest = {
            "version": 1,
            "handoff_id": request["handoff_id"],
            "kind": request["kind"],
            "approval_status": request["approval_status"],
            "editable_paths": request["editable_paths"],
            "recommendation_ids": [item["id"] for item in request["recommendations"]],
            "acceptance_eval_ids": request["acceptance_eval_ids"],
            "artifact_sha256": {
                path.name: digest(path) for path in (specification, gates, receipt)
            },
            "source_sha256": {
                relative: digest(root / relative) for relative in request["source_paths"]
            },
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        for path in (specification, gates, receipt, manifest_path):
            path.chmod(0o444)
        temporary.replace(target)
    except Exception:
        if temporary.exists():
            for path in temporary.iterdir():
                path.chmod(0o644)
                path.unlink()
            temporary.rmdir()
        raise
    manifest_path = target / "manifest.json"
    atomic_route(
        route,
        {
            "version": 1,
            "handoff_id": request["handoff_id"],
            "approval_status": request["approval_status"],
            "manifest": str(manifest_path.relative_to(root)),
            "manifest_sha256": digest(manifest_path),
        },
    )
    return {
        "implementation_spec": target / "implementation-spec.md",
        "acceptance_gates": target / "acceptance-gates.json",
        "manifest": manifest_path,
        "receipt_template": target / "receipt-template.json",
        "route": route,
    }


def load_manifest(path: Path) -> dict[str, Any]:
    return read_json(path, "engineering handoff manifest")


def verify_handoff(manifest_path: Path) -> list[str]:
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return ["engineering handoff manifest must be a regular file"]
    try:
        manifest = load_manifest(manifest_path)
    except EngineeringHandoffError as error:
        return error.issues
    issues: list[str] = []
    if manifest.get("version") != 1 or manifest.get("approval_status") != "approved":
        issues.append("manifest must be version 1 and approved")
    artifact_digests = manifest.get("artifact_sha256")
    expected_artifacts = {
        "implementation-spec.md",
        "acceptance-gates.json",
        "receipt-template.json",
    }
    if not isinstance(artifact_digests, dict) or set(artifact_digests) != expected_artifacts:
        issues.append("manifest artifact digests are missing")
    else:
        for name, expected in artifact_digests.items():
            path = manifest_path.parent / name
            if path.is_symlink() or not path.is_file():
                issues.append(f"artifact is missing: {name}")
            elif digest(path) != expected:
                issues.append(f"digest mismatch: {name}")
    source_digests = manifest.get("source_sha256")
    root = manifest_path.parents[3] if len(manifest_path.parents) > 3 else None
    if not isinstance(source_digests, dict) or root is None:
        issues.append("manifest source digests are missing")
    else:
        for relative, expected in source_digests.items():
            path = root / relative
            candidate = PurePosixPath(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                issues.append(f"invalid source evidence path: {relative}")
            elif path.is_symlink() or not path.is_file():
                issues.append(f"source evidence is missing: {relative}")
            elif digest(path) != expected:
                issues.append(f"source evidence changed: {relative}")
    return issues


def validate_receipt(
    receipt: dict[str, Any], manifest_path: Path, require_completed: bool = True
) -> list[str]:
    issues = verify_handoff(manifest_path)
    if issues:
        return issues
    if not isinstance(receipt, dict):
        return ["engineering receipt must contain an object"]
    manifest = load_manifest(manifest_path)
    if set(receipt) != RECEIPT_FIELDS:
        missing = sorted(RECEIPT_FIELDS - set(receipt))
        unexpected = sorted(set(receipt) - RECEIPT_FIELDS)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        issues.append("receipt fields do not match the shared schema: " + "; ".join(details))
    if receipt.get("version") != 1:
        issues.append("receipt version must be 1")
    if receipt.get("handoff_id") != manifest.get("handoff_id"):
        issues.append("receipt handoff id does not match the manifest")
    if receipt.get("manifest_sha256") != digest(manifest_path):
        issues.append("receipt references a stale manifest")
    result_status = receipt.get("result_status")
    if result_status not in {"completed", "failed", "incomplete"}:
        issues.append("receipt result status must be completed, failed, or incomplete")
    elif require_completed and result_status != "completed":
        issues.append("receipt result status must be completed")
    changed_files = receipt.get("changed_files")
    allowlist = {
        item["path"]
        for item in manifest.get("editable_paths", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if not isinstance(changed_files, list) or not all(non_empty(path) for path in changed_files):
        issues.append("receipt changed files must be a string list")
    elif len(set(changed_files)) != len(changed_files):
        issues.append("receipt changed files must not contain duplicates")
    elif result_status == "completed" and not changed_files:
        issues.append("receipt changed files must not be empty")
    else:
        for path in changed_files:
            if path not in allowlist:
                issues.append(f"changed file is outside the exact allowlist: {path}")
    if not non_empty_strings(receipt.get("test_evidence")):
        issues.append("receipt test evidence must not be empty")
    review_outcome = receipt.get("review_outcome")
    if result_status == "completed" and review_outcome not in {"passed", "passed_with_notes"}:
        issues.append("receipt review outcome must pass")
    if result_status in {"failed", "incomplete"} and review_outcome != result_status:
        issues.append(f"{result_status} receipt review outcome must be {result_status}")
    commit_sha = receipt.get("commit_sha")
    if result_status == "completed" and (
        not isinstance(commit_sha, str) or not COMMIT_SHA.fullmatch(commit_sha)
    ):
        issues.append("receipt commit sha must be a hexadecimal git revision")
    if result_status in {"failed", "incomplete"} and commit_sha is not None:
        issues.append(f"{result_status} receipt cannot claim a commit sha")
    if not isinstance(receipt.get("architecture_changed"), bool):
        issues.append("receipt architecture changed must be true or false")
    return issues


def route_manifest(root: Path, kind: str) -> Path:
    route_name = "build-handoff.yaml" if kind == "build" else "improvement-handoff.yaml"
    route_path = root / HANDOFFS_PATH / route_name
    if route_path.is_symlink():
        raise EngineeringHandoffError(["engineering handoff route must be a regular file"])
    route = read_json(route_path, "engineering handoff route")
    relative = route.get("manifest")
    if not non_empty(relative):
        raise EngineeringHandoffError(["engineering handoff route is missing its manifest"])
    candidate = (root / relative).resolve()
    handoffs = (root / HANDOFFS_PATH).resolve()
    try:
        candidate.relative_to(handoffs)
    except ValueError as error:
        raise EngineeringHandoffError(["engineering handoff manifest must remain inside handoffs"])
    if candidate.is_symlink() or not candidate.is_file():
        raise EngineeringHandoffError(["engineering handoff manifest must be a regular file"])
    if route.get("manifest_sha256") != digest(candidate):
        raise EngineeringHandoffError(["engineering handoff route references a stale manifest"])
    errors = verify_handoff(candidate)
    if errors:
        raise EngineeringHandoffError(errors)
    manifest = load_manifest(candidate)
    if route.get("handoff_id") != manifest.get("handoff_id"):
        raise EngineeringHandoffError(["engineering handoff route id does not match its manifest"])
    return candidate
