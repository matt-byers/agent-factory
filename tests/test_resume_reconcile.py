from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.architecture_planner import (
    create_architecture_artifacts,
    extract_mermaid,
    validate_mermaid,
)
from agent_creation.engineering_handoff import create_handoff, digest
from agent_creation.lifecycle import LifecycleError, advance, load_state, resume
from agent_creation.resume_reconcile import (
    ReconciliationError,
    reconcile_architecture,
    validate_reconciliation,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def architecture_request(shape: str) -> dict:
    request = {
        "version": 1,
        "requested_shape": shape,
        "model_steps": ["classify-request", "draft-answer"],
        "adaptive_execution": False,
        "tools": [],
        "specialist_domains": [],
        "parallel_directions": [],
        "single_agent_limit_eval_ids": [],
        "acceptance_eval_ids": ["core-resolution"],
        "external_dependencies": ["Customer database"],
    }
    if shape == "agent":
        request.update(
            model_steps=["resolve-request"],
            adaptive_execution=True,
            tools=["retrieve-policy"],
        )
    return request


def write_architecture_inputs(root: Path) -> None:
    files = {
        "agent-lifecycle/agent-definition/project-brief.md": """# Agent Project Brief

Status: complete

## Purpose

Resolve support requests with evidence-linked answers.
""",
        "docs/references/agent-building-best-practices.md": """# Agent-building Best Practices

## Architecture-selection contract

Choose the simplest architecture supported by evidence.

- [S1] Canonical architecture PDF.
- [S6] LangChain agents documentation.
- [S9] LangGraph workflows documentation.
""",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    write_json(
        root / "agent-lifecycle/agent-definition/success-metrics.yaml",
        {
            "version": 1,
            "status": "complete",
            "metrics": [{"id": "resolution-rate"}],
        },
    )
    write_json(
        root / "agent-lifecycle/agent-definition/business-value-model.yaml",
        {
            "version": 1,
            "status": "complete",
            "scenarios": {"base": {"results": {"annual_net_value": 100}}},
        },
    )
    write_json(
        root / "agent-lifecycle/evals/suite.yaml",
        {
            "version": 1,
            "status": "complete",
            "cases": [{"id": "core-resolution", "split": "held_in"}],
        },
    )


def handoff_request() -> dict:
    return {
        "version": 1,
        "handoff_id": "reconcile-build-001",
        "kind": "build",
        "approval_status": "approved",
        "editable_paths": [
            {"path": "agent/workflow/graph.py", "surface": "workflow"},
            {"path": "agent/prompts/system.md", "surface": "prompts"},
        ],
        "recommendations": [
            {
                "id": "add-policy-tool",
                "requirement_or_evidence": [
                    "agent-lifecycle/agent-definition/project-brief.md#purpose",
                    "agent-lifecycle/evals/suite.yaml#core-resolution",
                ],
                "likely_cause_or_design_need": "The runtime needs bounded policy retrieval.",
                "proposed_change": "Add tool routing to the target agent workflow.",
                "source_rationale": {
                    "summary": "Deterministic tools improve reliability.",
                    "references": [
                        "docs/references/agent-building-best-practices.md#architecture-selection-contract",
                        "agent-lifecycle/architecture/decisions.md#decision",
                    ],
                },
                "expected_effect": {"user": "Grounded answers.", "business": "Less rework."},
                "acceptance_eval_ids": ["core-resolution"],
            }
        ],
        "acceptance_gates": [
            {
                "id": "focused-tests",
                "kind": "focused_tests",
                "command": "pytest -q agent/tests/test_graph.py",
                "success_criteria": "Focused tests pass.",
            },
            {
                "id": "full-suite",
                "kind": "full_suite",
                "command": "pytest -q",
                "success_criteria": "Full suite passes.",
            },
            {
                "id": "acceptance-evals",
                "kind": "acceptance_evals",
                "eval_ids": ["core-resolution"],
                "success_criteria": "Acceptance eval passes.",
            },
            {
                "id": "review",
                "kind": "review",
                "success_criteria": "Review passes.",
            },
        ],
    }


def setup_waiting_lifecycle(root: Path) -> Path:
    write_architecture_inputs(root)
    create_architecture_artifacts(root, architecture_request("workflow"))
    paths = create_handoff(root, handoff_request())
    architecture_fingerprints = {
        "agent-lifecycle/architecture/agent-architecture.md": digest(
            root / "agent-lifecycle/architecture/agent-architecture.md"
        ),
        "agent-lifecycle/architecture/decisions.md": digest(
            root / "agent-lifecycle/architecture/decisions.md"
        ),
        "agent-lifecycle/handoffs/build-handoff.yaml": digest(paths["route"]),
    }
    write_json(
        root / "agent-lifecycle/state.yaml",
        {
            "version": 1,
            "lifecycle": "first-build",
            "stage": "awaiting_engineering",
            "status": "active",
            "engineering_loop": "included",
            "artifact_fingerprints": {"architecture": architecture_fingerprints},
            "receipt": None,
            "engineering_attempt": None,
        },
    )
    return paths["manifest"]


def receipt_for(root: Path, manifest: Path, architecture_changed: bool) -> Path:
    graph = root / "agent/workflow/graph.py"
    prompt = root / "agent/prompts/system.md"
    graph.parent.mkdir(parents=True, exist_ok=True)
    prompt.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text("TARGET_TOOLS = ('retrieve-policy',)\n", encoding="utf-8")
    prompt.write_text("Use grounded policy evidence.\n", encoding="utf-8")
    receipt = root / "agent-lifecycle/receipts/completed.json"
    write_json(
        receipt,
        {
            "version": 1,
            "handoff_id": "reconcile-build-001",
            "manifest_sha256": digest(manifest),
            "result_status": "completed",
            "changed_files": ["agent/workflow/graph.py", "agent/prompts/system.md"],
            "test_evidence": ["focused and full suites passed"],
            "review_outcome": "passed",
            "commit_sha": "0123456789abcdef",
            "architecture_changed": architecture_changed,
        },
    )
    return receipt


def test_unchanged_architecture_resumes_directly_without_rewriting_picture(tmp_path: Path) -> None:
    manifest = setup_waiting_lifecycle(tmp_path)
    receipt = receipt_for(tmp_path, manifest, architecture_changed=False)
    architecture = tmp_path / "agent-lifecycle/architecture/agent-architecture.md"
    decisions = tmp_path / "agent-lifecycle/architecture/decisions.md"
    before = (architecture.read_bytes(), decisions.read_bytes())

    result = resume(tmp_path, receipt)

    assert result["stage"] == "baseline"
    assert (architecture.read_bytes(), decisions.read_bytes()) == before
    assert not (tmp_path / "agent-lifecycle/architecture/reconciliation.json").exists()


def test_changed_architecture_reconciles_picture_and_decisions_before_baseline(tmp_path: Path) -> None:
    manifest = setup_waiting_lifecycle(tmp_path)
    receipt = receipt_for(tmp_path, manifest, architecture_changed=True)
    before = (tmp_path / "agent-lifecycle/architecture/agent-architecture.md").read_text()

    resumed = resume(tmp_path, receipt)
    result = reconcile_architecture(tmp_path, receipt, architecture_request("agent"))
    advanced = advance(tmp_path)
    architecture = (tmp_path / "agent-lifecycle/architecture/agent-architecture.md").read_text()

    assert resumed["stage"] == "architecture_reconciliation"
    assert resumed["next"] == "/agent-architecture-planner reconcile"
    assert result["status"] == "reconciled"
    assert architecture != before
    assert "Architecture: `agent`" in architecture
    assert "retrieve-policy" in architecture
    assert validate_mermaid(extract_mermaid(architecture)) == []
    assert validate_reconciliation(tmp_path) == []
    assert advanced["stage"] == "baseline"


def test_reconciliation_is_idempotent_for_the_same_receipt_and_implementation(tmp_path: Path) -> None:
    manifest = setup_waiting_lifecycle(tmp_path)
    receipt = receipt_for(tmp_path, manifest, architecture_changed=True)
    resume(tmp_path, receipt)

    first = reconcile_architecture(tmp_path, receipt, architecture_request("agent"))
    paths = [
        tmp_path / "agent-lifecycle/architecture/agent-architecture.md",
        tmp_path / "agent-lifecycle/architecture/decisions.md",
        tmp_path / "agent-lifecycle/architecture/reconciliation.json",
    ]
    first_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    second = reconcile_architecture(tmp_path, receipt, architecture_request("agent"))

    assert second == first
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths] == first_hashes


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        (lambda payload: payload.update(manifest_sha256="0" * 64), "stale manifest"),
        (lambda payload: payload.update(changed_files=["app/database.py"]), "exact allowlist"),
        (lambda payload: payload.update(result_status="failed", review_outcome="failed", commit_sha=None), "failed"),
        (lambda payload: payload.pop("test_evidence"), "receipt fields"),
    ],
)
def test_stale_tampered_failed_or_malformed_receipts_do_not_advance(
    tmp_path: Path, mutation, diagnostic: str
) -> None:
    manifest = setup_waiting_lifecycle(tmp_path)
    receipt = receipt_for(tmp_path, manifest, architecture_changed=False)
    payload = json.loads(receipt.read_text())
    mutation(payload)
    write_json(receipt, payload)

    with pytest.raises(LifecycleError, match=diagnostic):
        resume(tmp_path, receipt)

    assert load_state(tmp_path)["stage"] == "awaiting_engineering"


