from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.online_evaluation import (
    OnlineEvalError,
    OnlineTrace,
    build_online_report,
    create_online_eval_plan,
    route_review_batch,
    select_review_batch,
    validate_online_eval_plan,
)


def enabled_plan() -> dict:
    return {
        "version": 1,
        "status": "complete",
        "mode": "enabled",
        "provider": "langfuse",
        "trace_scope": {
            "trace_name": "support-agent",
            "environment": "production",
            "filters": {"release": "stable"},
        },
        "evaluators": [
            {
                "id": "helpfulness-online",
                "source_eval_ids": ["support-resolution"],
                "target": "trace",
                "method": "llm_judge",
                "score_name": "helpfulness",
                "sampling_rate": 0.1,
                "score_floor": 0.8,
                "input_mapping": {"input": "trace.input", "output": "trace.output"},
            },
            {
                "id": "safe-tools-online",
                "source_eval_ids": ["support-resolution"],
                "target": "trace",
                "method": "code",
                "score_name": "safe_tools",
                "sampling_rate": 1.0,
                "score_floor": 1.0,
                "input_mapping": {"tool_calls": "trace.observations"},
            },
        ],
        "review_policy": {
            "queue_name": "support-agent-online-review",
            "expert_role": "Support domain expert",
            "cadence": "weekly",
            "failure_limit": 20,
            "random_sample_limit": 1,
            "include_unscored": True,
        },
        "privacy": {
            "content_capture": "approved",
            "redaction_required": True,
            "retention_days": 30,
        },
        "feedback_routes": {
            "agent_failure": "agent-improvement",
            "eval_failure": "eval-improvement",
            "provider_failure": "evidence-repair",
            "new_coverage": "eval-candidate",
        },
    }


def traces() -> list[OnlineTrace]:
    return [
        OnlineTrace(
            "failed",
            "https://langfuse.example/traces/failed",
            {"helpfulness": 0.4, "safe_tools": 1.0},
        ),
        OnlineTrace(
            "passed",
            "https://langfuse.example/traces/passed",
            {"helpfulness": 0.9, "safe_tools": 1.0},
        ),
        OnlineTrace(
            "unscored",
            "https://langfuse.example/traces/unscored",
            {},
        ),
        OnlineTrace(
            "partial",
            "https://langfuse.example/traces/partial",
            {"helpfulness": 0.9},
        ),
    ]


def test_plan_requires_explicit_online_scope_evaluators_review_privacy_and_routes() -> None:
    assert validate_online_eval_plan(enabled_plan(), {"support-resolution"}) == []

    invalid = enabled_plan()
    invalid["evaluators"][0]["sampling_rate"] = 0
    invalid["review_policy"].pop("queue_name")
    invalid["privacy"]["redaction_required"] = False

    issues = validate_online_eval_plan(invalid, {"support-resolution"})

    assert "sampling rate must be greater than 0 and at most 1" in "; ".join(issues)
    assert "review policy queue name is required" in issues
    assert "privacy redaction must be required" in issues


def test_disabled_plan_is_explicit_and_does_not_require_provider_configuration() -> None:
    plan = {
        "version": 1,
        "status": "complete",
        "mode": "disabled",
        "reason": "The target agent is not connected to production traffic.",
    }

    assert validate_online_eval_plan(plan, set()) == []


def test_report_preserves_denominators_and_score_coverage() -> None:
    report = build_online_report(enabled_plan(), traces(), eligible_count=10)

    assert report["eligible_count"] == 10
    assert report["inspected_count"] == 4
    assert report["fully_scored_count"] == 2
    assert report["unscored_or_partial_count"] == 2
    assert report["failed_count"] == 1
    assert report["score_coverage"] == 0.2
    assert report["evaluators"]["helpfulness"]["scored_count"] == 3
    assert report["evaluators"]["helpfulness"]["failed_count"] == 1
    assert report["evaluators"]["safe_tools"]["scored_count"] == 2


def test_review_batch_prioritizes_failures_then_unscored_and_random_calibration() -> None:
    batch = select_review_batch(enabled_plan(), traces(), eligible_count=10)

    selected = {item["trace_id"]: item for item in batch["items"]}
    assert selected["failed"]["selection_reasons"] == ["score-floor-failure"]
    assert selected["unscored"]["selection_reasons"] == ["missing-online-score"]
    assert selected["partial"]["selection_reasons"] == ["missing-online-score"]
    assert selected["passed"]["selection_reasons"] == ["random-calibration"]
    assert batch["queue_name"] == "support-agent-online-review"
    assert batch["routing_options"] == enabled_plan()["feedback_routes"]
    assert all("input" not in item and "output" not in item for item in batch["items"])


def test_completed_expert_review_routes_each_trace_to_one_owner() -> None:
    batch = select_review_batch(enabled_plan(), traces(), eligible_count=10)
    dispositions = ["agent_failure", "eval_failure", "provider_failure", "new_coverage"]
    for item, disposition in zip(batch["items"], dispositions, strict=True):
        item["expert_disposition"] = disposition
        item["expert_comment"] = f"Reviewed as {disposition}."

    decision = route_review_batch(batch)

    assert decision["status"] == "complete"
    assert sum(len(items) for items in decision["routes"].values()) == 4
    assert decision["routes"]["agent-improvement"][0]["disposition"] == "agent_failure"
    assert decision["routes"]["eval-improvement"][0]["disposition"] == "eval_failure"
    assert decision["routes"]["evidence-repair"][0]["disposition"] == "provider_failure"
    assert decision["routes"]["eval-candidate"][0]["disposition"] == "new_coverage"


def test_plan_render_and_cli_validation_are_deterministic(tmp_path: Path) -> None:
    plan_path = create_online_eval_plan(tmp_path, enabled_plan(), {"support-resolution"})
    first = plan_path.read_bytes()
    plan_path = create_online_eval_plan(tmp_path, enabled_plan(), {"support-resolution"})

    assert plan_path.read_bytes() == first

    result = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/agent-online-eval"),
            "--root",
            str(tmp_path),
            "validate",
            "--plan",
            str(plan_path),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"errors": [], "status": "valid"}


def test_invalid_plan_is_not_written(tmp_path: Path) -> None:
    plan = enabled_plan()
    plan["evaluators"][0]["source_eval_ids"] = ["unknown"]

    with pytest.raises(OnlineEvalError, match="unknown source eval"):
        create_online_eval_plan(tmp_path, plan, {"support-resolution"})

    assert not (tmp_path / "agent-lifecycle/evals/online-eval-plan.yaml").exists()


def test_skill_defines_plan_monitor_review_and_feedback_flow() -> None:
    skill = (
        REPOSITORY_ROOT
        / ".claude/skills/agent-online-eval-planner/SKILL.md"
    ).read_text(encoding="utf-8")
    template = (
        REPOSITORY_ROOT
        / ".claude/skills/agent-online-eval-planner/assets/online-eval-plan-template.yaml"
    )

    assert "Offline evaluation" in skill
    assert "Online evaluation" in skill
    assert "scripts/agent-online-eval report" in skill
    assert "random calibration" in skill
    assert "agent_failure" in skill and "eval_failure" in skill
    assert template.is_file()
