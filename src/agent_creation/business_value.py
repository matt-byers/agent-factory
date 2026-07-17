from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


YAML_PATH = Path("agent-lifecycle/agent-definition/business-value-model.yaml")
MARKDOWN_PATH = Path("agent-lifecycle/agent-definition/business-value-model.md")
SCENARIO_NAMES = ("conservative", "base", "upside")
INPUT_FIELDS = (
    "eligible_volume", "adoption_rate", "baseline_success_rate", "target_success_rate",
    "attribution_rate", "revenue_per_success", "gross_margin_rate",
    "minutes_saved_per_adopted_task", "loaded_labor_cost_per_hour",
    "error_rate_reduction", "cost_per_error", "loss_rate_reduction", "loss_per_event",
    "variable_run_cost_per_adopted_task", "annual_fixed_cost", "implementation_cost",
)
RATE_FIELDS = {
    "adoption_rate", "baseline_success_rate", "target_success_rate", "attribution_rate",
    "gross_margin_rate", "error_rate_reduction", "loss_rate_reduction",
}
BENEFIT_FIELDS = {
    "revenue": "revenue_per_success",
    "time_savings": "minutes_saved_per_adopted_task",
    "rework_avoidance": "error_rate_reduction",
    "loss_avoidance": "loss_rate_reduction",
}


class BusinessModelError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


@dataclass(frozen=True)
class ScenarioInputs:
    eligible_volume: float
    adoption_rate: float
    baseline_success_rate: float
    target_success_rate: float
    attribution_rate: float
    revenue_per_success: float
    gross_margin_rate: float
    minutes_saved_per_adopted_task: float
    loaded_labor_cost_per_hour: float
    error_rate_reduction: float
    cost_per_error: float
    loss_rate_reduction: float
    loss_per_event: float
    variable_run_cost_per_adopted_task: float
    annual_fixed_cost: float
    implementation_cost: float


@dataclass(frozen=True)
class ScenarioResults:
    adopted_tasks: float
    incremental_successful_outcomes: float
    revenue_gross_profit: float
    time_savings_value: float
    rework_avoidance_value: float
    loss_avoidance_value: float
    annual_gross_value: float
    annual_run_cost: float
    annual_net_value: float
    first_year_net_value: float
    contribution_per_adopted_task: float | None
    value_per_successful_outcome: float | None
    maximum_viable_run_cost_per_adopted_task: float | None
    break_even_eligible_volume: float | None
    break_even_adoption_rate: float | None
    break_even_target_success_rate: float | None
    payback_period_months: float | None


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def parse_scenario(name: str, payload: Any) -> tuple[ScenarioInputs | None, list[str]]:
    if not isinstance(payload, dict):
        return None, [f"{name} scenario must be an object"]
    issues: list[str] = []
    values: dict[str, float] = {}
    for field in INPUT_FIELDS:
        if field not in payload:
            issues.append(f"{name}.{field} is required")
            continue
        value = payload[field]
        if not is_number(value):
            issues.append(f"{name}.{field} must be numeric")
            continue
        values[field] = float(value)
        if field in RATE_FIELDS and not 0 <= value <= 1:
            issues.append(f"{name}.{field} must be between 0 and 1")
        elif field not in RATE_FIELDS and value < 0:
            issues.append(f"{name}.{field} cannot be negative")
    if (
        "target_success_rate" in values and "baseline_success_rate" in values
        and values["target_success_rate"] < values["baseline_success_rate"]
    ):
        issues.append(f"{name}.target_success_rate cannot be below baseline success")
    if values.get("eligible_volume") == 0:
        issues.append(f"{name}.eligible_volume must be greater than zero")
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        issues.append(f"{name}.evidence is required")
    else:
        for field in INPUT_FIELDS:
            item = evidence.get(field)
            if not isinstance(item, dict) or not all(
                isinstance(item.get(key), str) and item[key].strip()
                for key in ("assumption", "source", "owner")
            ):
                issues.append(f"{name}.{field} evidence requires assumption, source, and owner")
    if issues:
        return None, issues
    return ScenarioInputs(**values), []


