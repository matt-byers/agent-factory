from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .engineering_handoff import digest
from .eval_design import SUITE_PATH, read_suite, validate_suite
from .eval_runtime import decide_gate
from .lifecycle import load_state, save_state


DECISION_PATH = Path("agent-lifecycle/evals/baseline-decision.yaml")
BASELINE_PATH = Path("agent-lifecycle/evals/agent-baseline.yaml")
DIAGNOSTIC_PATH = Path("agent-lifecycle/evals/baseline-diagnostic.json")
OWNER_ROUTES = {
    "target_agent": "/agent-self-improvement",
    "eval": "/eval-agent repair-eval",
    "provider": "/eval-agent repair-provider",
    "data": "/agent-eval-designer",
    "harness": "/eval-agent repair-harness",
}
ERROR_OWNERS = {
    "target_failure": "target_agent",
    "timeout": "target_agent",
    "process_crash": "target_agent",
    "malformed_output": "target_agent",
    "missing_result": "target_agent",
    "tool_failure": "target_agent",
    "protocol_error": "target_agent",
    "eval_failure": "eval",
    "provider_failure": "provider",
    "data_failure": "data",
    "harness_failure": "harness",
}
OWNER_PRIORITY = ("provider", "harness", "eval", "data", "target_agent")


class BaselineEvaluationError(ValueError):
    pass


