from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


STATE_PATH = Path("agent-lifecycle/state.yaml")
SETUP_PATH = Path("agent-lifecycle/setup.yaml")


@dataclass(frozen=True)
class Stage:
    name: str
    invocation: str
    required: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()


FIRST_BUILD = (
    Stage(
        "goal_definition",
        "/agent-goal-interview",
        (
            "agent-lifecycle/agent-definition/project-brief.md",
            "agent-lifecycle/agent-definition/success-metrics.yaml",
            "agent-lifecycle/agent-definition/business-value-model.yaml",
        ),
    ),
    Stage("eval_design", "/agent-eval-designer", ("agent-lifecycle/evals/suite.yaml",)),
    Stage(
        "architecture",
        "/agent-architecture-planner",
        (
            "agent-lifecycle/architecture/agent-architecture.md",
            "agent-lifecycle/architecture/decisions.md",
            "agent-lifecycle/handoffs/build-handoff.yaml",
        ),
    ),
    Stage("engineering", ""),
    Stage("waiting_for_receipt", ""),
    Stage("baseline", "/eval-agent", ("agent-lifecycle/evals/baseline-decision.yaml",)),
    Stage("operational", "Lifecycle complete"),
)

IMPROVEMENT = (
    Stage(
        "evidence",
        "/eval-agent or /agent-production-evidence",
        any_of=(
            "agent-lifecycle/evals/latest-run.yaml",
            "agent-lifecycle/evidence/selected-evidence.yaml",
        ),
    ),
    Stage("diagnosis", "/agent-behavior-review", ("agent-lifecycle/handoffs/improvement-handoff.yaml",)),
    Stage("engineering", ""),
    Stage("waiting_for_receipt", ""),
    Stage("held_in", "/eval-agent", ("agent-lifecycle/evals/held-in-decision.yaml",)),
    Stage("held_out", "/eval-agent", ("agent-lifecycle/evals/held-out-decision.yaml",)),
    Stage("learning", "/eval-compound-learnings", ("agent-lifecycle/evidence/eval-loop-learning.yaml",)),
    Stage("operational", "Lifecycle complete"),
)

FLOWS = {"first-build": FIRST_BUILD, "improvement": IMPROVEMENT}


