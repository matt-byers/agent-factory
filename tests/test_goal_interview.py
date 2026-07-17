from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.goal_definition import ContractError, assess_interview, create_artifacts, validate_artifacts


def complete_interview() -> dict:
    return {
        "purpose": "Help support agents resolve account questions accurately with less manual searching.",
        "target_users": ["Customer-support agents"],
        "user_problem": "Answers require searching several policy sources and are slow and inconsistent.",
        "current_workflow": "An agent searches policy documents, checks account context, and drafts a response.",
        "in_scope": ["Retrieve approved policy context", "Draft an evidence-linked response"],
        "out_of_scope": ["Change account records", "Make policy exceptions"],
        "editable_surfaces": ["prompts", "context", "workflow", "agent_tool_contracts"],
        "risks": [
            {
                "risk": "An unsupported answer reaches a customer",
                "failure_cost": "Rework, customer harm, and possible compliance escalation",
            }
        ],
        "priorities": {
            "accuracy": {"order": 1, "rationale": "Unsupported answers create material customer risk."},
            "latency": {"order": 2, "rationale": "Answers must fit within a live support interaction."},
            "cost": {"order": 3, "rationale": "Run cost matters after accuracy and response time."},
        },
        "outcomes": [
            {
                "id": "user-fast-supported-answer",
                "type": "user",
                "description": "A support agent receives a correct evidence-linked answer quickly.",
                "observation": "Reviewed conversations contain a supported answer within the handling target.",
            },
            {
                "id": "business-lower-handling-time",
                "type": "business",
                "description": "Average handling time falls without increasing rework.",
                "observation": "Support analytics show lower handling time and stable recontact rate.",
            },
        ],
        "metrics": [
            {
                "id": "supported-answer-rate",
                "name": "Supported answer rate",
                "outcome_ids": ["user-fast-supported-answer"],
                "direction": "increase",
                "baseline": {"value": 0.72, "unit": "ratio", "source": "QA review sample"},
                "target": {"value": 0.92, "unit": "ratio"},
                "data_source": "Weekly QA review",
                "owner": "Support operations",
                "cadence": "weekly",
            },
            {
                "id": "handling-time",
                "name": "Average handling time",
                "outcome_ids": ["business-lower-handling-time"],
                "direction": "decrease",
                "baseline": {"value": 18, "unit": "minutes", "source": "Support analytics"},
                "target": {"value": 12, "unit": "minutes"},
                "data_source": "Support analytics",
                "owner": "Support operations",
                "cadence": "monthly",
            },
        ],
    }


def test_clear_interview_creates_complete_self_contained_artifacts(tmp_path: Path) -> None:
    result = assess_interview(complete_interview())
    assert result == {"status": "complete", "follow_up_questions": []}

    paths = create_artifacts(complete_interview(), tmp_path)

    assert paths == {
        "project_brief": tmp_path / "agent-lifecycle/agent-definition/project-brief.md",
        "success_metrics": tmp_path / "agent-lifecycle/agent-definition/success-metrics.yaml",
    }
    brief = paths["project_brief"].read_text(encoding="utf-8")
    metrics = json.loads(paths["success_metrics"].read_text(encoding="utf-8"))
    assert "Customer-support agents" in brief
    assert "Accuracy — priority 1" in brief
    assert "user-fast-supported-answer" in brief
    assert metrics["status"] == "complete"
    assert validate_artifacts(paths["project_brief"], paths["success_metrics"]) == []


def test_ambiguous_interview_returns_precise_follow_up_questions() -> None:
    interview = complete_interview()
    interview["target_users"] = []
    interview["outcomes"] = []
    interview["metrics"] = []

    result = assess_interview(interview)

    assert result["status"] == "needs_follow_up"
    assert result["follow_up_questions"] == [
        "Who will directly use or be affected by this agent?",
        "What observable user or business outcome would prove the agent is useful?",
        "Which metric, baseline, and target will measure each stated outcome?",
    ]


def test_contradictory_scope_is_rejected() -> None:
    interview = complete_interview()
    interview["in_scope"].append("Make policy exceptions")

    with pytest.raises(ContractError, match="both in and out of scope"):
        create_artifacts(interview, Path("unused"))


