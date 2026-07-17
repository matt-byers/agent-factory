from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .engineering_handoff import digest, load_manifest, verify_handoff


ATTEMPTS_PATH = Path("agent-lifecycle/attempts")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
MANUAL_FIELDS = ("Status:", "Date:", "Evidence:")


class BuildPlanError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def attempt_directory(root: Path, attempt_id: str) -> Path:
    if not IDENTIFIER.fullmatch(attempt_id):
        raise BuildPlanError(["attempt id must contain only lowercase letters, numbers, dots, and hyphens"])
    directory = root / ATTEMPTS_PATH / attempt_id
    try:
        directory.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise BuildPlanError(["attempt directory must remain inside the repository"]) from error
    return directory


def state_path(root: Path, attempt_id: str) -> Path:
    return attempt_directory(root, attempt_id) / "build-state.json"


def plan_path(root: Path, attempt_id: str) -> Path:
    return attempt_directory(root, attempt_id) / "build-plan.md"


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_build_state(root: Path, attempt_id: str) -> dict[str, Any]:
    path = state_path(root, attempt_id)
    if path.is_symlink():
        raise BuildPlanError(["build state must be a regular repository file"])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BuildPlanError([f"build state is missing or invalid: {error}"]) from error
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise BuildPlanError(["build state must be a version 1 object"])
    return payload


def save_build_state(root: Path, attempt_id: str, state: dict[str, Any]) -> None:
    atomic_json(state_path(root, attempt_id), state)


def normalized_plan(content: str) -> str:
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(f"- {field}") for field in MANUAL_FIELDS):
            prefix = stripped.split(":", 1)[0]
            indentation = line[: len(line) - len(line.lstrip())]
            lines.append(f"{indentation}{prefix}: <manual-evidence>")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def plan_contract_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise BuildPlanError(["build plan must be a regular repository file"])
    return hashlib.sha256(normalized_plan(path.read_text(encoding="utf-8")).encode()).hexdigest()


