from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.engineering_handoff import (
    EngineeringHandoffError,
    create_handoff,
    load_manifest,
    validate_receipt,
    verify_handoff,
)


def write_sources(root: Path) -> None:
    sources = {
        "agent-lifecycle/agent-definition/project-brief.md": "# Brief\n\nStatus: complete\n\n## Purpose\nResolve requests.\n",
        "agent-lifecycle/architecture/agent-architecture.md": "# Architecture\n\nStatus: complete\n",
        "agent-lifecycle/architecture/decisions.md": "# Decisions\n\nStatus: complete\n\nUse a workflow.\n",
        "docs/references/agent-building-best-practices.md": "# Best practices\n\n## Tools\nPrefer deterministic contracts. [S1]\n",
    }
    for relative, content in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    suite = root / "agent-lifecycle/evals/suite.yaml"
    suite.parent.mkdir(parents=True, exist_ok=True)
    suite.write_text(
        json.dumps(
            {
                "version": 1,
                "status": "complete",
                "cases": [
                    {"id": "core-resolution", "split": "held_in"},
                    {"id": "tool-boundary", "split": "held_in"},
                ],
            }
        ),
        encoding="utf-8",
    )


def complete_request() -> dict:
    return {
        "version": 1,
        "handoff_id": "first-build-001",
        "kind": "build",
        "approval_status": "approved",
        "editable_paths": [
            {"path": "agent/prompts/system.md", "surface": "prompts"},
            {"path": "agent/tools/retrieve_policy.py", "surface": "agent_tool_contracts"},
            {"path": "agent/workflow/graph.py", "surface": "workflow"},
        ],
        "recommendations": [
            {
                "id": "ground-policy-answer",
                "requirement_or_evidence": [
                    "agent-lifecycle/agent-definition/project-brief.md#purpose",
                    "agent-lifecycle/evals/suite.yaml#core-resolution",
                ],
                "likely_cause_or_design_need": "The target needs an evidence-grounded response path.",
                "proposed_change": "Add a bounded policy retrieval tool and require grounded synthesis.",
                "source_rationale": {
                    "summary": "Deterministic tool contracts reduce model-owned uncertainty.",
                    "references": [
                        "docs/references/agent-building-best-practices.md#tools",
                        "agent-lifecycle/architecture/decisions.md#decision",
                    ],
                },
                "expected_effect": {
                    "user": "Users receive supported answers more consistently.",
                    "business": "Support rework and handling time should fall.",
                },
                "acceptance_eval_ids": ["core-resolution", "tool-boundary"],
            }
        ],
        "acceptance_gates": [
            {
                "id": "focused-tests",
                "kind": "focused_tests",
                "command": ".venv/bin/python -m pytest -q tests/test_agent.py",
                "success_criteria": "Focused agent tests pass.",
            },
            {
                "id": "full-suite",
                "kind": "full_suite",
                "command": ".venv/bin/python -m pytest -q",
                "success_criteria": "The full deterministic suite passes.",
            },
            {
                "id": "acceptance-evals",
                "kind": "acceptance_evals",
                "eval_ids": ["core-resolution", "tool-boundary"],
                "success_criteria": "All named acceptance evals meet their thresholds.",
            },
            {
                "id": "self-review",
                "kind": "review",
                "success_criteria": "Architecture, simplicity, and security review has no blocking findings.",
            },
        ],
    }


