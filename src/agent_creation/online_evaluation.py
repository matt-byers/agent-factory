from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


PLAN_PATH = Path("agent-lifecycle/evals/online-eval-plan.yaml")
INVENTORY_PATH = Path("agent-lifecycle/evidence/online-trace-inventory.json")
REPORT_PATH = Path("agent-lifecycle/evidence/online-eval-report.yaml")
REVIEW_BATCH_PATH = Path("agent-lifecycle/evidence/online-review-batch.yaml")
REVIEW_DECISION_PATH = Path("agent-lifecycle/evidence/online-review-decision.yaml")
ROUTES = {
    "agent_failure": "agent-improvement",
    "eval_failure": "eval-improvement",
    "provider_failure": "evidence-repair",
    "new_coverage": "eval-candidate",
}


class OnlineEvalError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


@dataclass(frozen=True)
class OnlineTrace:
    trace_id: str
    source_link: str
    scores: dict[str, float]


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_integer(value: Any, *, allow_zero: bool = False) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and (
        value >= 0 if allow_zero else value > 0
    )


def validate_online_eval_plan(
    plan: dict[str, Any], available_eval_ids: set[str] | None = None
) -> list[str]:
    if not isinstance(plan, dict):
        return ["online eval plan must contain an object"]
    issues: list[str] = []
    if plan.get("version") != 1:
        issues.append("online eval plan version must be 1")
    if plan.get("status") != "complete":
        issues.append("online eval plan status must be complete")
    mode = plan.get("mode")
    if mode not in {"enabled", "disabled"}:
        issues.append("online eval plan mode must be enabled or disabled")
        return issues
    if mode == "disabled":
        if not _non_empty(plan.get("reason")):
            issues.append("disabled online eval plan requires a reason")
        return issues
    if plan.get("provider") != "langfuse":
        issues.append("enabled online eval provider must be langfuse")
    scope = plan.get("trace_scope")
    if not isinstance(scope, dict) or not _non_empty(scope.get("trace_name")):
        issues.append("trace scope trace name is required")
    elif not _non_empty(scope.get("environment")):
        issues.append("trace scope environment is required")
    evaluators = plan.get("evaluators")
    if not isinstance(evaluators, list) or not evaluators:
        issues.append("at least one online evaluator is required")
        evaluators = []
    identifiers: set[str] = set()
    score_names: set[str] = set()
    for index, evaluator in enumerate(evaluators):
        label = f"online evaluator {index + 1}"
        if not isinstance(evaluator, dict):
            issues.append(f"{label} must contain an object")
            continue
        identifier = evaluator.get("id")
        if not _non_empty(identifier) or identifier in identifiers:
            issues.append(f"{label} requires a unique id")
        else:
            identifiers.add(identifier)
        source_ids = evaluator.get("source_eval_ids")
        if not isinstance(source_ids, list) or not source_ids or not all(
            _non_empty(item) for item in source_ids
        ):
            issues.append(f"{label} source eval ids are required")
        elif available_eval_ids is not None:
            for source_id in source_ids:
                if source_id not in available_eval_ids:
                    issues.append(f"{label} links unknown source eval: {source_id}")
        if evaluator.get("target") not in {"trace", "observation"}:
            issues.append(f"{label} target must be trace or observation")
        if evaluator.get("method") not in {"llm_judge", "code"}:
            issues.append(f"{label} method must be llm_judge or code")
        score_name = evaluator.get("score_name")
        if not _non_empty(score_name) or score_name in score_names:
            issues.append(f"{label} requires a unique score name")
        else:
            score_names.add(score_name)
        sampling_rate = evaluator.get("sampling_rate")
        if (
            not isinstance(sampling_rate, (int, float))
            or isinstance(sampling_rate, bool)
            or not 0 < float(sampling_rate) <= 1
        ):
            issues.append(f"{label} sampling rate must be greater than 0 and at most 1")
        score_floor = evaluator.get("score_floor")
        if not isinstance(score_floor, (int, float)) or isinstance(score_floor, bool):
            issues.append(f"{label} score floor must be numeric")
        mapping = evaluator.get("input_mapping")
        if not isinstance(mapping, dict) or not mapping or not all(
            _non_empty(key) and _non_empty(value) for key, value in mapping.items()
        ):
            issues.append(f"{label} input mapping is required")
    review = plan.get("review_policy")
    if not isinstance(review, dict):
        issues.append("review policy is required")
    else:
        if not _non_empty(review.get("queue_name")):
            issues.append("review policy queue name is required")
        if not _non_empty(review.get("expert_role")):
            issues.append("review policy expert role is required")
        if not _non_empty(review.get("cadence")):
            issues.append("review policy cadence is required")
        if not _positive_integer(review.get("failure_limit")):
            issues.append("review policy failure limit must be positive")
        if not _positive_integer(review.get("random_sample_limit"), allow_zero=True):
            issues.append("review policy random sample limit must be zero or positive")
        if not isinstance(review.get("include_unscored"), bool):
            issues.append("review policy include unscored must be boolean")
    privacy = plan.get("privacy")
    if not isinstance(privacy, dict):
        issues.append("privacy policy is required")
    else:
        if privacy.get("content_capture") not in {"approved", "metadata-only"}:
            issues.append("privacy content capture must be approved or metadata-only")
        if privacy.get("redaction_required") is not True:
            issues.append("privacy redaction must be required")
        if not _positive_integer(privacy.get("retention_days")):
            issues.append("privacy retention days must be positive")
    routes = plan.get("feedback_routes")
    if routes != ROUTES:
        issues.append("feedback routes must define the canonical disposition targets")
    return list(dict.fromkeys(issues))


