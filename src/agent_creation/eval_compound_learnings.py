from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence

from .engineering_handoff import digest
from .lifecycle import advance, atomic_write, load_state


LEARNING_PATH = Path("agent-lifecycle/evidence/eval-loop-learning.yaml")
HELD_IN_DECISION_PATH = Path("agent-lifecycle/evals/held-in-decision.yaml")
HELD_OUT_DECISION_PATH = Path("agent-lifecycle/evals/held-out-decision.yaml")
IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATEGORY_SURFACES = {
    "eval_case": (
        "agent-lifecycle/evals/",
        ".claude/skills/agent-eval-designer/",
        "src/agent_creation/eval_design.py",
    ),
    "simulated_user": (
        "agent-lifecycle/evals/",
        ".claude/skills/agent-eval-designer/",
        "src/agent_creation/simulated_user.py",
    ),
    "rubric": (
        "agent-lifecycle/evals/",
        ".claude/skills/agent-eval-designer/",
        ".claude/skills/eval-agent/",
        "src/agent_creation/eval_design.py",
        "src/agent_creation/eval_runtime.py",
    ),
    "evidence": (
        "agent-lifecycle/evidence/",
        ".claude/skills/agent-production-evidence/",
        "src/agent_creation/production_evidence.py",
        "src/agent_creation/target_adapter.py",
    ),
    "provider": (
        ".claude/skills/eval-agent/",
        "docs/references/eval-result-providers.md",
        "src/agent_creation/eval_providers.py",
    ),
    "comparison_gate": (
        ".claude/skills/eval-agent/",
        "src/agent_creation/eval_runtime.py",
        "src/agent_creation/validation_gates.py",
    ),
    "operator_guidance": (
        ".claude/skills/agent-eval-designer/",
        ".claude/skills/agent-production-evidence/",
        ".claude/skills/eval-agent/",
        ".claude/skills/eval-compound-learnings/",
        "docs/references/eval-result-providers.md",
        "scripts/agent-eval",
    ),
}


class EvalCompoundLearningError(ValueError):
    pass


def record_eval_loop_learning(
    root: Path,
    improvements: Sequence[Mapping[str, Any]],
    *,
    no_op_reason: str | None = None,
) -> dict[str, Any]:
    state = load_state(root)
    if state.get("lifecycle") != "improvement" or state.get("stage") != "learning":
        raise EvalCompoundLearningError("eval-loop learning requires the improvement learning stage")
    decision_path, decision = _conclusive_decision(root)
    if improvements and no_op_reason is not None:
        raise EvalCompoundLearningError("no-op reason cannot accompany improvements")
    if not improvements and not _non_empty(no_op_reason):
        raise EvalCompoundLearningError("a no-op reason is required when no improvements are recorded")
    normalized = [_normalize_improvement(root, item) for item in improvements]
    payload = {
        "version": 1,
        "status": "complete",
        "attempt_decision": decision["decision"],
        "decision": {
            "path": str(decision_path.relative_to(root)),
            "sha256": digest(decision_path),
        },
        "outcome": "updated" if normalized else "no_op",
        "improvements": normalized,
        "no_op_reason": no_op_reason.strip() if isinstance(no_op_reason, str) else None,
    }
    artifact_path = root / LEARNING_PATH
    if artifact_path.exists():
        existing = _read_object(artifact_path, "eval-loop learning")
        if existing != payload:
            raise EvalCompoundLearningError("eval-loop learning artifact is immutable")
    else:
        atomic_write(artifact_path, payload)
    issues = validate_eval_loop_learning(root)
    if issues:
        raise EvalCompoundLearningError("eval-loop learning is invalid: " + "; ".join(issues))
    return {"learning": payload, "lifecycle": advance(root)}


def validate_eval_loop_learning(root: Path) -> list[str]:
    try:
        payload = _read_object(root / LEARNING_PATH, "eval-loop learning")
    except EvalCompoundLearningError as error:
        return [str(error)]
    issues: list[str] = []
    if payload.get("version") != 1 or payload.get("status") != "complete":
        issues.append("version and complete status are required")
    try:
        decision_path, decision = _conclusive_decision(root)
    except EvalCompoundLearningError as error:
        issues.append(str(error))
        decision_path = None
        decision = {}
    decision_ref = payload.get("decision")
    if not isinstance(decision_ref, dict) or decision_path is None:
        issues.append("decision reference is invalid")
    elif decision_ref != {
        "path": str(decision_path.relative_to(root)),
        "sha256": digest(decision_path),
    }:
        issues.append("decision reference is stale or tampered")
    if payload.get("attempt_decision") != decision.get("decision"):
        issues.append("attempt decision does not match validation evidence")
    improvements = payload.get("improvements")
    if not isinstance(improvements, list):
        issues.append("improvements must be a list")
        improvements = []
    normalized: list[dict[str, Any]] = []
    for index, improvement in enumerate(improvements):
        try:
            normalized.append(_normalize_recorded_improvement(root, improvement))
        except EvalCompoundLearningError as error:
            issues.append(f"improvement {index + 1}: {error}")
    if len(normalized) == len(improvements) and normalized != improvements:
        issues.append("improvement evidence or changed-file digests are stale")
    outcome = payload.get("outcome")
    no_op_reason = payload.get("no_op_reason")
    if outcome == "updated":
        if not improvements:
            issues.append("updated outcome requires improvements")
        if no_op_reason is not None:
            issues.append("updated outcome cannot include a no-op reason")
    elif outcome == "no_op":
        if improvements:
            issues.append("no-op outcome cannot include improvements")
        if not _non_empty(no_op_reason):
            issues.append("no-op outcome requires a reason")
    else:
        issues.append("outcome must be updated or no_op")
    return issues