def test_receipt_tampering_after_resume_blocks_reconciliation(tmp_path: Path) -> None:
    manifest = setup_waiting_lifecycle(tmp_path)
    receipt = receipt_for(tmp_path, manifest, architecture_changed=True)
    resume(tmp_path, receipt)
    payload = json.loads(receipt.read_text())
    payload["commit_sha"] = "fedcba9876543210"
    write_json(receipt, payload)

    with pytest.raises(ReconciliationError, match="changed after lifecycle resume"):
        reconcile_architecture(tmp_path, receipt, architecture_request("agent"))


def test_repeated_receipt_does_not_apply_twice(tmp_path: Path) -> None:
    manifest = setup_waiting_lifecycle(tmp_path)
    receipt = receipt_for(tmp_path, manifest, architecture_changed=False)
    resume(tmp_path, receipt)
    architecture = (tmp_path / "agent-lifecycle/architecture/agent-architecture.md").read_bytes()

    with pytest.raises(LifecycleError, match="not waiting"):
        resume(tmp_path, receipt)

    assert (tmp_path / "agent-lifecycle/architecture/agent-architecture.md").read_bytes() == architecture


def test_tampered_reconciliation_marker_cannot_advance(tmp_path: Path) -> None:
    manifest = setup_waiting_lifecycle(tmp_path)
    receipt = receipt_for(tmp_path, manifest, architecture_changed=True)
    resume(tmp_path, receipt)
    reconcile_architecture(tmp_path, receipt, architecture_request("agent"))
    marker = tmp_path / "agent-lifecycle/architecture/reconciliation.json"
    payload = json.loads(marker.read_text())
    payload["receipt_sha256"] = "0" * 64
    write_json(marker, payload)

    with pytest.raises(LifecycleError, match="reconciliation is invalid"):
        advance(tmp_path)

    assert load_state(tmp_path)["stage"] == "architecture_reconciliation"


def test_old_marker_does_not_hide_architecture_tampering_before_new_reconciliation(
    tmp_path: Path,
) -> None:
    manifest = setup_waiting_lifecycle(tmp_path)
    receipt = receipt_for(tmp_path, manifest, architecture_changed=True)
    marker = tmp_path / "agent-lifecycle/architecture/reconciliation.json"
    write_json(
        marker,
        {
            "version": 1,
            "status": "reconciled",
            "receipt_sha256": "f" * 64,
            "after_sha256": {},
        },
    )
    resume(tmp_path, receipt)
    architecture = tmp_path / "agent-lifecycle/architecture/agent-architecture.md"
    architecture.write_text(architecture.read_text() + "tampered\n", encoding="utf-8")

    with pytest.raises(ReconciliationError, match="changed before reconciliation"):
        reconcile_architecture(tmp_path, receipt, architecture_request("agent"))