def create_online_eval_plan(
    root: Path, plan: dict[str, Any], available_eval_ids: set[str] | None = None
) -> Path:
    issues = validate_online_eval_plan(plan, available_eval_ids)
    if issues:
        raise OnlineEvalError(issues)
    path = root / PLAN_PATH
    _atomic_write(path, plan)
    return path


def required_scores(plan: dict[str, Any]) -> dict[str, float]:
    return {
        evaluator["score_name"]: float(evaluator["score_floor"])
        for evaluator in plan.get("evaluators", [])
        if isinstance(evaluator, dict)
        and _non_empty(evaluator.get("score_name"))
        and isinstance(evaluator.get("score_floor"), (int, float))
    }


def trace_failures(plan: dict[str, Any], trace: OnlineTrace) -> list[str]:
    return sorted(
        score_name
        for score_name, floor in required_scores(plan).items()
        if score_name in trace.scores and trace.scores[score_name] < floor
    )


def build_online_report(
    plan: dict[str, Any], traces: list[OnlineTrace], eligible_count: int | None = None
) -> dict[str, Any]:
    issues = validate_online_eval_plan(plan)
    if issues:
        raise OnlineEvalError(issues)
    if plan["mode"] != "enabled":
        raise OnlineEvalError(["online eval reporting requires an enabled plan"])
    eligible = len(traces) if eligible_count is None else eligible_count
    if eligible < len(traces):
        raise OnlineEvalError(["eligible count cannot be smaller than inspected traces"])
    score_floors = required_scores(plan)
    fully_scored = sum(
        1 for trace in traces if all(name in trace.scores for name in score_floors)
    )
    failed = sum(1 for trace in traces if trace_failures(plan, trace))
    evaluator_report: dict[str, Any] = {}
    for score_name, floor in score_floors.items():
        values = [trace.scores[score_name] for trace in traces if score_name in trace.scores]
        evaluator_report[score_name] = {
            "score_floor": floor,
            "scored_count": len(values),
            "failed_count": sum(value < floor for value in values),
            "mean_score": round(sum(values) / len(values), 6) if values else None,
            "coverage": round(len(values) / eligible, 6) if eligible else 0.0,
        }
    return {
        "version": 1,
        "status": "complete",
        "eligible_count": eligible,
        "inspected_count": len(traces),
        "fully_scored_count": fully_scored,
        "unscored_or_partial_count": len(traces) - fully_scored,
        "failed_count": failed,
        "score_coverage": round(fully_scored / eligible, 6) if eligible else 0.0,
        "evaluators": evaluator_report,
    }


