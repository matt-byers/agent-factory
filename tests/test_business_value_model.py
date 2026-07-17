from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.business_value import (
    INPUT_FIELDS,
    BusinessModelError,
    calculate_model,
    create_projections,
    render_markdown,
    validate_projection,
)


def scenario(**overrides: float) -> dict:
    values = {
        "eligible_volume": 10_000,
        "adoption_rate": 0.5,
        "baseline_success_rate": 0.6,
        "target_success_rate": 0.8,
        "attribution_rate": 0.8,
        "revenue_per_success": 100,
        "gross_margin_rate": 0.5,
        "minutes_saved_per_adopted_task": 6,
        "loaded_labor_cost_per_hour": 60,
        "error_rate_reduction": 0.05,
        "cost_per_error": 200,
        "loss_rate_reduction": 0.01,
        "loss_per_event": 500,
        "variable_run_cost_per_adopted_task": 2,
        "annual_fixed_cost": 14_000,
        "implementation_cost": 30_000,
    }
    values.update(overrides)
    values["evidence"] = {
        field: {
            "assumption": f"Fixture assumption for {field}",
            "source": f"Fixture source for {field}",
            "owner": "Finance owner",
        }
        for field in INPUT_FIELDS
    }
    return values


def complete_model() -> dict:
    return {
        "version": 1,
        "currency": "USD",
        "economic_units": {
            "revenue": "incremental-success-gross-profit",
            "time_savings": "support-handling-minutes",
            "rework_avoidance": "avoidable-rework-events",
            "loss_avoidance": "avoidable-loss-events",
        },
        "scenarios": {
            "conservative": scenario(
                adoption_rate=0.4,
                target_success_rate=0.72,
                attribution_rate=0.7,
                revenue_per_success=90,
                gross_margin_rate=0.45,
                minutes_saved_per_adopted_task=4,
                loaded_labor_cost_per_hour=55,
                error_rate_reduction=0.03,
                cost_per_error=180,
                loss_rate_reduction=0.005,
                loss_per_event=400,
                variable_run_cost_per_adopted_task=2.5,
            ),
            "base": scenario(),
            "upside": scenario(
                adoption_rate=0.65,
                target_success_rate=0.9,
                attribution_rate=0.9,
                revenue_per_success=110,
                gross_margin_rate=0.55,
                minutes_saved_per_adopted_task=8,
                loaded_labor_cost_per_hour=65,
                error_rate_reduction=0.08,
                cost_per_error=220,
                loss_rate_reduction=0.02,
                loss_per_event=600,
                variable_run_cost_per_adopted_task=1.5,
            ),
        },
    }


def disable_benefits(values: dict, keep: set[str]) -> None:
    fields = {
        "revenue": ("revenue_per_success",),
        "time_savings": ("minutes_saved_per_adopted_task",),
        "rework_avoidance": ("error_rate_reduction",),
        "loss_avoidance": ("loss_rate_reduction",),
    }
    for benefit, benefit_fields in fields.items():
        if benefit not in keep:
            for scenario_values in values["scenarios"].values():
                for field in benefit_fields:
                    scenario_values[field] = 0


def test_base_scenario_golden_unit_economics() -> None:
    result = calculate_model(complete_model())["scenarios"]["base"]["results"]

    assert result == {
        "adopted_tasks": 5000.0,
        "incremental_successful_outcomes": 800.0,
        "revenue_gross_profit": 40000.0,
        "time_savings_value": 24000.0,
        "rework_avoidance_value": 40000.0,
        "loss_avoidance_value": 20000.0,
        "annual_gross_value": 124000.0,
        "annual_run_cost": 24000.0,
        "annual_net_value": 100000.0,
        "first_year_net_value": 70000.0,
        "contribution_per_adopted_task": 22.8,
        "value_per_successful_outcome": 155.0,
        "maximum_viable_run_cost_per_adopted_task": 22.0,
        "break_even_eligible_volume": 3859.649123,
        "break_even_adoption_rate": 0.192982,
        "break_even_target_success_rate": 0.6,
        "payback_period_months": 3.6,
    }


@pytest.mark.parametrize(
    "benefit,expected_field,expected_value",
    [
        ("revenue", "revenue_gross_profit", 40000.0),
        ("time_savings", "time_savings_value", 24000.0),
        ("loss_avoidance", "loss_avoidance_value", 20000.0),
    ],
)
def test_golden_single_value_driver_models(
    benefit: str, expected_field: str, expected_value: float
) -> None:
    model = complete_model()
    disable_benefits(model, {benefit})

    result = calculate_model(model)["scenarios"]["base"]["results"]

    assert result[expected_field] == expected_value
    assert result["annual_gross_value"] == expected_value


@pytest.mark.parametrize("missing_field", INPUT_FIELDS)
def test_missing_required_input_is_rejected(missing_field: str) -> None:
    model = complete_model()
    model["scenarios"]["base"].pop(missing_field)

    with pytest.raises(BusinessModelError, match=f"base.{missing_field} is required"):
        calculate_model(model)


@pytest.mark.parametrize(
    "field,value,diagnostic",
    [
        ("adoption_rate", 1.1, "must be between 0 and 1"),
        ("target_success_rate", 0.5, "cannot be below baseline success"),
        ("annual_fixed_cost", -1, "cannot be negative"),
    ],
)
def test_contradictory_or_invalid_inputs_are_rejected(
    field: str, value: float, diagnostic: str
) -> None:
    model = complete_model()
    model["scenarios"]["base"][field] = value

    with pytest.raises(BusinessModelError, match=diagnostic):
        calculate_model(model)


