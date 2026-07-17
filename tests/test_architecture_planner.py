from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.architecture_planner import (
    ArchitecturePlanningError,
    create_architecture_artifacts,
    extract_mermaid,
    validate_architecture_artifacts,
    validate_mermaid,
)


def write_inputs(root: Path) -> None:
    definition = root / "agent-lifecycle/agent-definition"
    evals = root / "agent-lifecycle/evals"
    references = root / "docs/references"
    definition.mkdir(parents=True)
    evals.mkdir(parents=True)
    references.mkdir(parents=True)
    (definition / "project-brief.md").write_text(
        """# Agent Project Brief

Status: complete

## Purpose

Resolve support requests with evidence-linked answers.

## Agent Scope

Only the target agent harness and context are editable.

## Success Outcomes

- `supported-resolution`: Resolve requests accurately.
""",
        encoding="utf-8",
    )
    (definition / "success-metrics.yaml").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "complete",
                "outcomes": [{"id": "supported-resolution"}],
                "metrics": [{"id": "resolution-rate", "outcome_ids": ["supported-resolution"]}],
            }
        ),
        encoding="utf-8",
    )
    (definition / "business-value-model.yaml").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "complete",
                "currency": "USD",
                "scenarios": {"base": {"results": {"annual_net_value": 120000}}},
            }
        ),
        encoding="utf-8",
    )
    (evals / "suite.yaml").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "complete",
                "metrics": [{"id": "hard-pass-rate"}],
                "cases": [
                    {"id": "core-resolution", "split": "held_in", "tags": ["capability"]},
                    {"id": "cross-domain-limit", "split": "held_in", "tags": ["edge"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    (references / "agent-building-best-practices.md").write_text(
        """# Agent-building Best Practices

## Architecture-selection contract

Choose the simplest architecture supported by evidence.

### Model call
Use one bounded inference.

### Workflow
Use predefined steps and deterministic routing.

### Single agent
Use dynamic tool selection in one coherent domain.

### Multi-agent
Require measured single-agent limits across separable domains.

## Sources

- [S1] Canonical architecture PDF.
- [S6] LangChain agents documentation.
- [S9] LangGraph workflows and agents documentation.
""",
        encoding="utf-8",
    )


def request_for(shape: str) -> dict:
    common = {
        "version": 1,
        "requested_shape": shape,
        "model_steps": ["resolve-request"],
        "adaptive_execution": False,
        "tools": [],
        "specialist_domains": [],
        "parallel_directions": [],
        "single_agent_limit_eval_ids": [],
        "acceptance_eval_ids": ["core-resolution"],
        "external_dependencies": ["Customer database", "Support user interface"],
    }
    if shape == "workflow":
        common["model_steps"] = ["classify-request", "draft-answer", "verify-answer"]
    elif shape == "agent":
        common.update(adaptive_execution=True, tools=["retrieve-policy", "lookup-account"])
    elif shape == "multi_agent":
        common.update(
            adaptive_execution=True,
            tools=["retrieve-policy", "lookup-account"],
            specialist_domains=["policy", "account"],
            parallel_directions=["policy evidence", "account evidence"],
            single_agent_limit_eval_ids=["cross-domain-limit"],
        )
    return common


@pytest.mark.parametrize("shape", ["model_call", "workflow", "agent", "multi_agent"])
def test_four_architecture_choices_create_evidence_linked_artifacts(tmp_path: Path, shape: str) -> None:
    write_inputs(tmp_path)

    result = create_architecture_artifacts(tmp_path, request_for(shape))

    architecture = result["architecture"].read_text(encoding="utf-8")
    decisions = result["decisions"].read_text(encoding="utf-8")
    assert f"Architecture: `{shape}`" in architecture
    assert "agent-lifecycle/agent-definition/project-brief.md#purpose" in decisions
    assert "agent-lifecycle/agent-definition/success-metrics.yaml#resolution-rate" in decisions
    assert "agent-lifecycle/evals/suite.yaml#core-resolution" in decisions
    assert "docs/references/agent-building-best-practices.md#architecture-selection-contract" in decisions
    assert "[S1]" in decisions and "[S6]" in decisions and "[S9]" in decisions
    assert validate_architecture_artifacts(tmp_path) == []


def test_mermaid_contains_only_target_runtime_agent_components(tmp_path: Path) -> None:
    write_inputs(tmp_path)

    paths = create_architecture_artifacts(tmp_path, request_for("agent"))
    architecture = paths["architecture"].read_text(encoding="utf-8")
    diagram = extract_mermaid(architecture)

    assert "Target agent" in diagram
    assert "Customer database" not in diagram
    assert "Support user interface" not in diagram
    for forbidden in ("eval", "grader", "testagent", "simulated user", "build loop", "lifecycle"):
        assert forbidden not in diagram.lower()
    assert "Customer database" in architecture
    assert "not an editable agent component" in architecture


def test_multi_agent_requires_eval_evidence_of_a_single_agent_limit(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    request = request_for("multi_agent")
    request["single_agent_limit_eval_ids"] = []

    with pytest.raises(ArchitecturePlanningError, match="single-agent limit eval evidence"):
        create_architecture_artifacts(tmp_path, request)


def test_unknown_eval_evidence_is_rejected(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    request = request_for("multi_agent")
    request["single_agent_limit_eval_ids"] = ["missing-eval"]

    with pytest.raises(ArchitecturePlanningError, match="unknown eval case"):
        create_architecture_artifacts(tmp_path, request)


def test_unsupported_architecture_complexity_is_rejected(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    request = request_for("multi_agent")
    request["specialist_domains"] = [f"domain-{index}" for index in range(7)]

    with pytest.raises(ArchitecturePlanningError, match="at most 5 specialist domains"):
        create_architecture_artifacts(tmp_path, request)


def test_artifact_content_cannot_inject_mermaid_or_markdown(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    request = request_for("model_call")
    request["external_dependencies"] = ["Database\n```mermaid\nflowchart TD"]

    with pytest.raises(ArchitecturePlanningError, match="unsafe diagram label"):
        create_architecture_artifacts(tmp_path, request)


@pytest.mark.parametrize(
    "diagram,diagnostic",
    [
        ("flowchart TD\n  A[Target agent] --> M[Eval grader]", "non-runtime machinery"),
        ("flowchart TD\n  A[Target agent] --> M[Model]\n  M --> Z", "undefined node"),
        ("flowchart TD\n  A[Target agent]", "at least one edge"),
    ],
)
def test_mermaid_validation_rejects_invalid_or_out_of_scope_graphs(diagram: str, diagnostic: str) -> None:
    assert diagnostic in "; ".join(validate_mermaid(diagram))


def test_cli_creates_and_validates_architecture(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request_for("workflow")), encoding="utf-8")

    create = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/agent-architecture-planner"),
            "--root",
            str(tmp_path),
            "plan",
            "--input",
            str(request_path),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    validate = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/agent-architecture-planner"),
            "--root",
            str(tmp_path),
            "validate",
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert create.returncode == validate.returncode == 0
    assert json.loads(create.stdout)["architecture"] == "workflow"
    assert json.loads(validate.stdout) == {"errors": [], "status": "valid"}


def test_skill_uses_required_inputs_and_maintains_one_visual_source_of_truth() -> None:
    skill = (REPOSITORY_ROOT / ".claude/skills/agent-architecture-planner/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "agent-lifecycle/agent-definition/project-brief.md" in skill
    assert "agent-lifecycle/agent-definition/business-value-model.yaml" in skill
    assert "agent-lifecycle/evals/suite.yaml" in skill
    assert "docs/references/agent-building-best-practices.md" in skill
    assert "scripts/agent-architecture-planner" in skill
    assert "current LangChain and LangGraph documentation" in skill
    assert "one Mermaid" in skill


def test_repository_templates_are_pending_without_claiming_a_decision() -> None:
    architecture = REPOSITORY_ROOT / "agent-lifecycle/architecture/agent-architecture.md"
    decisions = REPOSITORY_ROOT / "agent-lifecycle/architecture/decisions.md"

    assert "Status: pending" in architecture.read_text(encoding="utf-8")
    assert "Status: pending" in decisions.read_text(encoding="utf-8")
    assert validate_mermaid(extract_mermaid(architecture.read_text(encoding="utf-8"))) == []