class LifecycleError(ValueError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


def initial_state() -> dict[str, Any]:
    return {
        "version": 1,
        "lifecycle": None,
        "stage": "not_started",
        "status": "idle",
        "engineering_loop": None,
        "artifact_fingerprints": {},
        "receipt": None,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LifecycleError(f"{label} does not exist: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LifecycleError(f"{label} is not valid JSON-compatible YAML: {path}") from error
    if not isinstance(payload, dict):
        raise LifecycleError(f"{label} must contain an object: {path}")
    return payload


def load_state(root: Path) -> dict[str, Any]:
    path = root / STATE_PATH
    if not path.exists():
        state = initial_state()
        atomic_write(path, state)
        return state
    state = read_json(path, "lifecycle state")
    if state.get("version") != 1:
        raise LifecycleError("unsupported lifecycle state version")
    return state


def save_state(root: Path, state: dict[str, Any]) -> None:
    atomic_write(root / STATE_PATH, state)


def flow_for(state: dict[str, Any]) -> tuple[Stage, ...]:
    lifecycle = state.get("lifecycle")
    if lifecycle not in FLOWS:
        raise LifecycleError("lifecycle has not started")
    return FLOWS[lifecycle]


def stage_for(state: dict[str, Any]) -> Stage:
    stage_name = state.get("stage")
    for stage in flow_for(state):
        if stage.name == stage_name:
            return stage
    raise LifecycleError(f"invalid lifecycle stage: {stage_name}")


def invocation_for(state: dict[str, Any], stage: Stage | None = None) -> str:
    current = stage or stage_for(state)
    if current.name in {"engineering", "waiting_for_receipt"}:
        if state.get("engineering_loop") == "included":
            return "/agent-build-loop"
        return "Provide an engineering receipt from the selected external loop"
    return current.invocation


def artifact_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def existing_stage_artifacts(root: Path, stage: Stage) -> list[str]:
    paths = list(stage.required)
    if stage.any_of:
        paths.extend(relative for relative in stage.any_of if (root / relative).is_file())
    return paths


def missing_artifacts(root: Path, stage: Stage) -> list[str]:
    missing = [relative for relative in stage.required if not (root / relative).is_file()]
    if stage.any_of and not any((root / relative).is_file() for relative in stage.any_of):
        missing.append("one of: " + ", ".join(stage.any_of))
    return missing


def snapshot_stage(root: Path, state: dict[str, Any], stage: Stage) -> None:
    paths = existing_stage_artifacts(root, stage)
    state["artifact_fingerprints"][stage.name] = {
        relative: artifact_digest(root / relative) for relative in paths
    }


def validate_stage_artifacts(root: Path, state: dict[str, Any], stage: Stage) -> None:
    if stage.name not in {"architecture", "diagnosis"}:
        return
    relative = (
        "agent-lifecycle/handoffs/build-handoff.yaml"
        if state.get("lifecycle") == "first-build"
        else "agent-lifecycle/handoffs/improvement-handoff.yaml"
    )
    handoff = read_json(root / relative, "engineering handoff")
    if handoff.get("approval_status") != "approved" or not isinstance(handoff.get("handoff_id"), str):
        raise LifecycleError("engineering routing requires an approved handoff with a handoff_id")


def detect_drift(root: Path, state: dict[str, Any]) -> list[str]:
    if state.get("lifecycle") not in FLOWS:
        return []
    flow = flow_for(state)
    fingerprints = state.get("artifact_fingerprints", {})
    for index, stage in enumerate(flow):
        recorded = fingerprints.get(stage.name)
        if not recorded:
            continue
        changed = [
            relative
            for relative, digest in recorded.items()
            if not (root / relative).is_file() or artifact_digest(root / relative) != digest
        ]
        if changed:
            state["stage"] = stage.name
            state["status"] = "active"
            state["receipt"] = None
            state["artifact_fingerprints"] = {
                name: values
                for name, values in fingerprints.items()
                if next((position for position, item in enumerate(flow) if item.name == name), len(flow)) < index
            }
            return sorted(changed)
    return []


def public_state(state: dict[str, Any], changed: list[str] | None = None) -> dict[str, Any]:
    response = {
        "lifecycle": state.get("lifecycle"),
        "stage": state.get("stage"),
        "status": state.get("status"),
    }
    if state.get("lifecycle") in FLOWS:
        response["next"] = invocation_for(state)
    if state.get("receipt"):
        response["receipt"] = state["receipt"]
    if changed:
        response["changed"] = changed
    return response


def setup(
    root: Path,
    simulator_model: str,
    judge_model: str,
    evidence_mode: str,
    engineering_loop: str,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    configuration = {
        "version": 1,
        "simulator_model": simulator_model,
        "judge_model": judge_model,
        "evidence_mode": evidence_mode,
        "engineering_loop": engineering_loop,
    }
    atomic_write(root / SETUP_PATH, configuration)
    state = load_state(root)
    return public_state(state)


def start(root: Path, lifecycle: str, engineering_loop: str | None) -> dict[str, Any]:
    state = load_state(root)
    if state.get("status") == "active" or state.get("stage") == "waiting_for_receipt":
        raise LifecycleError("a lifecycle is already active; use status or resume")
    selected_loop = engineering_loop
    if selected_loop is None and (root / SETUP_PATH).exists():
        selected_loop = read_json(root / SETUP_PATH, "setup configuration").get("engineering_loop")
    selected_loop = selected_loop or "included"
    state = initial_state()
    state.update(
        lifecycle=lifecycle,
        stage=FLOWS[lifecycle][0].name,
        status="active",
        engineering_loop=selected_loop,
    )
    save_state(root, state)
    return public_state(state)


def status(root: Path) -> dict[str, Any]:
    state = load_state(root)
    changed = detect_drift(root, state)
    if changed:
        save_state(root, state)
    return public_state(state, changed)


def advance(root: Path) -> dict[str, Any]:
    state = load_state(root)
    changed = detect_drift(root, state)
    if changed:
        save_state(root, state)
        return public_state(state, changed)
    current = stage_for(state)
    if current.name == "operational":
        raise LifecycleError("lifecycle is already operational")
    if current.name == "waiting_for_receipt":
        raise LifecycleError("waiting for an engineering receipt; use resume --receipt")
    missing = missing_artifacts(root, current)
    if missing:
        raise LifecycleError(
            "required artifacts are missing",
            {"stage": current.name, "next": invocation_for(state, current), "missing": missing},
        )
    validate_stage_artifacts(root, state, current)
    snapshot_stage(root, state, current)
    flow = flow_for(state)
    next_stage = flow[flow.index(current) + 1]
    state["stage"] = next_stage.name
    if next_stage.name == "waiting_for_receipt":
        state["status"] = "waiting"
    elif next_stage.name == "operational":
        state["status"] = "complete"
    save_state(root, state)
    return public_state(state)


def expected_handoff_id(root: Path, state: dict[str, Any]) -> str | None:
    relative = (
        "agent-lifecycle/handoffs/build-handoff.yaml"
        if state.get("lifecycle") == "first-build"
        else "agent-lifecycle/handoffs/improvement-handoff.yaml"
    )
    payload = read_json(root / relative, "engineering handoff")
    value = payload.get("handoff_id")
    return value if isinstance(value, str) and value else None


def validate_receipt(root: Path, state: dict[str, Any], receipt_path: Path) -> dict[str, Any]:
    resolved_root = root.resolve()
    if receipt_path.is_symlink():
        raise LifecycleError("engineering receipt must be a regular repository file")
    resolved_receipt = receipt_path.resolve()
    try:
        resolved_receipt.relative_to(resolved_root)
    except ValueError as error:
        raise LifecycleError("engineering receipt must be inside the repository") from error
    if not resolved_receipt.is_file():
        raise LifecycleError("engineering receipt must be a regular repository file")
    receipt = read_json(resolved_receipt, "engineering receipt")
    required = {
        "handoff_id",
        "result_status",
        "changed_files",
        "test_evidence",
        "review_outcome",
        "commit_sha",
        "architecture_changed",
    }
    if receipt.get("result_status") != "completed" or required - set(receipt):
        raise LifecycleError("resume requires a completed receipt with all contract fields")
    if receipt.get("handoff_id") != expected_handoff_id(root, state):
        raise LifecycleError("engineering receipt does not match the active handoff")
    return receipt


def resume(root: Path, receipt_path: Path) -> dict[str, Any]:
    state = load_state(root)
    if state.get("stage") != "waiting_for_receipt":
        raise LifecycleError("not waiting for an engineering receipt")
    receipt = validate_receipt(root, state, receipt_path)
    state["receipt"] = {
        "path": str(receipt_path.resolve().relative_to(root.resolve())),
        "sha256": artifact_digest(receipt_path.resolve()),
        "handoff_id": receipt["handoff_id"],
    }
    state["stage"] = "baseline" if state["lifecycle"] == "first-build" else "held_in"
    state["status"] = "active"
    save_state(root, state)
    return public_state(state)