def calculate_scenario(inputs: ScenarioInputs) -> ScenarioResults:
    adopted = inputs.eligible_volume * inputs.adoption_rate
    incremental_successes = adopted * (inputs.target_success_rate - inputs.baseline_success_rate) * inputs.attribution_rate
    revenue = incremental_successes * inputs.revenue_per_success * inputs.gross_margin_rate
    time_savings = adopted * inputs.minutes_saved_per_adopted_task / 60 * inputs.loaded_labor_cost_per_hour * inputs.attribution_rate
    rework = adopted * inputs.error_rate_reduction * inputs.cost_per_error * inputs.attribution_rate
    avoided_loss = adopted * inputs.loss_rate_reduction * inputs.loss_per_event * inputs.attribution_rate
    gross = revenue + time_savings + rework + avoided_loss
    variable_cost = adopted * inputs.variable_run_cost_per_adopted_task
    run_cost = variable_cost + inputs.annual_fixed_cost
    annual_net = gross - run_cost
    first_year_net = annual_net - inputs.implementation_cost
    gross_per_adopted = gross / adopted if adopted else 0
    contribution = gross_per_adopted - inputs.variable_run_cost_per_adopted_task if adopted else None
    value_per_success = gross / incremental_successes if incremental_successes else None
    maximum_run_cost = max((gross - inputs.annual_fixed_cost) / adopted, 0) if adopted else None
    first_year_fixed = inputs.annual_fixed_cost + inputs.implementation_cost
    break_even_volume = (
        first_year_fixed / (inputs.adoption_rate * contribution)
        if contribution is not None and contribution > 0 and inputs.adoption_rate > 0 else None
    )
    break_even_adoption = (
        first_year_fixed / (inputs.eligible_volume * contribution)
        if contribution is not None and contribution > 0 else None
    )
    other_benefits = time_savings + rework + avoided_loss
    revenue_per_rate_point = adopted * inputs.attribution_rate * inputs.revenue_per_success * inputs.gross_margin_rate
    required_revenue = max(first_year_fixed + variable_cost - other_benefits, 0)
    break_even_quality = (
        inputs.baseline_success_rate + required_revenue / revenue_per_rate_point
        if revenue_per_rate_point > 0 else None
    )
    if break_even_quality is not None and break_even_quality > 1:
        break_even_quality = None
    payback = (
        inputs.implementation_cost / (annual_net / 12) if annual_net > 0 and inputs.implementation_cost > 0
        else 0.0 if inputs.implementation_cost == 0 and annual_net >= 0 else None
    )
    return ScenarioResults(
        adopted_tasks=rounded(adopted),
        incremental_successful_outcomes=rounded(incremental_successes),
        revenue_gross_profit=rounded(revenue),
        time_savings_value=rounded(time_savings),
        rework_avoidance_value=rounded(rework),
        loss_avoidance_value=rounded(avoided_loss),
        annual_gross_value=rounded(gross),
        annual_run_cost=rounded(run_cost),
        annual_net_value=rounded(annual_net),
        first_year_net_value=rounded(first_year_net),
        contribution_per_adopted_task=rounded(contribution),
        value_per_successful_outcome=rounded(value_per_success),
        maximum_viable_run_cost_per_adopted_task=rounded(maximum_run_cost),
        break_even_eligible_volume=rounded(break_even_volume),
        break_even_adoption_rate=rounded(break_even_adoption),
        break_even_target_success_rate=rounded(break_even_quality),
        payback_period_months=rounded(payback),
    )


def validate_economic_units(model: dict[str, Any], scenarios: dict[str, ScenarioInputs]) -> list[str]:
    units = model.get("economic_units")
    if not isinstance(units, dict) or set(units) != set(BENEFIT_FIELDS):
        return ["economic_units must define revenue, time_savings, rework_avoidance, and loss_avoidance"]
    active = [
        benefit for benefit, field in BENEFIT_FIELDS.items()
        if any(getattr(scenario, field) > 0 for scenario in scenarios.values())
    ]
    issues: list[str] = []
    for benefit in active:
        if not isinstance(units.get(benefit), str) or not units[benefit].strip():
            issues.append(f"economic unit for {benefit} is required")
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            if units.get(left) == units.get(right):
                issues.append(f"{left} and {right} claim the same economic unit")
    return issues