def valid_receipt(root: Path, manifest: dict, architecture_changed: bool = False) -> dict:
    manifest_path = root / "agent-lifecycle/handoffs/first-build-001/manifest.json"
    return {
        "version": 1,
        "handoff_id": manifest["handoff_id"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "result_status": "completed",
        "changed_files": ["agent/prompts/system.md", "agent/workflow/graph.py"],
        "test_evidence": ["focused-tests: passed", "full-suite: passed", "acceptance-evals: passed"],
        "review_outcome": "passed",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "architecture_changed": architecture_changed,
    }


def test_create_immutable_evidence_linked_handoff(tmp_path: Path) -> None:
    write_sources(tmp_path)

    paths = create_handoff(tmp_path, complete_request())
    manifest = load_manifest(paths["manifest"])
    specification = paths["implementation_spec"].read_text(encoding="utf-8")
    gates = json.loads(paths["acceptance_gates"].read_text(encoding="utf-8"))

    assert set(paths) == {"implementation_spec", "acceptance_gates", "manifest", "receipt_template", "route"}
    assert manifest["handoff_id"] == "first-build-001"
    assert manifest["editable_paths"] == complete_request()["editable_paths"]
    assert set(manifest["artifact_sha256"]) == {
        "implementation-spec.md",
        "acceptance-gates.json",
        "receipt-template.json",
    }
    assert set(manifest["source_sha256"]) == {
        "agent-lifecycle/agent-definition/project-brief.md",
        "agent-lifecycle/architecture/agent-architecture.md",
        "agent-lifecycle/architecture/decisions.md",
        "docs/references/agent-building-best-practices.md",
        "agent-lifecycle/evals/suite.yaml",
    }
    for heading in (
        "Requirement or observed evidence",
        "Likely cause or design need",
        "Proposed change",
        "Source-linked rationale",
        "Expected user and business effect",
        "Acceptance evals",
    ):
        assert heading in specification
    assert {gate["kind"] for gate in gates["gates"]} == {
        "focused_tests",
        "full_suite",
        "acceptance_evals",
        "review",
    }
    assert verify_handoff(paths["manifest"]) == []
    for name in ("implementation_spec", "acceptance_gates", "manifest", "receipt_template"):
        assert not os.stat(paths[name]).st_mode & 0o222


def test_repository_contains_generic_receipt_template() -> None:
    template = json.loads(
        (REPOSITORY_ROOT / "agent-lifecycle/receipts/receipt-template.json").read_text(
            encoding="utf-8"
        )
    )

    assert template == {
        "version": 1,
        "handoff_id": "<handoff-id>",
        "manifest_sha256": "<manifest-sha256>",
        "result_status": "pending",
        "changed_files": [],
        "test_evidence": [],
        "review_outcome": "pending",
        "commit_sha": None,
        "architecture_changed": None,
    }


def test_architecture_planner_routes_approved_recommendations_into_handoff() -> None:
    skill = (
        REPOSITORY_ROOT / ".claude/skills/agent-architecture-planner/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "scripts/engineering-handoff create" in skill
    assert "exact editable" in skill
    assert "acceptance" in skill


def test_existing_handoff_identifier_cannot_be_replaced(tmp_path: Path) -> None:
    write_sources(tmp_path)
    paths = create_handoff(tmp_path, complete_request())
    original = {name: path.read_bytes() for name, path in paths.items() if name != "route"}
    changed = complete_request()
    changed["recommendations"][0]["proposed_change"] = "Silently replace the original recommendation."

    with pytest.raises(EngineeringHandoffError, match="already exists"):
        create_handoff(tmp_path, changed)

    assert {name: path.read_bytes() for name, path in paths.items() if name != "route"} == original


def test_manifest_detects_stale_or_tampered_artifacts(tmp_path: Path) -> None:
    write_sources(tmp_path)
    paths = create_handoff(tmp_path, complete_request())
    paths["implementation_spec"].chmod(0o644)
    paths["implementation_spec"].write_text("changed\n", encoding="utf-8")

    assert "digest mismatch: implementation-spec.md" in verify_handoff(paths["manifest"])


def test_manifest_detects_stale_source_evidence(tmp_path: Path) -> None:
    write_sources(tmp_path)
    paths = create_handoff(tmp_path, complete_request())
    source = tmp_path / "agent-lifecycle/architecture/agent-architecture.md"
    source.write_text("changed architecture\n", encoding="utf-8")

    assert "source evidence changed: agent-lifecycle/architecture/agent-architecture.md" in verify_handoff(
        paths["manifest"]
    )


@pytest.mark.parametrize("missing_kind", ["focused_tests", "full_suite", "acceptance_evals", "review"])
def test_every_acceptance_gate_kind_is_required(tmp_path: Path, missing_kind: str) -> None:
    write_sources(tmp_path)
    request = complete_request()
    request["acceptance_gates"] = [
        gate for gate in request["acceptance_gates"] if gate["kind"] != missing_kind
    ]

    with pytest.raises(EngineeringHandoffError, match=f"acceptance gate kind is required: {missing_kind}"):
        create_handoff(tmp_path, request)


def test_all_recommendation_evals_must_be_covered_by_acceptance_gate(tmp_path: Path) -> None:
    write_sources(tmp_path)
    request = complete_request()
    request["acceptance_gates"][2]["eval_ids"] = ["core-resolution"]

    with pytest.raises(EngineeringHandoffError, match="acceptance eval is not gated: tool-boundary"):
        create_handoff(tmp_path, request)


@pytest.mark.parametrize(
    "editable_path,diagnostic",
    [
        ({"path": "/tmp/system.md", "surface": "prompts"}, "repository-relative"),
        ({"path": "agent/prompts/*.md", "surface": "prompts"}, "exact file path"),
        ({"path": "agent/src/db/repository.py", "surface": "context"}, "does not belong"),
        ({"path": "app/ui/view.py", "surface": "workflow"}, "does not belong"),
        ({"path": "agent/prompts/system.md", "surface": "database"}, "unsupported agent surface"),
    ],
)
def test_allowlist_rejects_non_exact_or_non_agent_paths(
    tmp_path: Path, editable_path: dict, diagnostic: str
) -> None:
    write_sources(tmp_path)
    request = complete_request()
    request["editable_paths"] = [editable_path]

    with pytest.raises(EngineeringHandoffError, match=diagnostic):
        create_handoff(tmp_path, request)


@pytest.mark.parametrize(
    "field",
    [
        "requirement_or_evidence",
        "likely_cause_or_design_need",
        "proposed_change",
        "source_rationale",
        "expected_effect",
        "acceptance_eval_ids",
    ],
)
def test_each_recommendation_requires_complete_traceability(tmp_path: Path, field: str) -> None:
    write_sources(tmp_path)
    request = complete_request()
    request["recommendations"][0].pop(field)

    with pytest.raises(EngineeringHandoffError, match=field.replace("_", " ")):
        create_handoff(tmp_path, request)


def test_missing_or_unknown_evidence_reference_is_rejected(tmp_path: Path) -> None:
    write_sources(tmp_path)
    request = complete_request()
    request["recommendations"][0]["source_rationale"]["references"] = ["missing.md#source"]

    with pytest.raises(EngineeringHandoffError, match="referenced evidence does not exist"):
        create_handoff(tmp_path, request)


@pytest.mark.parametrize("architecture_changed", [False, True])
def test_completed_receipt_validates_and_preserves_architecture_change_status(
    tmp_path: Path, architecture_changed: bool
) -> None:
    write_sources(tmp_path)
    paths = create_handoff(tmp_path, complete_request())
    manifest = load_manifest(paths["manifest"])
    receipt = valid_receipt(tmp_path, manifest, architecture_changed)

    assert validate_receipt(receipt, paths["manifest"]) == []
    assert receipt["architecture_changed"] is architecture_changed


@pytest.mark.parametrize(
    "mutation,diagnostic",
    [
        (lambda receipt: receipt.update(manifest_sha256="0" * 64), "stale manifest"),
        (lambda receipt: receipt.update(changed_files=["app/database.py"]), "outside the exact allowlist"),
        (lambda receipt: receipt.update(architecture_changed=None), "architecture changed must be true or false"),
        (lambda receipt: receipt.update(result_status="failed"), "result status must be completed"),
    ],
)
def test_invalid_receipt_fails_with_actionable_error(tmp_path: Path, mutation, diagnostic: str) -> None:
    write_sources(tmp_path)
    paths = create_handoff(tmp_path, complete_request())
    receipt = valid_receipt(tmp_path, load_manifest(paths["manifest"]))
    mutation(receipt)

    assert diagnostic in "; ".join(validate_receipt(receipt, paths["manifest"]))


def test_cli_smoke_creates_handoff_and_validates_receipt(tmp_path: Path) -> None:
    write_sources(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(complete_request()), encoding="utf-8")
    create = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/engineering-handoff"),
            "--root",
            str(tmp_path),
            "create",
            "--input",
            str(request_path),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    manifest_path = tmp_path / "agent-lifecycle/handoffs/first-build-001/manifest.json"
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(valid_receipt(tmp_path, load_manifest(manifest_path))), encoding="utf-8"
    )
    validate = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/engineering-handoff"),
            "validate-receipt",
            "--manifest",
            str(manifest_path),
            "--receipt",
            str(receipt_path),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert create.returncode == validate.returncode == 0
    assert json.loads(create.stdout)["handoff_id"] == "first-build-001"
    assert json.loads(validate.stdout) == {"errors": [], "status": "valid"}
