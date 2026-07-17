from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


ARCHITECTURE_PATH = Path("agent-lifecycle/architecture/agent-architecture.md")
DECISIONS_PATH = Path("agent-lifecycle/architecture/decisions.md")
BRIEF_PATH = Path("agent-lifecycle/agent-definition/project-brief.md")
METRICS_PATH = Path("agent-lifecycle/agent-definition/success-metrics.yaml")
VALUE_PATH = Path("agent-lifecycle/agent-definition/business-value-model.yaml")
SUITE_PATH = Path("agent-lifecycle/evals/suite.yaml")
REFERENCE_PATH = Path("docs/references/agent-building-best-practices.md")
SHAPES = {"model_call", "workflow", "agent", "multi_agent"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.,:/()&+-]*$")
NODE = re.compile(r'\b([A-Z][A-Z0-9_]*)\s*\["([^"\n]+)"\]')
EDGE = re.compile(r"\b([A-Z][A-Z0-9_]*)\s*--+>\s*([A-Z][A-Z0-9_]*)\b")
FORBIDDEN_DIAGRAM_TERMS = (
    "eval",
    "grader",
    "testagent",
    "simulated user",
    "build loop",
    "engineering loop",
    "lifecycle",
    "architecture planner",
)


class ArchitecturePlanningError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArchitecturePlanningError([f"{label} is missing or invalid: {error}"]) from error
    if not isinstance(value, dict):
        raise ArchitecturePlanningError([f"{label} must be an object"])
    return value


def read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ArchitecturePlanningError([f"{label} is missing or unreadable: {error}"]) from error


def string_list(value: Any, field: str, allow_empty: bool = True) -> tuple[list[str], list[str]]:
    if not isinstance(value, list) or (not allow_empty and not value):
        return [], [f"{field} must be a{' non-empty' if not allow_empty else ''} string list"]
    if not all(isinstance(item, str) and item.strip() for item in value):
        return [], [f"{field} must contain non-empty strings"]
    return [item.strip() for item in value], []


def safe_labels(values: list[str], field: str) -> list[str]:
    issues: list[str] = []
    for value in values:
        if not SAFE_LABEL.fullmatch(value):
            issues.append(f"{field} contains an unsafe diagram label: {value!r}")
    return issues


def load_evidence(root: Path) -> dict[str, Any]:
    brief = read_text(root / BRIEF_PATH, "project brief")
    metrics = read_json(root / METRICS_PATH, "success metrics")
    value = read_json(root / VALUE_PATH, "business value model")
    suite = read_json(root / SUITE_PATH, "eval suite")
    reference = read_text(root / REFERENCE_PATH, "agent-building best-practices reference")
    issues: list[str] = []
    if "Status: complete" not in brief:
        issues.append("project brief must be complete")
    for document, label in ((metrics, "success metrics"), (value, "business value model"), (suite, "eval suite")):
        if document.get("status") != "complete":
            issues.append(f"{label} must be complete")
    if not isinstance(metrics.get("metrics"), list) or not metrics["metrics"]:
        issues.append("success metrics must contain at least one metric")
    if not isinstance(suite.get("cases"), list) or not suite["cases"]:
        issues.append("eval suite must contain at least one case")
    for marker in ("## Architecture-selection contract", "[S1]", "[S6]", "[S9]"):
        if marker not in reference:
            issues.append(f"agent-building best-practices reference is missing {marker}")
    if issues:
        raise ArchitecturePlanningError(issues)
    return {"brief": brief, "metrics": metrics, "value": value, "suite": suite, "reference": reference}