def calculate_model(model: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if model.get("version") != 1:
        issues.append("model version must be 1")
    if not isinstance(model.get("currency"), str) or not model["currency"].strip():
        issues.append("currency is required")
    scenario_payloads = model.get("scenarios")
    if not isinstance(scenario_payloads, dict) or set(scenario_payloads) != set(SCENARIO_NAMES):
        raise BusinessModelError(issues + ["scenarios must define conservative, base, and upside"])
    parsed: dict[str, ScenarioInputs] = {}
    for name in SCENARIO_NAMES:
        scenario, scenario_issues = parse_scenario(name, scenario_payloads[name])
        issues.extend(scenario_issues)
        if scenario is not None:
            parsed[name] = scenario
    if len(parsed) == len(SCENARIO_NAMES):
        issues.extend(validate_economic_units(model, parsed))
    if issues:
        raise BusinessModelError(issues)
    results = {name: calculate_scenario(parsed[name]) for name in SCENARIO_NAMES}
    gross_values = [result.annual_gross_value for result in results.values()]
    net_values = [result.first_year_net_value for result in results.values()]
    if gross_values != sorted(gross_values) or net_values != sorted(net_values):
        raise BusinessModelError(["scenario boundaries must order conservative <= base <= upside value"])
    projection = {
        "version": 1, "status": "complete", "currency": model["currency"],
        "economic_units": model["economic_units"], "scenarios": {},
    }
    for name in SCENARIO_NAMES:
        source = {field: scenario_payloads[name][field] for field in INPUT_FIELDS}
        source["evidence"] = scenario_payloads[name]["evidence"]
        source["results"] = asdict(results[name])
        projection["scenarios"][name] = source
    return projection


def money(value: float | None, currency: str) -> str:
    if value is None:
        return "Unavailable"
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{value:,.2f}"


def percentage(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value * 100:.2f}%"


def render_markdown(projection: dict[str, Any]) -> str:
    currency = projection["currency"]
    lines = [
        "# Business Value Model", "", "Status: complete", "", "## Scenario Summary", "",
        "| Scenario | Annual gross value | Annual net value | First-year net value | Payback months |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in SCENARIO_NAMES:
        result = projection["scenarios"][name]["results"]
        payback = result["payback_period_months"]
        lines.append(
            f"| {name.title()} | {money(result['annual_gross_value'], currency)} | "
            f"{money(result['annual_net_value'], currency)} | {money(result['first_year_net_value'], currency)} | "
            f"{'Unavailable' if payback is None else f'{payback:.2f}'} |"
        )
    for name in SCENARIO_NAMES:
        scenario = projection["scenarios"][name]
        result = scenario["results"]
        lines.extend([
            "", f"## {name.title()} Scenario", "",
            f"- Adopted tasks: {result['adopted_tasks']:,.2f}",
            f"- Incremental successful outcomes: {result['incremental_successful_outcomes']:,.2f}",
            f"- Contribution per adopted task: {money(result['contribution_per_adopted_task'], currency)}",
            f"- Value per successful outcome: {money(result['value_per_successful_outcome'], currency)}",
            f"- Maximum viable run cost per adopted task: {money(result['maximum_viable_run_cost_per_adopted_task'], currency)}",
            f"- Break-even eligible volume: {result['break_even_eligible_volume'] if result['break_even_eligible_volume'] is not None else 'Unavailable'}",
            f"- Break-even adoption: {percentage(result['break_even_adoption_rate'])}",
            f"- Break-even target success: {percentage(result['break_even_target_success_rate'])}",
            "", "### Assumptions and Evidence", "",
        ])
        for field in INPUT_FIELDS:
            evidence = scenario["evidence"][field]
            lines.append(f"- `{field}`: {evidence['assumption']} Source: {evidence['source']}. Owner: {evidence['owner']}.")
    lines.extend(["", "## Double-Counting Controls", ""])
    for benefit in BENEFIT_FIELDS:
        unit = projection["economic_units"][benefit]
        lines.append(f"- `{benefit}` counts only `{unit}`.")
    return "\n".join(lines) + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def create_projections(model: dict[str, Any], root: Path) -> dict[str, Path]:
    projection = calculate_model(model)
    yaml_path = root / YAML_PATH
    markdown_path = root / MARKDOWN_PATH
    atomic_write(yaml_path, json.dumps(projection, indent=2, sort_keys=True) + "\n")
    atomic_write(markdown_path, render_markdown(projection))
    return {"yaml": yaml_path, "markdown": markdown_path}


def source_from_projection(projection: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": projection.get("version"), "currency": projection.get("currency"),
        "economic_units": projection.get("economic_units"),
        "scenarios": {
            name: {
                **{field: projection["scenarios"][name].get(field) for field in INPUT_FIELDS},
                "evidence": projection["scenarios"][name].get("evidence"),
            }
            for name in SCENARIO_NAMES
        },
    }


def validate_projection(yaml_path: Path, markdown_path: Path) -> list[str]:
    try:
        projection = json.loads(yaml_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ["business value model is missing or invalid"]
    if not isinstance(projection, dict) or projection.get("status") == "pending":
        return ["business value model is pending"]
    try:
        recalculated = calculate_model(source_from_projection(projection))
    except (BusinessModelError, KeyError, TypeError) as error:
        return [f"business value model is invalid: {error}"]
    issues: list[str] = []
    if projection != recalculated:
        issues.append("business value model calculations are stale")
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        issues.append("business value Markdown is missing")
    else:
        if markdown != render_markdown(recalculated):
            issues.append("business value Markdown projection is stale")
    return issues