def _conclusive_decision(root: Path) -> tuple[Path, dict[str, Any]]:
    held_out = root / HELD_OUT_DECISION_PATH
    held_in = root / HELD_IN_DECISION_PATH
    path = held_out if held_out.is_file() else held_in
    decision = _read_object(path, "validation decision")
    expected_split = "held_out" if path == held_out else "held_in"
    if (
        decision.get("version") != 1
        or decision.get("status") != "complete"
        or decision.get("split") != expected_split
    ):
        raise EvalCompoundLearningError("validation decision is incomplete or invalid")
    if decision.get("decision") not in {"accepted", "rejected"}:
        raise EvalCompoundLearningError("eval learning requires an accepted or rejected attempt")
    if path == held_in and decision.get("decision") != "rejected":
        raise EvalCompoundLearningError("accepted held-in validation is not a completed attempt")
    source = decision.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise EvalCompoundLearningError("validation decision source is invalid")
    source_path = _repository_file(root, source["path"], "decision source")
    if digest(source_path) != source.get("sha256"):
        raise EvalCompoundLearningError("validation decision source changed")
    return path, decision


def _normalize_improvement(root: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    identifier = value.get("id")
    category = value.get("category")
    summary = value.get("summary")
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise EvalCompoundLearningError("improvement id must use lowercase hyphen-case")
    if category not in CATEGORY_SURFACES:
        raise EvalCompoundLearningError(f"unsupported eval-loop category: {category}")
    if not _non_empty(summary):
        raise EvalCompoundLearningError("improvement summary is required")
    evidence_refs = value.get("evidence_refs")
    changed_paths = value.get("changed_paths")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise EvalCompoundLearningError("each improvement requires evidence")
    if not isinstance(changed_paths, list) or not changed_paths:
        raise EvalCompoundLearningError("each improvement requires changed paths")
    evidence = [_evidence_record(root, item) for item in evidence_refs]
    changes = [_change_record(root, category, item) for item in changed_paths]
    if len({item["path"] for item in changes}) != len(changes):
        raise EvalCompoundLearningError("changed paths must be unique")
    return {
        "id": identifier,
        "category": category,
        "summary": summary.strip(),
        "evidence": evidence,
        "changes": changes,
    }


def _normalize_recorded_improvement(root: Path, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalCompoundLearningError("must contain an object")
    evidence = value.get("evidence")
    changes = value.get("changes")
    if not isinstance(evidence, list) or not evidence:
        raise EvalCompoundLearningError("each improvement requires evidence")
    if not isinstance(changes, list) or not changes:
        raise EvalCompoundLearningError("each improvement requires changed paths")
    request = {
        "id": value.get("id"),
        "category": value.get("category"),
        "summary": value.get("summary"),
        "evidence_refs": [
            f"{item.get('path')}#{item.get('anchor')}" if isinstance(item, dict) else ""
            for item in evidence
        ],
        "changed_paths": [item.get("path") if isinstance(item, dict) else "" for item in changes],
    }
    return _normalize_improvement(root, request)


def _evidence_record(root: Path, reference: Any) -> dict[str, str]:
    if not isinstance(reference, str) or "#" not in reference:
        raise EvalCompoundLearningError("evidence references require path#anchor")
    relative, anchor = reference.split("#", 1)
    if not relative or not anchor:
        raise EvalCompoundLearningError("evidence references require path#anchor")
    path = _repository_file(root, relative, "evidence")
    return {"path": relative, "anchor": anchor, "sha256": digest(path)}


def _change_record(root: Path, category: str, relative: Any) -> dict[str, str]:
    if not isinstance(relative, str) or not _allowed_surface(category, relative):
        raise EvalCompoundLearningError(f"changed path is outside the {category} scope: {relative}")
    path = _repository_file(root, relative, "changed path")
    return {"path": relative, "sha256": digest(path)}


def _allowed_surface(category: str, relative: str) -> bool:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        return False
    return any(
        relative.startswith(prefix) if prefix.endswith("/") else relative == prefix
        for prefix in CATEGORY_SURFACES[category]
    )


def _repository_file(root: Path, relative: str, label: str) -> Path:
    path_value = PurePosixPath(relative)
    if path_value.is_absolute() or ".." in path_value.parts or "\\" in relative:
        raise EvalCompoundLearningError(f"{label} must remain inside the repository")
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise EvalCompoundLearningError(f"{label} must be a regular repository file: {relative}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise EvalCompoundLearningError(f"{label} must remain inside the repository") from error
    return path


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise EvalCompoundLearningError(f"{label} must be a regular repository file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvalCompoundLearningError(f"{label} is missing or invalid") from error
    if not isinstance(value, dict):
        raise EvalCompoundLearningError(f"{label} must contain an object")
    return value


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