def validate_request(request: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if request.get("version") != 1:
        issues.append("request.version must be 1")
    requested_shape = request.get("requested_shape")
    if requested_shape not in SHAPES:
        issues.append("requested_shape must be model_call, workflow, agent, or multi_agent")
    fields: dict[str, list[str]] = {}
    for field in (
        "model_steps",
        "tools",
        "specialist_domains",
        "parallel_directions",
        "single_agent_limit_eval_ids",
        "acceptance_eval_ids",
        "external_dependencies",
    ):
        fields[field], field_issues = string_list(
            request.get(field), field, allow_empty=field not in {"model_steps", "acceptance_eval_ids"}
        )
        issues.extend(field_issues)
    if not isinstance(request.get("adaptive_execution"), bool):
        issues.append("adaptive_execution must be true or false")
    for field in ("model_steps", "tools", "specialist_domains", "external_dependencies"):
        issues.extend(safe_labels(fields[field], field))
    if len(fields["model_steps"]) > 5:
        issues.append("architecture supports at most 5 model steps")
    if len(fields["tools"]) > 5:
        issues.append("architecture picture supports at most 5 tools")
    if len(fields["specialist_domains"]) > 5:
        issues.append("architecture supports at most 5 specialist domains")
    eval_ids = {
        case.get("id")
        for case in evidence["suite"]["cases"]
        if isinstance(case, dict) and isinstance(case.get("id"), str)
    }
    for field in ("single_agent_limit_eval_ids", "acceptance_eval_ids"):
        for identifier in fields[field]:
            if not IDENTIFIER.fullmatch(identifier):
                issues.append(f"{field} contains an invalid eval id: {identifier}")
            elif identifier not in eval_ids:
                issues.append(f"{field} links unknown eval case: {identifier}")
    if issues:
        raise ArchitecturePlanningError(issues)
    return {**request, **fields}


def recommended_shape(request: dict[str, Any]) -> str:
    multi_agent_supported = (
        len(request["specialist_domains"]) >= 2
        and len(request["parallel_directions"]) >= 2
        and bool(request["single_agent_limit_eval_ids"])
    )
    if request["requested_shape"] == "multi_agent" and not request["single_agent_limit_eval_ids"]:
        raise ArchitecturePlanningError(["multi_agent requires single-agent limit eval evidence"])
    if request["requested_shape"] == "multi_agent" and not multi_agent_supported:
        raise ArchitecturePlanningError(
            ["multi_agent requires at least two separable domains and two independent directions"]
        )
    if multi_agent_supported:
        shape = "multi_agent"
    elif request["adaptive_execution"]:
        shape = "agent"
    elif len(request["model_steps"]) > 1 or request["tools"]:
        shape = "workflow"
    else:
        shape = "model_call"
    if request["requested_shape"] != shape:
        raise ArchitecturePlanningError(
            [f"requested {request['requested_shape']} but evidence supports the simpler {shape} architecture"]
        )
    return shape


def diagram_for(shape: str, request: dict[str, Any]) -> str:
    if shape == "model_call":
        lines = [
            "flowchart TD",
            '  INPUT["User input"] --> CONTEXT["Context assembly"]',
            '  CONTEXT --> MODEL["Bounded model call"]',
            '  MODEL --> OUTPUT["Agent output"]',
        ]
    elif shape == "workflow":
        lines = ["flowchart TD", '  INPUT["User input"] --> CONTEXT["Context assembly"]']
        previous = "CONTEXT"
        for index, step in enumerate(request["model_steps"], 1):
            identifier = f"STEP_{index}"
            lines.append(f'  {previous} --> {identifier}["{step}"]')
            previous = identifier
        lines.append(f'  {previous} --> OUTPUT["Agent output"]')
    elif shape == "agent":
        lines = [
            "flowchart TD",
            '  INPUT["User input"] --> CONTEXT["Context assembly"]',
            '  CONTEXT --> AGENT["Target agent loop"]',
            '  AGENT --> MODEL["Agent model"]',
            '  MODEL --> ROUTER["Tool routing"]',
        ]
        for index, tool in enumerate(request["tools"], 1):
            identifier = f"TOOL_{index}"
            lines.append(f'  ROUTER --> {identifier}["{tool}"]')
            lines.append(f"  {identifier} --> AGENT")
        lines.append('  AGENT --> OUTPUT["Agent output"]')
    else:
        lines = [
            "flowchart TD",
            '  INPUT["User input"] --> SUPERVISOR["Target agent supervisor"]',
        ]
        for index, domain in enumerate(request["specialist_domains"], 1):
            identifier = f"SPECIALIST_{index}"
            lines.append(f'  SUPERVISOR --> {identifier}["{domain} specialist"]')
            lines.append(f'  {identifier} --> SYNTHESIS["Verification and synthesis"]')
        lines.append('  SYNTHESIS --> OUTPUT["Agent output"]')
    return "\n".join(lines)


def extract_mermaid(markdown: str) -> str:
    blocks = re.findall(r"```mermaid\s*\n(.*?)```", markdown, flags=re.DOTALL)
    if len(blocks) != 1:
        raise ArchitecturePlanningError(["architecture must contain exactly one Mermaid diagram"])
    return blocks[0].strip()


def validate_mermaid(diagram: str) -> list[str]:
    issues: list[str] = []
    if not diagram.startswith("flowchart "):
        issues.append("Mermaid diagram must be a flowchart")
    lowered = diagram.casefold()
    if any(term in lowered for term in FORBIDDEN_DIAGRAM_TERMS):
        issues.append("Mermaid diagram contains non-runtime machinery")
    nodes = {match.group(1) for match in NODE.finditer(diagram)}
    edges = list(EDGE.finditer(diagram))
    if not edges:
        issues.append("Mermaid diagram must contain at least one edge")
    for edge in edges:
        for identifier in edge.groups():
            if identifier not in nodes:
                issues.append(f"Mermaid edge references undefined node: {identifier}")
    if len(nodes) > 15:
        issues.append("Mermaid diagram exceeds the 15-node readability limit")
    return list(dict.fromkeys(issues))


def purpose_from_brief(brief: str) -> str:
    match = re.search(r"## Purpose\s+(.+?)(?:\n## |\Z)", brief, flags=re.DOTALL)
    return match.group(1).strip().replace("\n", " ") if match else "See the project brief."


def rationale_for(shape: str) -> str:
    return {
        "model_call": "One bounded inference satisfies the declared runtime behavior without tools or adaptive control.",
        "workflow": "The required model steps are known in advance, so deterministic orchestration provides adequate control.",
        "agent": "The runtime must choose and recover across tools dynamically within one coherent domain.",
        "multi_agent": "Eval evidence demonstrates a single-agent limit across separable domains with independent directions.",
    }[shape]


def render_architecture(shape: str, request: dict[str, Any], evidence: dict[str, Any]) -> str:
    dependencies = "\n".join(
        f"- {dependency} is an external dependency, not an editable agent component."
        for dependency in request["external_dependencies"]
    ) or "- None declared."
    return f"""# Target Agent Architecture

Status: complete

Architecture: `{shape}`

## Runtime Purpose

{purpose_from_brief(evidence['brief'])}

## Visual Source of Truth

This is the single maintained picture of the target runtime agent.

```mermaid
{diagram_for(shape, request)}
```

## Runtime Boundary

The diagram contains only the target agent harness and its runtime context. Evaluation, testing, lifecycle, and engineering machinery remain outside it.

## External Dependencies

{dependencies}
"""


def render_decisions(shape: str, request: dict[str, Any], evidence: dict[str, Any]) -> str:
    metric_id = evidence["metrics"]["metrics"][0]["id"]
    acceptance = "\n".join(
        f"- `agent-lifecycle/evals/suite.yaml#{identifier}`" for identifier in request["acceptance_eval_ids"]
    )
    limits = "\n".join(
        f"- `agent-lifecycle/evals/suite.yaml#{identifier}`"
        for identifier in request["single_agent_limit_eval_ids"]
    ) or "- No single-agent limit evidence is required for this shape."
    return f"""# Agent Architecture Decisions

Status: complete

## Decision

Use `{shape}`. {rationale_for(shape)}

## Requirement and Value Evidence

- `agent-lifecycle/agent-definition/project-brief.md#purpose`
- `agent-lifecycle/agent-definition/success-metrics.yaml#{metric_id}`
- `agent-lifecycle/agent-definition/business-value-model.yaml#base`

## Acceptance Eval Evidence

{acceptance}

## Single-Agent Limit Evidence

{limits}

## Architecture Sources

- `docs/references/agent-building-best-practices.md#architecture-selection-contract`
- [S1] Canonical architecture PDF: simplest justified architecture and measured escalation.
- [S6] Current LangChain agent interface and middleware guidance.
- [S9] Current LangGraph workflow and agent orchestration guidance.

## Maintenance

Maintain `agent-architecture.md` as the only architecture picture. Reconcile it after runtime implementation changes and use ordinary search and replace for renamed agent or tool labels.
"""


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def create_architecture_artifacts(root: Path, raw_request: dict[str, Any]) -> dict[str, Path | str]:
    evidence = load_evidence(root)
    request = validate_request(raw_request, evidence)
    shape = recommended_shape(request)
    architecture = render_architecture(shape, request, evidence)
    diagram_issues = validate_mermaid(extract_mermaid(architecture))
    if diagram_issues:
        raise ArchitecturePlanningError(diagram_issues)
    architecture_path = root / ARCHITECTURE_PATH
    decisions_path = root / DECISIONS_PATH
    atomic_write(architecture_path, architecture)
    atomic_write(decisions_path, render_decisions(shape, request, evidence))
    return {"architecture": architecture_path, "decisions": decisions_path, "shape": shape}


def validate_architecture_artifacts(root: Path) -> list[str]:
    issues: list[str] = []
    try:
        architecture = read_text(root / ARCHITECTURE_PATH, "agent architecture")
        decisions = read_text(root / DECISIONS_PATH, "architecture decisions")
    except ArchitecturePlanningError as error:
        return error.issues
    if "Status: complete" not in architecture:
        issues.append("agent architecture must be complete")
    if "Status: complete" not in decisions:
        issues.append("architecture decisions must be complete")
    try:
        issues.extend(validate_mermaid(extract_mermaid(architecture)))
    except ArchitecturePlanningError as error:
        issues.extend(error.issues)
    for link in (
        "agent-lifecycle/agent-definition/project-brief.md#purpose",
        "agent-lifecycle/agent-definition/success-metrics.yaml#",
        "agent-lifecycle/agent-definition/business-value-model.yaml#base",
        "agent-lifecycle/evals/suite.yaml#",
        "docs/references/agent-building-best-practices.md#architecture-selection-contract",
        "[S1]",
        "[S6]",
        "[S9]",
    ):
        if link not in decisions:
            issues.append(f"architecture decisions are missing evidence link: {link}")
    return issues
