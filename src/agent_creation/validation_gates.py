from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .baseline_evaluation import (
    BASELINE_PATH,
    atomic_json,
    selected_owner,
    surface_digests,
    validate_trial,
)
from .engineering_handoff import digest
from .eval_design import SUITE_PATH, load_held_out_case, read_suite, validate_suite
from .eval_runtime import EvalRuntimeError, comparison_summary, decide_gate
from .lifecycle import load_state, save_state


HELD_IN_DECISION_PATH = Path("agent-lifecycle/evals/held-in-decision.yaml")
HELD_OUT_DECISION_PATH = Path("agent-lifecycle/evals/held-out-decision.yaml")
HELD_OUT_RELEASE_PATH = Path("agent-lifecycle/evals/held-out-release.json")
COMPARISON_FIELDS = {
    "quality",
    "hard_invariant_pass_rate",
    "latency_ms",
    "cost",
    "trial_count",
}


class ValidationGateError(ValueError):
    pass


def read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ValidationGateError(f"{label} must be a regular repository file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationGateError(f"{label} is missing or invalid: {error}") from error
    if not isinstance(value, dict):
        raise ValidationGateError(f"{label} must contain an object")
    return value


def evaluate_held_in(root: Path, run_path: Path) -> dict[str, Any]:
    state = _require_stage(root, "held_in")
    run, relative_run = _load_run(root, run_path)
    existing = _existing_decision(root / HELD_IN_DECISION_PATH, digest(run_path.resolve()))
    if existing is not None:
        if existing.get("decision") == "accepted":
            _write_release(root, state, _load_suite(root))
        return existing
    suite = _load_suite(root)
    cases = [case for case in suite["cases"] if case["split"] == "held_in"]
    issues, artifacts = _inspect_run(root, suite, run, relative_run, "held_in", cases)
    decision, owner, reason, comparison = _decide(issues, artifacts, cases)
    payload = _decision_payload(
        "held_in", decision, owner, reason, relative_run, digest(run_path.resolve()), comparison
    )
    atomic_json(root / HELD_IN_DECISION_PATH, payload)
    if decision == "accepted":
        _write_release(root, state, suite)
    else:
        _remove(root / HELD_OUT_RELEASE_PATH)
        if decision == "rejected":
            state["stage"] = "learning"
            state["status"] = "active"
            save_state(root, state)
    return payload


def load_released_held_out_cases(root: Path) -> tuple[dict[str, Any], ...]:
    release_path = root / HELD_OUT_RELEASE_PATH
    if not release_path.is_file() or release_path.is_symlink():
        raise ValidationGateError("held-out cases are not released")
    state = _require_stage(root, "held_out")
    release = read_object(release_path, "held-out release")
    decision_path = root / HELD_IN_DECISION_PATH
    decision = read_object(decision_path, "held-in decision")
    suite = _load_suite(root)
    expected = {
        case["id"]: case["sha256"]
        for case in suite["cases"]
        if case["split"] == "held_out"
    }
    if (
        release.get("version") != 1
        or release.get("status") != "released"
        or decision.get("decision") != "accepted"
        or release.get("suite_sha256") != digest(root / SUITE_PATH)
        or release.get("receipt_sha256") != state["receipt"]["sha256"]
        or release.get("held_in_decision_sha256") != digest(decision_path)
        or release.get("sealed_cases") != expected
    ):
        raise ValidationGateError("held-out release is stale or invalid")
    return tuple(
        load_held_out_case(root, manifest, release=True)
        for manifest in suite["cases"]
        if manifest["split"] == "held_out"
    )


def evaluate_held_out(
    root: Path,
    run_path: Path,
    *,
    allowed_quality_delta: float = 0.05,
    max_latency_ratio: float = 1.2,
    max_cost_ratio: float = 1.2,
) -> dict[str, Any]:
    _require_stage(root, "held_out")
    run, relative_run = _load_run(root, run_path)
    run_sha256 = digest(run_path.resolve())
    existing = _existing_decision(root / HELD_OUT_DECISION_PATH, run_sha256)
    if existing is not None:
        return existing
    cases = list(load_released_held_out_cases(root))
    suite = _load_suite(root)
    issues, artifacts = _inspect_run(root, suite, run, relative_run, "held_out", cases)
    decision, owner, reason, comparison = _decide(issues, artifacts, cases)
    baseline_path = root / BASELINE_PATH
    baseline_before_sha256 = digest(baseline_path) if baseline_path.is_file() else None
    baseline: dict[str, Any] | None = None
    if decision == "accepted":
        try:
            baseline = read_object(baseline_path, "accepted agent baseline")
            baseline_comparison = _validated_comparison(baseline.get("comparison"))
        except ValidationGateError as error:
            decision, owner, reason = "inconclusive", "harness", str(error)
        else:
            regressions = _regressions(
                comparison,
                baseline_comparison,
                allowed_quality_delta,
                max_latency_ratio,
                max_cost_ratio,
            )
            if regressions:
                decision, owner, reason = "rejected", "target_agent", "; ".join(regressions)
    baseline_after_sha256 = baseline_before_sha256
    if decision == "accepted" and baseline is not None:
        baseline = {
            **baseline,
            "run_path": str(relative_run),
            "run_sha256": run_sha256,
            "prompt_sha256": surface_digests(root, "agent/prompts", required=True),
            "toolset_sha256": surface_digests(root, "agent/tools", required=False),
            "comparison": comparison,
            "validation": {
                "held_in_decision_sha256": digest(root / HELD_IN_DECISION_PATH),
                "held_out_run_path": str(relative_run),
                "held_out_run_sha256": run_sha256,
            },
        }
        atomic_json(baseline_path, baseline)
        baseline_after_sha256 = digest(baseline_path)
    payload = _decision_payload(
        "held_out", decision, owner, reason, relative_run, run_sha256, comparison
    )
    payload["baseline_before_sha256"] = baseline_before_sha256
    payload["baseline_after_sha256"] = baseline_after_sha256
    atomic_json(root / HELD_OUT_DECISION_PATH, payload)
    return payload


def validate_validation_decision(root: Path, split: str) -> list[str]:
    path = root / (HELD_IN_DECISION_PATH if split == "held_in" else HELD_OUT_DECISION_PATH)
    try:
        decision = read_object(path, f"{split} decision")
    except ValidationGateError as error:
        return [str(error)]
    allowed = {"accepted"} if split == "held_in" else {"accepted", "rejected"}
    if decision.get("decision") not in allowed:
        return [decision.get("reason") or f"{split} decision is incomplete"]
    source = decision.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        return [f"{split} decision source is invalid"]
    source_path = root / source["path"]
    if not source_path.is_file() or source_path.is_symlink() or digest(source_path) != source.get("sha256"):
        return [f"{split} decision source changed"]
    if split == "held_in":
        try:
            release = read_object(root / HELD_OUT_RELEASE_PATH, "held-out release")
        except ValidationGateError as error:
            return [str(error)]
        if release.get("held_in_decision_sha256") != digest(path):
            return ["held-out release does not match the held-in decision"]
    if split == "held_out" and decision.get("decision") == "accepted":
        baseline = root / BASELINE_PATH
        if not baseline.is_file() or digest(baseline) != decision.get("baseline_after_sha256"):
            return ["accepted baseline does not match the held-out decision"]
    return []


def _require_stage(root: Path, stage: str) -> dict[str, Any]:
    state = load_state(root)
    if state.get("lifecycle") != "improvement":
        raise ValidationGateError("validation gates apply only to a target-agent improvement")
    if state.get("stage") != stage:
        raise ValidationGateError(
            f"lifecycle is not ready for {stage.replace('_', '-')} validation"
        )
    receipt = state.get("receipt")
    if not isinstance(receipt, dict) or not isinstance(receipt.get("sha256"), str):
        raise ValidationGateError("target-agent improvement receipt is missing")
    return state


def _load_suite(root: Path) -> dict[str, Any]:
    try:
        suite = read_suite(root / SUITE_PATH)
        issues = validate_suite(suite)
    except (OSError, ValueError) as error:
        raise ValidationGateError(f"eval suite is missing or invalid: {error}") from error
    if issues:
        raise ValidationGateError("eval suite is invalid: " + "; ".join(issues))
    return suite


def _load_run(root: Path, path: Path) -> tuple[dict[str, Any], Path]:
    if path.is_symlink():
        raise ValidationGateError("native validation run must be a regular repository file")
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValidationGateError("native validation run must remain inside the repository") from error
    return read_object(resolved, "native validation run"), relative


def _inspect_run(
    root: Path,
    suite: dict[str, Any],
    run: dict[str, Any],
    relative_run: Path,
    split: str,
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if run.get("version") != 1:
        issues.append(_issue("harness", "native run version must be 1"))
    if run.get("status") != "complete":
        issues.append(_issue("harness", "native run status is not complete"))
    if run.get("split") != split:
        issues.append(_issue("data", f"native run must contain only the {split} split"))
    if run.get("suite_sha256") != digest(root / SUITE_PATH):
        issues.append(_issue("data", "native run references a stale eval suite"))
    try:
        baseline = read_object(root / BASELINE_PATH, "accepted agent baseline")
    except ValidationGateError as error:
        issues.append(_issue("harness", str(error)))
        baseline = {}
    if baseline and run.get("target_command") != baseline.get("target_command"):
        issues.append(_issue("data", "native run target command differs from the accepted baseline"))
    results = run.get("cases")
    if not isinstance(results, list):
        return issues + [_issue("data", f"{split} case results must be a list")], []
    indexed = {
        result.get("case_id"): result
        for result in results
        if isinstance(result, dict) and isinstance(result.get("case_id"), str)
    }
    if len(indexed) != len(results):
        issues.append(_issue("data", f"{split} case results are malformed or duplicated"))
    expected_ids = {case["id"] for case in cases}
    for unexpected in sorted(set(indexed) - expected_ids):
        issues.append(_issue("data", f"unexpected {split} case result: {unexpected}"))
    artifacts: list[dict[str, Any]] = []
    for case in cases:
        result = indexed.get(case["id"])
        if result is None:
            issues.append(_issue("data", f"required {split.replace('_', '-')} case is missing: {case['id']}"))
            continue
        trials = result.get("trials")
        if not isinstance(trials, list) or len(trials) != case["trials"]:
            issues.append(_issue("data", f"{split.replace('_', '-')} case has incomplete trial coverage: {case['id']}"))
            continue
        for index, trial in enumerate(trials):
            trial_issues, artifact = validate_trial(case, trial, f"{case['id']}:{index}")
            issues.extend(trial_issues)
            if artifact is not None:
                artifacts.append(artifact)
    return issues, artifacts


def _decide(
    issues: list[dict[str, Any]], artifacts: list[dict[str, Any]], cases: list[dict[str, Any]]
) -> tuple[str, str | None, str, dict[str, Any]]:
    comparison: dict[str, Any] = {}
    if issues:
        owner = selected_owner(issues)
        decision = "rejected" if owner == "target_agent" else "inconclusive"
        return decision, owner, issues[0]["reason"], comparison
    gate = decide_gate(artifacts, gate="held_in")
    if not gate.proceed:
        owner = "target_agent" if gate.decision == "reject" else "harness"
        return "rejected" if owner == "target_agent" else "inconclusive", owner, gate.reason, comparison
    try:
        comparison = comparison_summary(
            artifacts,
            deterministic_keys={
                grader["id"] for case in cases for grader in case["graders"]["deterministic"]
            },
            quality_keys={rubric["id"] for case in cases for rubric in case["graders"]["rubrics"]},
        )
    except EvalRuntimeError as error:
        return "inconclusive", "harness", str(error), {}
    return "accepted", None, "all required eval cases and trials passed", comparison


def _validated_comparison(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or not COMPARISON_FIELDS.issubset(value):
        raise ValidationGateError("accepted baseline comparison is missing or incomplete")
    validated: dict[str, float] = {}
    for field in COMPARISON_FIELDS:
        try:
            number = float(value[field])
        except (TypeError, ValueError) as error:
            raise ValidationGateError(f"accepted baseline comparison is invalid: {field}") from error
        if not math.isfinite(number) or number < 0:
            raise ValidationGateError(f"accepted baseline comparison is invalid: {field}")
        validated[field] = number
    return validated


def _regressions(
    candidate: dict[str, Any],
    baseline: dict[str, float],
    quality_delta: float,
    latency_ratio: float,
    cost_ratio: float,
) -> list[str]:
    if (
        not all(math.isfinite(value) for value in (quality_delta, latency_ratio, cost_ratio))
        or quality_delta < 0
        or latency_ratio < 1
        or cost_ratio < 1
    ):
        raise ValidationGateError("comparison tolerances are invalid")
    regressions: list[str] = []
    if candidate["quality"] < baseline["quality"] - quality_delta:
        regressions.append("quality regression exceeded the allowed delta")
    if candidate["hard_invariant_pass_rate"] < baseline["hard_invariant_pass_rate"]:
        regressions.append("hard invariant regression is not allowed")
    if candidate["latency_ms"] > baseline["latency_ms"] * latency_ratio:
        regressions.append("latency regression exceeded the allowed ratio")
    if candidate["cost"] > baseline["cost"] * cost_ratio:
        regressions.append("cost regression exceeded the allowed ratio")
    return regressions


def _decision_payload(
    split: str,
    decision: str,
    owner: str | None,
    reason: str,
    run_path: Path,
    run_sha256: str,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": 1,
        "status": "complete",
        "split": split,
        "decision": decision,
        "owner": owner,
        "reason": reason,
        "source": {"path": str(run_path), "sha256": run_sha256},
        "comparison": comparison,
    }


def _existing_decision(path: Path, run_sha256: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    decision = read_object(path, "validation decision")
    source = decision.get("source")
    if isinstance(source, dict) and source.get("sha256") == run_sha256:
        return decision
    if decision.get("decision") in {"accepted", "rejected"}:
        raise ValidationGateError("conclusive validation decision is immutable")
    return None


def _issue(owner: str, reason: str) -> dict[str, Any]:
    return {"owner": owner, "reason": reason, "case_id": None, "trial_id": None}


def _remove(path: Path) -> None:
    if path.is_symlink():
        raise ValidationGateError(f"refusing to remove symlinked validation artifact: {path}")
    if path.is_file():
        path.unlink()


def _write_release(root: Path, state: dict[str, Any], suite: dict[str, Any]) -> None:
    release = {
        "version": 1,
        "status": "released",
        "suite_sha256": digest(root / SUITE_PATH),
        "receipt_sha256": state["receipt"]["sha256"],
        "held_in_decision_sha256": digest(root / HELD_IN_DECISION_PATH),
        "sealed_cases": {
            case["id"]: case["sha256"]
            for case in suite["cases"]
            if case["split"] == "held_out"
        },
    }
    atomic_json(root / HELD_OUT_RELEASE_PATH, release)