def select_review_batch(
    plan: dict[str, Any], traces: list[OnlineTrace], eligible_count: int | None = None
) -> dict[str, Any]:
    report = build_online_report(plan, traces, eligible_count)
    review = plan["review_policy"]
    score_names = set(required_scores(plan))
    selected: dict[str, dict[str, Any]] = {}
    failures = sorted(
        (trace for trace in traces if trace_failures(plan, trace)),
        key=lambda item: item.trace_id,
    )[: review["failure_limit"]]
    for trace in failures:
        selected[trace.trace_id] = _review_item(
            trace, ["score-floor-failure"], trace_failures(plan, trace)
        )
    if review["include_unscored"]:
        for trace in sorted(traces, key=lambda item: item.trace_id):
            if trace.trace_id in selected:
                continue
            if not score_names.issubset(trace.scores):
                selected[trace.trace_id] = _review_item(
                    trace, ["missing-online-score"], []
                )
    candidates = [
        trace
        for trace in traces
        if trace.trace_id not in selected and score_names.issubset(trace.scores)
    ]
    candidates.sort(
        key=lambda item: (
            hashlib.sha256(item.trace_id.encode()).hexdigest(),
            item.trace_id,
        )
    )
    for trace in candidates[: review["random_sample_limit"]]:
        selected[trace.trace_id] = _review_item(trace, ["random-calibration"], [])
    return {
        "version": 1,
        "status": "ready-for-expert-review",
        "queue_name": review["queue_name"],
        "expert_role": review["expert_role"],
        "report": report,
        "selection_policy": {
            "failure_limit": review["failure_limit"],
            "random_sample_limit": review["random_sample_limit"],
            "include_unscored": review["include_unscored"],
        },
        "items": list(selected.values()),
        "routing_options": plan["feedback_routes"],
    }


def route_review_batch(batch: dict[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(batch, dict)
        or batch.get("status") not in {"ready-for-expert-review", "reviewed"}
        or not isinstance(batch.get("items"), list)
        or not batch["items"]
    ):
        raise OnlineEvalError(["online review batch is missing or invalid"])
    routed: dict[str, list[dict[str, Any]]] = {
        target: [] for target in ROUTES.values()
    }
    for index, item in enumerate(batch["items"]):
        if not isinstance(item, dict):
            raise OnlineEvalError([f"online review item {index + 1} is invalid"])
        disposition = item.get("expert_disposition")
        if disposition not in ROUTES:
            raise OnlineEvalError(
                [f"online review item {index + 1} requires one expert disposition"]
            )
        if not _non_empty(item.get("expert_comment")):
            raise OnlineEvalError(
                [f"online review item {index + 1} requires an expert comment"]
            )
        routed[ROUTES[disposition]].append(
            {
                "trace_id": item.get("trace_id"),
                "source_link": item.get("source_link"),
                "disposition": disposition,
                "expert_comment": item["expert_comment"],
            }
        )
    return {
        "version": 1,
        "status": "complete",
        "queue_name": batch.get("queue_name"),
        "routes": routed,
        "next_actions": {
            "agent-improvement": "Promote each selected trace as diagnostic production evidence, then invoke /agent-self-improvement.",
            "eval-improvement": "Repair or recalibrate the evaluator and rerun the affected online evidence.",
            "evidence-repair": "Repair provider instrumentation, mappings or evaluator execution before judging agent quality.",
            "eval-candidate": "Promote each trace as an eval candidate for expert validation by /agent-eval-designer.",
        },
    }


def read_online_traces(path: Path) -> tuple[list[OnlineTrace], int | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OnlineEvalError([f"online trace input is invalid: {error}"]) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("traces"), list):
        raise OnlineEvalError(["online trace input must contain a traces list"])
    traces: list[OnlineTrace] = []
    for index, item in enumerate(payload["traces"]):
        if (
            not isinstance(item, dict)
            or not _non_empty(item.get("trace_id"))
            or not _non_empty(item.get("source_link"))
            or not isinstance(item.get("scores"), dict)
        ):
            raise OnlineEvalError([f"online trace {index + 1} is invalid"])
        scores: dict[str, float] = {}
        for name, value in item["scores"].items():
            if not _non_empty(name) or not isinstance(value, (int, float)) or isinstance(value, bool):
                raise OnlineEvalError([f"online trace {index + 1} has an invalid score"])
            scores[name] = float(value)
        traces.append(OnlineTrace(item["trace_id"], item["source_link"], scores))
    eligible = payload.get("eligible_count")
    if eligible is not None and not _positive_integer(eligible, allow_zero=True):
        raise OnlineEvalError(["eligible count must be zero or positive"])
    return traces, eligible


def _review_item(
    trace: OnlineTrace, reasons: list[str], failed_scores: list[str]
) -> dict[str, Any]:
    return {
        "trace_id": trace.trace_id,
        "source_link": trace.source_link,
        "scores": dict(sorted(trace.scores.items())),
        "failed_scores": failed_scores,
        "selection_reasons": reasons,
        "expert_disposition": "pending",
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
