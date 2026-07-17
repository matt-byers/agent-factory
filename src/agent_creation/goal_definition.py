from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


BRIEF_PATH = Path("agent-lifecycle/agent-definition/project-brief.md")
METRICS_PATH = Path("agent-lifecycle/agent-definition/success-metrics.yaml")
ALLOWED_EDITABLE_SURFACES = {
    "prompts",
    "context",
    "workflow",
    "model_configuration",
    "agent_state",
    "memory_orchestration",
    "agent_tool_contracts",
    "middleware",
    "skills",
    "subagents",
}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")


class ContractError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def non_empty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(non_empty_string(item) for item in value)


def follow_up_questions(interview: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    if not non_empty_strings(interview.get("target_users")):
        questions.append("Who will directly use or be affected by this agent?")
    if not isinstance(interview.get("outcomes"), list) or not interview.get("outcomes"):
        questions.append("What observable user or business outcome would prove the agent is useful?")
    if not isinstance(interview.get("metrics"), list) or not interview.get("metrics"):
        questions.append("Which metric, baseline, and target will measure each stated outcome?")
    field_questions = {
        "purpose": "What is the agent's specific purpose?",
        "user_problem": "What user problem and failure cost should the agent address?",
        "current_workflow": "How is this work completed today?",
    }
    for field, question in field_questions.items():
        if not non_empty_string(interview.get(field)):
            questions.append(question)
    return questions


def validate_priorities(priorities: Any) -> list[str]:
    if not isinstance(priorities, dict) or set(priorities) != {"accuracy", "latency", "cost"}:
        return ["priorities must cover accuracy, latency, and cost"]
    orders: list[int] = []
    issues: list[str] = []
    for name in ("accuracy", "latency", "cost"):
        value = priorities[name]
        if not isinstance(value, dict) or not isinstance(value.get("order"), int):
            issues.append(f"{name} priority order is required")
            continue
        orders.append(value["order"])
        if not non_empty_string(value.get("rationale")):
            issues.append(f"{name} priority rationale is required")
    if sorted(orders) != [1, 2, 3]:
        issues.append("priority order must rank accuracy, latency, and cost uniquely from 1 to 3")
    return issues


def validate_outcomes(outcomes: Any) -> tuple[list[str], set[str]]:
    if not isinstance(outcomes, list) or not outcomes:
        return ["at least one observable outcome is required"], set()
    issues: list[str] = []
    identifiers: set[str] = set()
    for index, outcome in enumerate(outcomes):
        label = f"outcome {index + 1}"
        if not isinstance(outcome, dict):
            issues.append(f"{label} must be an object")
            continue
        identifier = outcome.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            issues.append(f"{label} id must use lowercase hyphen-case")
        elif identifier in identifiers:
            issues.append(f"duplicate outcome id: {identifier}")
        else:
            identifiers.add(identifier)
        if outcome.get("type") not in {"user", "business"}:
            issues.append(f"{label} type must be user or business")
        for field in ("description", "observation"):
            if not non_empty_string(outcome.get(field)):
                issues.append(f"{label} {field} is required")
    return issues, identifiers


def numeric_measure(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_metrics(metrics: Any, outcome_ids: set[str]) -> list[str]:
    if not isinstance(metrics, list) or not metrics:
        return ["at least one success metric is required"]
    issues: list[str] = []
    metric_ids: set[str] = set()
    linked_outcomes: set[str] = set()
    for index, metric in enumerate(metrics):
        label = f"metric {index + 1}"
        if not isinstance(metric, dict):
            issues.append(f"{label} must be an object")
            continue
        identifier = metric.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            issues.append(f"{label} id must use lowercase hyphen-case")
        elif identifier in metric_ids:
            issues.append(f"duplicate metric id: {identifier}")
        else:
            metric_ids.add(identifier)
        if not non_empty_string(metric.get("name")):
            issues.append(f"{label} name is required")
        links = metric.get("outcome_ids")
        if not non_empty_strings(links):
            issues.append(f"{label} must link at least one outcome")
        else:
            for outcome_id in links:
                if outcome_id not in outcome_ids:
                    issues.append(f"{label} links unknown outcome: {outcome_id}")
                else:
                    linked_outcomes.add(outcome_id)
        direction = metric.get("direction")
        if direction not in {"increase", "decrease", "maintain", "range"}:
            issues.append(f"{label} direction is invalid")
        for field in ("baseline", "target"):
            measure = metric.get(field)
            if not isinstance(measure, dict) or not numeric_measure(measure.get("value")) or not non_empty_string(measure.get("unit")):
                issues.append(f"{label} {field} requires a numeric value and unit")
        baseline = metric.get("baseline")
        if isinstance(baseline, dict) and not non_empty_string(baseline.get("source")):
            issues.append(f"{label} baseline source is required")
        for field in ("data_source", "owner", "cadence"):
            if not non_empty_string(metric.get(field)):
                issues.append(f"{label} {field.replace('_', ' ')} is required")
        if isinstance(baseline, dict) and isinstance(metric.get("target"), dict):
            target = metric["target"]
            if baseline.get("unit") != target.get("unit"):
                issues.append(f"{label} baseline and target units must match")
            if numeric_measure(baseline.get("value")) and numeric_measure(target.get("value")):
                if direction == "increase" and target["value"] <= baseline["value"]:
                    issues.append(f"{label} target does not move in the declared increase direction")
                if direction == "decrease" and target["value"] >= baseline["value"]:
                    issues.append(f"{label} target does not move in the declared decrease direction")
    for outcome_id in sorted(outcome_ids - linked_outcomes):
        issues.append(f"outcome has no success metric: {outcome_id}")
    return issues


def contract_issues(interview: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in ("purpose", "user_problem", "current_workflow"):
        if not non_empty_string(interview.get(field)):
            issues.append(f"{field.replace('_', ' ')} is required")
    for field in ("target_users", "in_scope", "out_of_scope", "editable_surfaces", "risks"):
        if not isinstance(interview.get(field), list) or not interview.get(field):
            issues.append(f"{field.replace('_', ' ')} must not be empty")
    if non_empty_strings(interview.get("in_scope")) and non_empty_strings(interview.get("out_of_scope")):
        overlap = {item.casefold() for item in interview["in_scope"]} & {
            item.casefold() for item in interview["out_of_scope"]
        }
        if overlap:
            issues.append("the same capability cannot be both in and out of scope: " + ", ".join(sorted(overlap)))
    surfaces = interview.get("editable_surfaces")
    if isinstance(surfaces, list):
        forbidden = sorted(set(surfaces) - ALLOWED_EDITABLE_SURFACES)
        if forbidden:
            issues.append("editable surfaces outside the agent harness: " + ", ".join(forbidden))
    risks = interview.get("risks")
    if isinstance(risks, list):
        for index, risk in enumerate(risks):
            if not isinstance(risk, dict) or not non_empty_string(risk.get("risk")) or not non_empty_string(risk.get("failure_cost")):
                issues.append(f"risk {index + 1} requires risk and failure cost")
    issues.extend(validate_priorities(interview.get("priorities")))
    outcome_issues, outcome_ids = validate_outcomes(interview.get("outcomes"))
    issues.extend(outcome_issues)
    issues.extend(validate_metrics(interview.get("metrics"), outcome_ids))
    return issues


def assess_interview(interview: dict[str, Any]) -> dict[str, Any]:
    questions = follow_up_questions(interview)
    if questions:
        return {"status": "needs_follow_up", "follow_up_questions": questions}
    issues = contract_issues(interview)
    if issues:
        return {"status": "invalid", "issues": issues, "follow_up_questions": []}
    return {"status": "complete", "follow_up_questions": []}


def render_list(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def render_project_brief(interview: dict[str, Any]) -> str:
    priorities = interview["priorities"]
    risks = "\n".join(
        f"- {item['risk']} — Failure cost: {item['failure_cost']}" for item in interview["risks"]
    )
    outcomes = "\n".join(
        f"- `{item['id']}` ({item['type']}): {item['description']} Observation: {item['observation']}"
        for item in interview["outcomes"]
    )
    priority_lines = "\n".join(
        f"- {name.title()} — priority {priorities[name]['order']}: {priorities[name]['rationale']}"
        for name in ("accuracy", "latency", "cost")
    )
    return f"""# Agent Project Brief

Status: complete

## Purpose

{interview['purpose']}

## Target Users

{render_list(interview['target_users'])}

## User Problem

{interview['user_problem']}

## Current Workflow

{interview['current_workflow']}

## Agent Scope

### In Scope

{render_list(interview['in_scope'])}

### Out of Scope

{render_list(interview['out_of_scope'])}

### Editable Agent Surfaces

{render_list(interview['editable_surfaces'])}

## Accuracy, Latency, and Cost Priorities

{priority_lines}

## Risks and Failure Cost

{risks}

## Success Outcomes

{outcomes}
"""


def metrics_document(interview: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "status": "complete",
        "outcomes": interview["outcomes"],
        "metrics": interview["metrics"],
    }


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def create_artifacts(interview: dict[str, Any], root: Path) -> dict[str, Path]:
    questions = follow_up_questions(interview)
    if questions:
        raise ContractError(questions)
    issues = contract_issues(interview)
    if issues:
        raise ContractError(issues)
    brief = root / BRIEF_PATH
    metrics = root / METRICS_PATH
    atomic_write(brief, render_project_brief(interview))
    atomic_write(metrics, json.dumps(metrics_document(interview), indent=2, sort_keys=True) + "\n")
    return {"project_brief": brief, "success_metrics": metrics}


def validate_artifacts(brief_path: Path, metrics_path: Path) -> list[str]:
    issues: list[str] = []
    try:
        brief = brief_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ["project brief is missing or unreadable"]
    try:
        document = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ["success metrics are missing or invalid"]
    if "Status: pending" in brief:
        issues.append("project brief is pending")
    elif "Status: complete" not in brief:
        issues.append("project brief completion status is missing")
    required_headings = (
        "## Purpose",
        "## Target Users",
        "## User Problem",
        "## Current Workflow",
        "## Agent Scope",
        "## Accuracy, Latency, and Cost Priorities",
        "## Risks and Failure Cost",
        "## Success Outcomes",
    )
    for heading in required_headings:
        if heading not in brief:
            issues.append(f"project brief section is missing: {heading}")
    if not isinstance(document, dict) or document.get("status") == "pending":
        issues.append("success metrics are pending")
        return issues
    if document.get("version") != 1:
        issues.append("success metrics version must be 1")
    outcome_issues, outcome_ids = validate_outcomes(document.get("outcomes"))
    issues.extend(outcome_issues)
    issues.extend(validate_metrics(document.get("metrics"), outcome_ids))
    for outcome_id in outcome_ids:
        if f"`{outcome_id}`" not in brief:
            issues.append(f"project brief is missing outcome: {outcome_id}")
    return issues