def read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise BaselineEvaluationError(f"{label} must be a regular repository file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BaselineEvaluationError(f"{label} is missing or invalid: {error}") from error
    if not isinstance(payload, dict):
        raise BaselineEvaluationError(f"{label} must contain an object")
    return payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    if path.is_symlink():
        raise BaselineEvaluationError(f"artifact must be a regular repository file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def issue(owner: str, reason: str, case_id: str | None = None, trial_id: str | None = None) -> dict[str, Any]:
    return {
        "owner": owner,
        "reason": reason,
        "case_id": case_id,
        "trial_id": trial_id,
    }


def expected_scores(case: dict[str, Any]) -> dict[str, float]:
    expected = {
        grader["id"]: 1.0 for grader in case["graders"]["deterministic"]
    }
    expected.update(
        {rubric["id"]: float(rubric["threshold"]) for rubric in case["graders"]["rubrics"]}
    )
    return expected


def validate_trial(
    case: dict[str, Any], trial: Any, expected_trial_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    case_id = case["id"]
    if not isinstance(trial, dict):
        return [issue("harness", "native trial artifact must contain an object", case_id, expected_trial_id)], None
    trial_id = trial.get("trial_id")
    if trial_id != expected_trial_id:
        return [issue("data", "held-in trial id is missing or unexpected", case_id, str(trial_id))], trial
    issues: list[dict[str, Any]] = []
    errors = trial.get("errors")
    if not isinstance(errors, list):
        issues.append(issue("harness", "native trial errors must be a list", case_id, trial_id))
        errors = []
    if trial.get("status") != "complete" and not errors:
        issues.append(issue("harness", "incomplete trial has no typed error", case_id, trial_id))
    for error in errors:
        if not isinstance(error, dict):
            issues.append(issue("harness", "native trial error must contain an object", case_id, trial_id))
            continue
        category = error.get("category")
        owner = ERROR_OWNERS.get(category, "harness")
        issues.append(issue(owner, f"{category or 'unknown'} during {error.get('stage') or 'evaluation'}", case_id, trial_id))
    scores = trial.get("scores")
    if not isinstance(scores, list):
        issues.append(issue("eval", "required grader scores are missing", case_id, trial_id))
        return issues, trial
    indexed: dict[str, dict[str, Any]] = {}
    for score in scores:
        if not isinstance(score, dict) or not isinstance(score.get("key"), str):
            issues.append(issue("eval", "grader score is malformed", case_id, trial_id))
            continue
        if score["key"] in indexed:
            issues.append(issue("eval", f"duplicate grader score: {score['key']}", case_id, trial_id))
        indexed[score["key"]] = score
    expected = expected_scores(case)
    for unexpected in sorted(set(indexed) - set(expected)):
        issues.append(issue("eval", f"unexpected grader score: {unexpected}", case_id, trial_id))
    for key, threshold in expected.items():
        score = indexed.get(key)
        if score is None:
            issues.append(issue("eval", f"required grader score is missing: {key}", case_id, trial_id))
            continue
        try:
            numeric_score = float(score["score"])
            numeric_threshold = float(score["threshold"])
        except (KeyError, TypeError, ValueError):
            issues.append(issue("eval", f"grader score is malformed: {key}", case_id, trial_id))
            continue
        if not math.isfinite(numeric_score) or not math.isfinite(numeric_threshold):
            issues.append(issue("eval", f"grader score is not finite: {key}", case_id, trial_id))
        elif numeric_threshold != threshold:
            issues.append(issue("eval", f"grader threshold differs from suite: {key}", case_id, trial_id))
        elif numeric_score < threshold:
            issues.append(issue("target_agent", f"required grader score failed: {key}", case_id, trial_id))
    return issues, trial


def inspect_run(
    suite: dict[str, Any], run: dict[str, Any], suite_sha256: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if run.get("version") != 1:
        issues.append(issue("harness", "native run version must be 1"))
    if run.get("status") != "complete":
        issues.append(issue("harness", "native run status is not complete"))
    if run.get("split") != "held_in":
        issues.append(issue("data", "native run must contain only the held-in split"))
    if run.get("suite_sha256") != suite_sha256:
        issues.append(issue("data", "native run references a stale eval suite"))
    run_metrics = run.get("metrics")
    if not isinstance(run_metrics, list):
        issues.append(issue("eval", "native run aggregate metrics must be a list"))
    else:
        indexed_metrics: dict[str, Any] = {}
        for measurement in run_metrics:
            if not isinstance(measurement, dict) or not isinstance(measurement.get("id"), str):
                issues.append(issue("eval", "native run aggregate metric is malformed"))
                continue
            identifier = measurement["id"]
            if identifier in indexed_metrics:
                issues.append(issue("eval", f"duplicate aggregate metric: {identifier}"))
            indexed_metrics[identifier] = measurement.get("value")
        for metric in suite["metrics"]:
            identifier = metric["id"]
            if identifier not in indexed_metrics:
                issues.append(issue("eval", f"required aggregate metric is missing: {identifier}"))
                continue
            try:
                value = float(indexed_metrics[identifier])
                threshold = float(metric["threshold"])
            except (TypeError, ValueError):
                issues.append(issue("eval", f"aggregate metric is not numeric: {identifier}"))
                continue
            if not math.isfinite(value) or not math.isfinite(threshold):
                issues.append(issue("eval", f"aggregate metric is not finite: {identifier}"))
                continue
            failed = value > threshold if metric["kind"] == "operational" else value < threshold
            if failed:
                issues.append(issue("target_agent", f"required aggregate metric failed: {identifier}"))
        expected_metric_ids = {metric["id"] for metric in suite["metrics"]}
        for unexpected in sorted(set(indexed_metrics) - expected_metric_ids):
            issues.append(issue("eval", f"unexpected aggregate metric: {unexpected}"))
    run_cases = run.get("cases")
    if not isinstance(run_cases, list):
        return issues + [issue("data", "held-in case results must be a list")], []
    indexed: dict[str, dict[str, Any]] = {}
    for result in run_cases:
        if not isinstance(result, dict) or not isinstance(result.get("case_id"), str):
            issues.append(issue("data", "held-in case result is malformed"))
            continue
        case_id = result["case_id"]
        if case_id in indexed:
            issues.append(issue("data", f"duplicate held-in case result: {case_id}", case_id))
        indexed[case_id] = result
    expected_cases = [case for case in suite["cases"] if case["split"] == "held_in"]
    expected_ids = {case["id"] for case in expected_cases}
    for unexpected in sorted(set(indexed) - expected_ids):
        issues.append(issue("data", f"unexpected non-held-in case result: {unexpected}", unexpected))
    artifacts: list[dict[str, Any]] = []
    for case in expected_cases:
        case_id = case["id"]
        result = indexed.get(case_id)
        if result is None:
            issues.append(issue("data", f"required held-in case is missing: {case_id}", case_id))
            continue
        trials = result.get("trials")
        if not isinstance(trials, list) or len(trials) != case["trials"]:
            issues.append(issue("data", f"held-in case has incomplete trial coverage: {case_id}", case_id))
            continue
        for index, trial in enumerate(trials):
            trial_issues, artifact = validate_trial(case, trial, f"{case_id}:{index}")
            issues.extend(trial_issues)
            if artifact is not None:
                artifacts.append(artifact)
    return issues, artifacts


def selected_owner(issues: list[dict[str, Any]]) -> str:
    owners = {item["owner"] for item in issues}
    return next(owner for owner in OWNER_PRIORITY if owner in owners)


def surface_digests(root: Path, relative: str, required: bool) -> dict[str, str]:
    directory = root / relative
    if directory.is_symlink():
        raise BaselineEvaluationError(f"agent baseline surface must be a regular directory: {relative}")
    values: dict[str, str] = {}
    if directory.is_dir():
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise BaselineEvaluationError(
                    f"agent baseline surface cannot contain symlinks: {path.relative_to(root)}"
                )
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                values[str(path.relative_to(root))] = digest(path)
    if required and not values:
        raise BaselineEvaluationError(f"agent baseline requires at least one file under {relative}")
    return values


def remove_file(path: Path) -> None:
    if path.is_symlink():
        raise BaselineEvaluationError(f"refusing to replace symlinked lifecycle artifact: {path}")
    if path.is_file():
        path.unlink()


def evaluate_baseline(
    root: Path, run_path: Path, target_command: list[str]
) -> dict[str, Any]:
    state = load_state(root)
    if state.get("lifecycle") != "first-build" or state.get("stage") != "baseline":
        raise BaselineEvaluationError("lifecycle is not waiting for first-build baseline evaluation")
    if not isinstance(target_command, list) or not target_command or not all(
        isinstance(argument, str) and argument for argument in target_command
    ):
        raise BaselineEvaluationError("target command must be a non-empty argument vector")
    if run_path.is_symlink():
        raise BaselineEvaluationError("native run artifact must be a regular repository file")
    try:
        resolved_run = run_path.resolve()
        relative_run = resolved_run.relative_to(root.resolve())
    except ValueError as error:
        raise BaselineEvaluationError("native run artifact must remain inside the repository") from error
    run = read_object(resolved_run, "native held-in run artifact")
    if run.get("target_command") != target_command:
        raise BaselineEvaluationError("native run target command does not match the requested target command")
    suite_path = root / SUITE_PATH
    suite_sha256 = digest(suite_path) if suite_path.is_file() and not suite_path.is_symlink() else None
    try:
        suite = read_suite(suite_path)
        suite_issues = validate_suite(suite)
    except (OSError, ValueError) as error:
        suite_issues = [str(error)]
        suite = {"cases": []}
    issues = [issue("data", f"eval suite is invalid: {message}") for message in suite_issues]
    run_issues, artifacts = inspect_run(suite, run, str(suite_sha256)) if not suite_issues else ([], [])
    issues.extend(run_issues)
    if not issues:
        gate = decide_gate(artifacts, gate="held_in")
        if not gate.proceed:
            owner = "target_agent" if gate.decision == "reject" else "harness"
            issues.append(issue(owner, gate.reason))
    if issues:
        owner = selected_owner(issues)
        decision = {
            "version": 1,
            "status": "complete",
            "decision": "rejected" if owner == "target_agent" else "inconclusive",
            "owner": owner,
            "route": OWNER_ROUTES[owner],
            "reason": issues[0]["reason"],
            "run_path": str(relative_run),
            "run_sha256": digest(resolved_run),
            "suite_sha256": suite_sha256,
        }
        diagnostic = {
            "version": 1,
            "status": decision["decision"],
            "owner": owner,
            "route": decision["route"],
            "source": {"path": str(relative_run), "sha256": decision["run_sha256"]},
            "issues": issues,
        }
        atomic_json(root / DECISION_PATH, decision)
        atomic_json(root / DIAGNOSTIC_PATH, diagnostic)
        remove_file(root / BASELINE_PATH)
    else:
        prompts = surface_digests(root, "agent/prompts", required=True)
        tools = surface_digests(root, "agent/tools", required=False)
        baseline = {
            "version": 1,
            "status": "operational",
            "target_command": target_command,
            "suite_sha256": suite_sha256,
            "run_path": str(relative_run),
            "run_sha256": digest(resolved_run),
            "prompt_sha256": prompts,
            "toolset_sha256": tools,
        }
        atomic_json(root / BASELINE_PATH, baseline)
        decision = {
            "version": 1,
            "status": "complete",
            "decision": "accepted",
            "owner": None,
            "route": None,
            "reason": "all required held-in eval cases and trials passed",
            "run_path": str(relative_run),
            "run_sha256": digest(resolved_run),
            "suite_sha256": digest(suite_path),
            "baseline_path": str(BASELINE_PATH),
            "baseline_sha256": digest(root / BASELINE_PATH),
        }
        atomic_json(root / DECISION_PATH, decision)
        remove_file(root / DIAGNOSTIC_PATH)
    state["baseline_evaluation"] = {
        "decision": decision["decision"],
        "owner": decision["owner"],
        "route": decision["route"],
        "decision_path": str(DECISION_PATH),
        "decision_sha256": digest(root / DECISION_PATH),
    }
    save_state(root, state)
    return decision


def validate_baseline_decision(root: Path) -> list[str]:
    try:
        decision = read_object(root / DECISION_PATH, "baseline decision")
    except BaselineEvaluationError as error:
        return [str(error)]
    if decision.get("decision") != "accepted":
        return [f"baseline evaluation did not pass: {decision.get('reason') or 'unknown reason'}"]
    try:
        baseline = read_object(root / BASELINE_PATH, "agent baseline")
    except BaselineEvaluationError as error:
        return [str(error)]
    issues: list[str] = []
    if baseline.get("version") != 1 or baseline.get("status") != "operational":
        issues.append("agent baseline must be version 1 and operational")
    suite_path = root / SUITE_PATH
    if baseline.get("suite_sha256") != digest(suite_path):
        issues.append("agent baseline references a stale eval suite")
    run_path = root / str(baseline.get("run_path") or "")
    if run_path.is_symlink() or not run_path.is_file() or baseline.get("run_sha256") != digest(run_path):
        issues.append("agent baseline references a missing or stale native run")
    for field, relative, required in (
        ("prompt_sha256", "agent/prompts", True),
        ("toolset_sha256", "agent/tools", False),
    ):
        try:
            current = surface_digests(root, relative, required)
        except BaselineEvaluationError as error:
            issues.append(str(error))
            continue
        if baseline.get(field) != current:
            issues.append(f"agent baseline {field.replace('_', ' ')} changed before operational entry")
    if decision.get("baseline_path") != str(BASELINE_PATH) or decision.get("baseline_sha256") != digest(root / BASELINE_PATH):
        issues.append("baseline decision references a stale agent baseline")
    return issues