def test_duplicate_economic_unit_rejects_double_counting() -> None:
    model = complete_model()
    model["economic_units"]["rework_avoidance"] = model["economic_units"]["time_savings"]

    with pytest.raises(
        BusinessModelError,
        match="time_savings and rework_avoidance claim the same economic unit",
    ):
        calculate_model(model)


def test_every_input_requires_assumption_source_and_owner() -> None:
    model = complete_model()
    del model["scenarios"]["base"]["evidence"]["eligible_volume"]["source"]

    with pytest.raises(BusinessModelError, match="base.eligible_volume evidence requires assumption, source, and owner"):
        calculate_model(model)


def test_scenario_boundaries_must_remain_conservative_base_upside() -> None:
    model = complete_model()
    model["scenarios"]["conservative"] = scenario(
        adoption_rate=0.99,
        target_success_rate=0.99,
        attribution_rate=0.99,
        revenue_per_success=500,
        gross_margin_rate=0.9,
    )

    with pytest.raises(BusinessModelError, match="scenario boundaries"):
        calculate_model(model)


def test_break_even_returns_unavailable_when_contribution_is_not_positive() -> None:
    model = complete_model()
    disable_benefits(model, set())

    result = calculate_model(model)["scenarios"]["base"]["results"]

    assert result["break_even_eligible_volume"] is None
    assert result["break_even_adoption_rate"] is None
    assert result["payback_period_months"] is None


def test_yaml_and_markdown_projections_are_deterministic_and_traceable(tmp_path: Path) -> None:
    paths = create_projections(complete_model(), tmp_path)
    document = json.loads(paths["yaml"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert validate_projection(paths["yaml"], paths["markdown"]) == []
    assert document["status"] == "complete"
    assert document["scenarios"]["base"]["results"]["annual_net_value"] == 100000.0
    assert "| Base | $124,000.00 | $100,000.00 | $70,000.00 | 3.60 |" in markdown
    assert "Maximum viable run cost" in markdown
    assert "Break-even adoption" in markdown
    assert "Fixture source for eligible_volume" in markdown
    assert markdown == render_markdown(calculate_model(complete_model()))


def test_pending_repository_projections_do_not_claim_value() -> None:
    yaml_path = REPOSITORY_ROOT / "agent-lifecycle/agent-definition/business-value-model.yaml"
    markdown_path = REPOSITORY_ROOT / "agent-lifecycle/agent-definition/business-value-model.md"

    assert json.loads(yaml_path.read_text(encoding="utf-8"))["status"] == "pending"
    assert "Status: pending" in markdown_path.read_text(encoding="utf-8")
    assert "business value model is pending" in validate_projection(yaml_path, markdown_path)


def test_lifecycle_rejects_pending_business_value_model(tmp_path: Path) -> None:
    root = tmp_path / "target"
    business_yaml = REPOSITORY_ROOT / "agent-lifecycle/agent-definition/business-value-model.yaml"
    business_markdown = REPOSITORY_ROOT / "agent-lifecycle/agent-definition/business-value-model.md"
    brief = root / "agent-lifecycle/agent-definition/project-brief.md"
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text(
        """# Agent Project Brief

Status: complete

## Purpose
Fixture purpose.
## Target Users
Fixture users.
## User Problem
Fixture problem.
## Current Workflow
Fixture workflow.
## Agent Scope
Fixture scope.
## Accuracy, Latency, and Cost Priorities
Fixture priorities.
## Risks and Failure Cost
Fixture risk.
## Success Outcomes
- `fixture-outcome` (business): Fixture outcome.
""",
        encoding="utf-8",
    )
    metrics = root / "agent-lifecycle/agent-definition/success-metrics.yaml"
    metrics.write_text(
        json.dumps(
            {
                "version": 1,
                "status": "complete",
                "outcomes": [{"id": "fixture-outcome", "type": "business", "description": "Fixture", "observation": "Fixture"}],
                "metrics": [{
                    "id": "fixture-metric", "name": "Fixture", "outcome_ids": ["fixture-outcome"],
                    "direction": "increase", "baseline": {"value": 1, "unit": "count", "source": "fixture"},
                    "target": {"value": 2, "unit": "count"}, "data_source": "fixture", "owner": "fixture", "cadence": "weekly",
                }],
            }
        ),
        encoding="utf-8",
    )
    for source in (business_yaml, business_markdown):
        destination = root / source.relative_to(REPOSITORY_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    start = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-lifecycle"), "--root", str(root), "start", "first-build"],
        text=True,
        capture_output=True,
        check=False,
    )
    advance = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-lifecycle"), "--root", str(root), "next"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert start.returncode == 0
    assert advance.returncode == 1
    assert "business value model is pending" in advance.stdout


def test_cli_calculates_and_validates_model(tmp_path: Path) -> None:
    source = tmp_path / "model.json"
    source.write_text(json.dumps(complete_model()), encoding="utf-8")
    root = tmp_path / "target"

    calculate = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-business-value"), "--root", str(root), "calculate", "--input", str(source)],
        text=True,
        capture_output=True,
        check=False,
    )
    validate = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-business-value"), "--root", str(root), "validate"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert calculate.returncode == validate.returncode == 0
    assert json.loads(calculate.stdout)["status"] == "complete"
    assert json.loads(validate.stdout) == {"errors": [], "status": "valid"}


def test_goal_interview_skill_collects_commercial_inputs_before_advancing() -> None:
    skill = (REPOSITORY_ROOT / ".claude/skills/agent-goal-interview/SKILL.md").read_text(encoding="utf-8")
    guide = (
        REPOSITORY_ROOT / ".claude/skills/agent-goal-interview/references/interview-guide.md"
    ).read_text(encoding="utf-8")

    assert "scripts/agent-business-value" in skill
    for phrase in ("eligible volume", "unit economics", "double counting", "payback"):
        assert phrase in guide.lower()