def valid_relative_file(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = PurePosixPath(value)
    return not candidate.is_absolute() and ".." not in candidate.parts and not value.endswith("/")


def validate_request(
    request: dict[str, Any],
    allowlist: set[str],
    source_paths: set[str],
    focused_commands: set[str],
    full_suite_command: str,
) -> list[str]:
    issues: list[str] = []
    if request.get("version") != 1:
        issues.append("build plan version must be 1")
    requirements = request.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        issues.append("requirements must not be empty")
        requirements = []
    requirement_ids = {
        item.get("id") for item in requirements if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(requirement_ids) != len(requirements) or any(
        not isinstance(item, dict) or not isinstance(item.get("summary"), str) or not item["summary"].strip()
        for item in requirements
    ):
        issues.append("every requirement needs a unique id and summary")
    units = request.get("units")
    if not isinstance(units, list) or not units:
        issues.append("at least one implementation unit is required")
        units = []
    unit_ids = {
        unit.get("id") for unit in units if isinstance(unit, dict) and isinstance(unit.get("id"), str)
    }
    if len(unit_ids) != len(units):
        issues.append("every unit needs a unique id")
    mapped: set[str] = set()
    dependency_graph: dict[str, list[str]] = {}
    unit_positions = {
        unit.get("id"): index for index, unit in enumerate(units) if isinstance(unit, dict)
    }
    for index, unit in enumerate(units):
        label = f"unit {index + 1}"
        if not isinstance(unit, dict):
            issues.append(f"{label} must be an object")
            continue
        identifier = unit.get("id")
        if not isinstance(unit.get("title"), str) or not unit["title"].strip():
            issues.append(f"{label} title is required")
        mapped_ids = unit.get("requirement_ids")
        if not isinstance(mapped_ids, list) or not mapped_ids:
            issues.append(f"{label} requirement ids are required")
        else:
            mapped.update(item for item in mapped_ids if isinstance(item, str))
            for item in mapped_ids:
                if item not in requirement_ids:
                    issues.append(f"{label} maps unknown requirement: {item}")
        dependencies = unit.get("depends_on")
        if not isinstance(dependencies, list):
            issues.append(f"{label} dependencies must be a list")
            dependencies = []
        dependency_graph[str(identifier)] = dependencies
        for dependency in dependencies:
            if dependency in unit_positions and unit_positions[dependency] >= index:
                issues.append(f"{label} must appear after dependency {dependency}")
        files = unit.get("files")
        if not isinstance(files, list) or not files:
            issues.append(f"{label} exact files are required")
        else:
            for file in files:
                if not valid_relative_file(file) or file not in allowlist:
                    issues.append(f"{label} file is outside the exact handoff allowlist: {file}")
        for field in ("test_file", "red_command", "expected_red", "implementation", "focused_green_command"):
            if not isinstance(unit.get(field), str) or not unit[field].strip():
                issues.append(f"{label} {field.replace('_', ' ')} is required")
        if not isinstance(files, list) or unit.get("test_file") not in files:
            issues.append(f"{label} test file must be one of its exact files")
        source_references = unit.get("source_references")
        if not isinstance(source_references, list) or not source_references:
            issues.append(f"{label} source references are required")
        else:
            for reference in source_references:
                relative = reference.split("#", 1)[0] if isinstance(reference, str) else None
                if relative not in source_paths:
                    issues.append(f"{label} source is not bound by the approved handoff: {reference}")
        if unit.get("red_command") not in focused_commands:
            issues.append(f"{label} RED command is not an approved focused-test gate")
        if unit.get("focused_green_command") not in focused_commands:
            issues.append(f"{label} focused GREEN command is not an approved focused-test gate")
        if not isinstance(unit.get("self_verification"), list) or not unit["self_verification"]:
            issues.append(f"{label} self verification commands are required")
        smoke_tests = unit.get("smoke_tests")
        if not isinstance(smoke_tests, list) or not smoke_tests:
            issues.append(f"{label} smoke tests are required")
        else:
            smoke_ids: set[str] = set()
            for smoke in smoke_tests:
                if not isinstance(smoke, dict):
                    issues.append(f"{label} smoke test must be an object")
                    continue
                smoke_id = smoke.get("id")
                if not isinstance(smoke_id, str) or smoke_id in smoke_ids:
                    issues.append(f"{label} smoke tests need unique ids")
                smoke_ids.add(str(smoke_id))
                if smoke.get("mode") not in {"automated", "manual"}:
                    issues.append(f"{label} smoke test mode must be automated or manual")
                if smoke.get("mode") == "manual" and not isinstance(smoke.get("manual_reason"), str):
                    issues.append(f"{label} manual smoke test needs a reason")
                for field in ("action", "expected_outcome"):
                    if not isinstance(smoke.get(field), str) or not smoke[field].strip():
                        issues.append(f"{label} smoke test {field.replace('_', ' ')} is required")
        testagent = unit.get("testagent")
        if not isinstance(testagent, dict) or not isinstance(testagent.get("enabled"), bool):
            issues.append(f"{label} testagent choice is required")
        elif testagent["enabled"] and not testagent.get("probes"):
            issues.append(f"{label} enabled testagent needs at least one bounded probe")
    for missing in sorted(requirement_ids - mapped):
        issues.append(f"requirement is not mapped to a unit: {missing}")
    for unit, dependencies in dependency_graph.items():
        for dependency in dependencies:
            if dependency not in unit_ids:
                issues.append(f"unit {unit} depends on unknown unit: {dependency}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            issues.append(f"dependency cycle includes unit {identifier}")
            return
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in dependency_graph.get(identifier, []):
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in dependency_graph:
        visit(identifier)
    review_sources = request.get("review_sources")
    if not isinstance(review_sources, list) or not review_sources:
        issues.append("review sources are required")
    else:
        for reference in review_sources:
            if reference not in source_paths:
                issues.append(f"review source is not bound by the approved handoff: {reference}")
    if not isinstance(request.get("full_suite_command"), str) or not request["full_suite_command"].strip():
        issues.append("full suite command is required")
    elif request["full_suite_command"] != full_suite_command:
        issues.append("full suite command does not match the approved handoff gate")
    return list(dict.fromkeys(issues))


def render_plan(
    attempt_id: str,
    manifest_path: Path,
    manifest_sha256: str,
    request: dict[str, Any],
    acceptance_gates: list[dict[str, Any]],
) -> str:
    lines = [
        "# Agent Build Plan",
        "",
        f"Attempt: `{attempt_id}`",
        f"Approved handoff: `{manifest_path.as_posix()}`",
        f"Handoff SHA-256: `{manifest_sha256}`",
        "Status: Draft — explicit acceptance is required before editing agent files.",
        "",
        "## Requirements",
        "",
    ]
    lines.extend(f"- **{item['id']}**: {item['summary']}" for item in request["requirements"])
    lines.extend(["", "## Approved acceptance gates", ""])
    lines.extend(
        f"- **{gate['id']}** ({gate['kind']}): {gate['success_criteria']}"
        for gate in acceptance_gates
    )
    for unit in request["units"]:
        lines.extend(
            [
                "",
                f"## Unit {unit['id']} — {unit['title']}",
                "",
                f"Requirements: {', '.join(unit['requirement_ids'])}",
                f"Depends on: {', '.join(unit['depends_on']) if unit['depends_on'] else 'None'}",
                "",
                "### Exact files",
                "",
                *[f"- `{path}`" for path in unit["files"]],
                "",
                "### Sources",
                "",
                *[f"- `{source}`" for source in unit["source_references"]],
                "",
                "### Tests-first RED",
                "",
                f"Test file: `{unit['test_file']}`",
                f"Command: `{unit['red_command']}`",
                f"Expected failure: {unit['expected_red']}",
                "",
                "### Implementation",
                "",
                unit["implementation"],
                "",
                "### Focused GREEN",
                "",
                f"Command: `{unit['focused_green_command']}`",
                "",
                "### Self-verification",
                "",
                *[f"- `{command}`" for command in unit["self_verification"]],
                "",
                "### Smoke tests",
                "",
            ]
        )
        for smoke in unit["smoke_tests"]:
            lines.extend(
                [
                    f"#### {smoke['id']} [{smoke['mode']}]",
                    "",
                    f"- Action: {smoke['action']}",
                    f"- Expected outcome: {smoke['expected_outcome']}",
                ]
            )
            if smoke["mode"] == "manual":
                lines.extend(
                    [
                        f"- Manual reason: {smoke['manual_reason']}",
                        "- Status: Pending",
                        "- Date: Pending",
                        "- Evidence: Pending",
                    ]
                )
        lines.extend(["", "### Optional testagent", ""])
        if unit["testagent"]["enabled"]:
            lines.extend(f"- {probe}" for probe in unit["testagent"]["probes"])
        else:
            lines.append("Disabled for this unit.")
        lines.extend(["", "### Review", "", "Review the accepted plan, repository instructions, and named sources. No blocking or high findings may remain."])
    lines.extend(
        [
            "",
            "## Review sources",
            "",
            *[f"- `{source}`" for source in request["review_sources"]],
            "",
            "## Full suite",
            "",
            f"Run exactly once after every unit is reviewed: `{request['full_suite_command']}`",
            "",
            "## Commit and receipt",
            "",
            "Commit only exact allowlisted files with an explicit path list, preserve unrelated work, and write the manifest- and plan-bound engineering receipt.",
        ]
    )
    return "\n".join(lines) + "\n"


def create_build_plan(root: Path, attempt_id: str, manifest_path: Path, request: dict[str, Any]) -> Path:
    directory = attempt_directory(root, attempt_id)
    if directory.exists():
        raise BuildPlanError([f"build attempt already exists: {attempt_id}"])
    try:
        resolved_manifest = manifest_path.resolve()
        resolved_manifest.relative_to(root.resolve())
    except ValueError as error:
        raise BuildPlanError(["handoff manifest must be inside the repository"]) from error
    handoff_issues = verify_handoff(resolved_manifest)
    if handoff_issues:
        raise BuildPlanError(handoff_issues)
    manifest = load_manifest(resolved_manifest)
    if manifest.get("approval_status") != "approved":
        raise BuildPlanError(["engineering handoff must be approved"])
    if not isinstance(request, dict):
        raise BuildPlanError(["build plan request must contain an object"])
    allowlist = {item["path"] for item in manifest["editable_paths"]}
    gates_path = resolved_manifest.parent / "acceptance-gates.json"
    try:
        gates_payload = json.loads(gates_path.read_text(encoding="utf-8"))
        acceptance_gates = gates_payload["gates"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise BuildPlanError([f"approved acceptance gates are invalid: {error}"]) from error
    focused_commands = {
        gate["command"] for gate in acceptance_gates if gate.get("kind") == "focused_tests"
    }
    full_suite_commands = [
        gate["command"] for gate in acceptance_gates if gate.get("kind") == "full_suite"
    ]
    if len(full_suite_commands) != 1:
        raise BuildPlanError(["approved handoff must contain one full-suite command"])
    source_paths = set(manifest.get("source_sha256", {}))
    issues = validate_request(
        request,
        allowlist,
        source_paths,
        focused_commands,
        full_suite_commands[0],
    )
    if issues:
        raise BuildPlanError(issues)
    directory.mkdir(parents=True)
    output = plan_path(root, attempt_id)
    relative_manifest = resolved_manifest.relative_to(root.resolve())
    output.write_text(
        render_plan(
            attempt_id,
            relative_manifest,
            digest(resolved_manifest),
            request,
            acceptance_gates,
        ),
        encoding="utf-8",
    )
    state = {
        "version": 1,
        "attempt_id": attempt_id,
        "status": "draft",
        "handoff_manifest": str(relative_manifest),
        "handoff_manifest_sha256": digest(resolved_manifest),
        "accepted_plan_sha256": None,
        "request": request,
        "acceptance_gates": acceptance_gates,
        "progress": {unit["id"]: {"completed_stages": [], "evidence": {}} for unit in request["units"]},
        "failures": [],
        "full_suite": None,
        "commit_sha": None,
        "receipt": None,
    }
    save_build_state(root, attempt_id, state)
    return output


def accept_build_plan(root: Path, attempt_id: str) -> dict[str, Any]:
    state = load_build_state(root, attempt_id)
    if state["status"] != "draft":
        raise BuildPlanError(["only a draft build plan can be accepted"])
    path = plan_path(root, attempt_id)
    state["status"] = "accepted"
    state["accepted_plan_sha256"] = plan_contract_sha256(path)
    save_build_state(root, attempt_id, state)
    return state


def assert_accepted_plan(root: Path, attempt_id: str) -> dict[str, Any]:
    state = load_build_state(root, attempt_id)
    if state.get("status") not in {"accepted", "running", "ready_to_commit", "committed"}:
        raise BuildPlanError(["explicit plan acceptance is required before implementation"])
    if state.get("accepted_plan_sha256") != plan_contract_sha256(plan_path(root, attempt_id)):
        raise BuildPlanError(["accepted build plan content has changed"])
    manifest = root / state["handoff_manifest"]
    if digest(manifest) != state["handoff_manifest_sha256"] or verify_handoff(manifest):
        raise BuildPlanError(["approved handoff changed after plan creation"])
    return state