def test_surrounding_application_editable_surface_is_rejected() -> None:
    interview = complete_interview()
    interview["editable_surfaces"].append("database_schema")

    with pytest.raises(ContractError, match="outside the agent harness"):
        create_artifacts(interview, Path("unused"))


def test_success_metric_must_link_to_a_declared_outcome(tmp_path: Path) -> None:
    interview = complete_interview()
    interview["metrics"][0]["outcome_ids"] = ["unknown-outcome"]

    with pytest.raises(ContractError, match="unknown outcome"):
        create_artifacts(interview, tmp_path)


@pytest.mark.parametrize("missing_field", ["baseline", "target", "data_source", "owner", "cadence"])
def test_success_metric_must_be_measurable(missing_field: str, tmp_path: Path) -> None:
    interview = complete_interview()
    interview["metrics"][0].pop(missing_field)

    with pytest.raises(ContractError, match=missing_field.replace("_", " ")):
        create_artifacts(interview, tmp_path)


@pytest.mark.parametrize(
    "direction,baseline,target",
    [("increase", 0.8, 0.7), ("decrease", 10, 12)],
)
def test_metric_target_must_move_in_declared_direction(
    direction: str, baseline: float, target: float, tmp_path: Path
) -> None:
    interview = complete_interview()
    metric = interview["metrics"][0]
    metric["direction"] = direction
    metric["baseline"]["value"] = baseline
    metric["target"]["value"] = target

    with pytest.raises(ContractError, match="does not move"):
        create_artifacts(interview, tmp_path)


def test_priority_order_must_express_accuracy_latency_cost_tradeoff(tmp_path: Path) -> None:
    interview = complete_interview()
    interview["priorities"]["cost"]["order"] = 2

    with pytest.raises(ContractError, match="priority order"):
        create_artifacts(interview, tmp_path)


def test_pending_repository_artifacts_expose_contract_without_claiming_completion() -> None:
    brief = REPOSITORY_ROOT / "agent-lifecycle/agent-definition/project-brief.md"
    metrics = REPOSITORY_ROOT / "agent-lifecycle/agent-definition/success-metrics.yaml"

    assert "Status: pending" in brief.read_text(encoding="utf-8")
    assert json.loads(metrics.read_text(encoding="utf-8")) == {
        "version": 1,
        "status": "pending",
        "outcomes": [],
        "metrics": [],
    }
    errors = validate_artifacts(brief, metrics)
    assert "project brief is pending" in errors
    assert "success metrics are pending" in errors


def test_skill_is_fresh_context_complete_and_uses_deterministic_validation() -> None:
    skill = (REPOSITORY_ROOT / ".claude/skills/agent-goal-interview/SKILL.md").read_text(encoding="utf-8")
    guide = (
        REPOSITORY_ROOT / ".claude/skills/agent-goal-interview/references/interview-guide.md"
    ).read_text(encoding="utf-8")

    assert "scripts/agent-goal-interview" in skill
    assert "needs_follow_up" in skill
    assert "accuracy" in guide.lower() and "latency" in guide.lower() and "cost" in guide.lower()
    assert "failure cost" in guide.lower()


def test_cli_renders_and_validates_complete_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "interview.json"
    fixture.write_text(json.dumps(complete_interview()), encoding="utf-8")

    render = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/agent-goal-interview"),
            "--root",
            str(tmp_path / "target"),
            "render",
            "--input",
            str(fixture),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    validate = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/agent-goal-interview"),
            "--root",
            str(tmp_path / "target"),
            "validate",
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert render.returncode == validate.returncode == 0
    assert json.loads(render.stdout)["status"] == "complete"
    assert json.loads(validate.stdout) == {"status": "valid", "errors": []}


def test_lifecycle_cannot_advance_from_pending_templates(tmp_path: Path) -> None:
    root = tmp_path / "target"
    definition = root / "agent-lifecycle/agent-definition"
    definition.mkdir(parents=True)
    for name in ("project-brief.md", "success-metrics.yaml"):
        (definition / name).write_text(
            (REPOSITORY_ROOT / "agent-lifecycle/agent-definition" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (definition / "business-value-model.yaml").write_text("{}\n", encoding="utf-8")
    start = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-lifecycle"), "--root", str(root), "start", "first-build"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert start.returncode == 0

    result = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-lifecycle"), "--root", str(root), "next"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "goal artifacts are invalid" in json.loads(result.stdout)["error"]
