from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.engineering_contract import (
    EngineeringContractError,
    assess_engineering_receipt,
    prepare_engineering_input,
)
from agent_creation.engineering_handoff import create_handoff, load_manifest
from agent_creation.lifecycle import LifecycleError, load_state, resume, setup, start


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_sources(root: Path) -> None:
    sources = {
        "agent-lifecycle/agent-definition/project-brief.md": "# Brief\n\nStatus: complete\n\n## Purpose\nResolve requests.\n",
        "agent-lifecycle/architecture/agent-architecture.md": "# Architecture\n\nStatus: complete\n",
        "agent-lifecycle/architecture/decisions.md": "# Decisions\n\nStatus: complete\n\n## Decision\nUse a workflow.\n",
        "docs/references/agent-building-best-practices.md": "# Best practices\n\n## Tools\nUse bounded tools.\n",
    }
    for relative, content in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
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
        "handoff_id": "contract-build-001",
        "kind": "build",
        "approval_status": "approved",
        "editable_paths": [
            {"path": "agent/prompts/system.md", "surface": "prompts"},
            {"path": "agent/workflow/graph.py", "surface": "workflow"},
        ],
        "recommendations": [
            {
                "id": "ground-response",
                "requirement_or_evidence": [
                    "agent-lifecycle/agent-definition/project-brief.md#purpose",
                    "agent-lifecycle/evals/suite.yaml#core-resolution",
                ],
                "likely_cause_or_design_need": "The response path needs grounding.",
                "proposed_change": "Update the prompt and workflow.",
                "source_rationale": {
                    "summary": "Bounded tools improve determinism.",
                    "references": [
                        "docs/references/agent-building-best-practices.md#tools",
                        "agent-lifecycle/architecture/decisions.md#decision",
                    ],
                },
                "expected_effect": {
                    "user": "More reliable answers.",
                    "business": "Less rework.",
                },
                "acceptance_eval_ids": ["core-resolution"],
            }
        ],
        "acceptance_gates": [
            {
                "id": "focused-tests",
                "kind": "focused_tests",
                "command": "pytest focused",
                "success_criteria": "Focused tests pass.",
            },
            {
                "id": "full-suite",
                "kind": "full_suite",
                "command": "pytest",
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


def setup_contract(root: Path, loop: str) -> Path:
    write_sources(root)
    paths = create_handoff(root, handoff_request())
    write_json(
        root / "agent-lifecycle/setup.yaml",
        {
            "version": 1,
            "simulator_model": "simulator",
            "judge_model": "judge",
            "evidence_mode": "local",
            "engineering_loop": loop,
        },
    )
    write_json(
        root / "agent-lifecycle/state.yaml",
        {
            "version": 1,
            "lifecycle": "first-build",
            "stage": "awaiting_engineering",
            "status": "active" if loop == "included" else "waiting",
            "engineering_loop": loop,
            "artifact_fingerprints": {},
            "receipt": None,
            "engineering_attempt": None,
        },
    )
    return paths["manifest"]


def receipt(manifest_path: Path, status: str = "completed", architecture_changed: bool = False) -> dict:
    manifest = load_manifest(manifest_path)
    completed = status == "completed"
    return {
        "version": 1,
        "handoff_id": manifest["handoff_id"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "result_status": status,
        "changed_files": ["agent/prompts/system.md"] if status != "incomplete" else [],
        "test_evidence": [f"engineering loop result: {status}"],
        "review_outcome": "passed" if completed else status,
        "commit_sha": "0123456789abcdef0123456789abcdef01234567" if completed else None,
        "architecture_changed": architecture_changed,
    }


@pytest.mark.parametrize("loop", ["included", "external"])
def test_each_loop_receives_the_same_immutable_input_contract(tmp_path: Path, loop: str) -> None:
    root = tmp_path / loop
    manifest_path = setup_contract(root, loop)

    contract = prepare_engineering_input(root, "build")

    assert contract["engineering_loop"] == loop
    assert contract["kind"] == "build"
    assert contract["handoff_id"] == "contract-build-001"
    assert contract["manifest"] == {
        "path": "agent-lifecycle/handoffs/contract-build-001/manifest.json",
        "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    assert contract["editable_paths"] == handoff_request()["editable_paths"]
    assert contract["implementation_spec"]["path"].endswith("implementation-spec.md")
    assert contract["acceptance_gates"]["path"].endswith("acceptance-gates.json")
    assert contract["receipt_template"]["path"].endswith("receipt-template.json")


def test_switching_loop_changes_only_selection_not_handoff_contract(tmp_path: Path) -> None:
    included_root = tmp_path / "included"
    external_root = tmp_path / "external"
    setup_contract(included_root, "included")
    setup_contract(external_root, "external")

    included = prepare_engineering_input(included_root, "build")
    external = prepare_engineering_input(external_root, "build")
    included.pop("engineering_loop")
    external.pop("engineering_loop")

    assert included == external


def test_cli_prepares_the_selected_loop_contract(tmp_path: Path) -> None:
    root = tmp_path / "target"
    setup_contract(root, "external")

    result = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/engineering-handoff"),
            "--root",
            str(root),
            "prepare",
            "--kind",
            "build",
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["engineering_loop"] == "external"


def test_orchestrator_passes_the_same_prepared_contract_to_either_loop() -> None:
    skill = (
        REPOSITORY_ROOT / ".claude/skills/agent-lifecycle-orchestrator/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "scripts/engineering-handoff prepare" in skill
    assert "failed or incomplete" in skill


def test_invalid_engineering_loop_selection_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "target"
    setup_contract(root, "included")
    setup = root / "agent-lifecycle/setup.yaml"
    payload = json.loads(setup.read_text(encoding="utf-8"))
    payload["engineering_loop"] = "custom-unregistered"
    write_json(setup, payload)

    with pytest.raises(EngineeringContractError, match="included or external"):
        prepare_engineering_input(root, "build")


def test_explicit_lifecycle_loop_selection_updates_setup_source_of_truth(tmp_path: Path) -> None:
    root = tmp_path / "target"
    setup(root, "simulator", "judge", "local", "included")

    start(root, "first-build", "external")

    configuration = json.loads(
        (root / "agent-lifecycle/setup.yaml").read_text(encoding="utf-8")
    )
    assert configuration["engineering_loop"] == "external"


@pytest.mark.parametrize("loop", ["included", "external"])
def test_completed_receipt_round_trips_through_either_loop(tmp_path: Path, loop: str) -> None:
    root = tmp_path / loop
    manifest_path = setup_contract(root, loop)
    output = receipt(manifest_path)

    assessment = assess_engineering_receipt(output, manifest_path)

    assert assessment == {"accepted": True, "status": "completed", "errors": []}


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_failed_or_incomplete_result_preserves_evidence_without_success(status: str, tmp_path: Path) -> None:
    root = tmp_path / status
    manifest_path = setup_contract(root, "included")
    output = receipt(manifest_path, status)

    assessment = assess_engineering_receipt(output, manifest_path)

    assert assessment == {"accepted": False, "status": status, "errors": []}
    assert output["test_evidence"]
    assert output["commit_sha"] is None


@pytest.mark.parametrize(
    "mutation,diagnostic",
    [
        (lambda value: value.pop("review_outcome"), "receipt fields"),
        (lambda value: value.update(manifest_sha256="0" * 64), "stale manifest"),
        (lambda value: value.update(changed_files=["agent/src/db/store.py"]), "exact allowlist"),
        (lambda value: value.update(changed_files=["app/ui/view.py"]), "exact allowlist"),
    ],
)
def test_malformed_stale_or_surrounding_app_receipt_is_invalid(
    tmp_path: Path, mutation, diagnostic: str
) -> None:
    root = tmp_path / "target"
    manifest_path = setup_contract(root, "included")
    output = receipt(manifest_path)
    mutation(output)

    assessment = assess_engineering_receipt(output, manifest_path)

    assert assessment["accepted"] is False
    assert assessment["status"] == "invalid"
    assert diagnostic in "; ".join(assessment["errors"])


def test_architecture_change_status_survives_successful_lifecycle_resume(tmp_path: Path) -> None:
    root = tmp_path / "target"
    manifest_path = setup_contract(root, "external")
    receipt_path = root / "agent-lifecycle/receipts/completed.json"
    write_json(receipt_path, receipt(manifest_path, architecture_changed=True))

    result = resume(root, receipt_path)

    assert result["stage"] == "baseline"
    assert result["receipt"]["architecture_changed"] is True


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_unsuccessful_receipt_is_retained_without_advancing_lifecycle(
    tmp_path: Path, status: str
) -> None:
    root = tmp_path / status
    manifest_path = setup_contract(root, "included")
    receipt_path = root / f"agent-lifecycle/receipts/{status}.json"
    write_json(receipt_path, receipt(manifest_path, status))

    with pytest.raises(LifecycleError, match=status):
        resume(root, receipt_path)

    state = load_state(root)
    assert state["stage"] == "awaiting_engineering"
    assert state["receipt"] is None
    attempt_path = root / state["engineering_attempt"]["path"]
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    assert attempt["status"] == status
    assert attempt["receipt"]["test_evidence"] == [f"engineering loop result: {status}"]


def test_out_of_allowlist_attempt_is_retained_without_advancing_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "target"
    manifest_path = setup_contract(root, "external")
    output = receipt(manifest_path)
    output["changed_files"] = ["app/database/schema.sql"]
    receipt_path = root / "agent-lifecycle/receipts/out-of-scope.json"
    write_json(receipt_path, output)

    with pytest.raises(LifecycleError, match="exact allowlist"):
        resume(root, receipt_path)

    state = load_state(root)
    assert state["stage"] == "awaiting_engineering"
    attempt = json.loads((root / state["engineering_attempt"]["path"]).read_text(encoding="utf-8"))
    assert attempt["status"] == "invalid"
    assert attempt["receipt"]["changed_files"] == ["app/database/schema.sql"]


def test_malformed_handoff_id_cannot_escape_attempts_directory(tmp_path: Path) -> None:
    root = tmp_path / "target"
    manifest_path = setup_contract(root, "external")
    output = receipt(manifest_path)
    output["handoff_id"] = "../../outside"
    receipt_path = root / "agent-lifecycle/receipts/malformed-id.json"
    write_json(receipt_path, output)

    with pytest.raises(LifecycleError, match="handoff id"):
        resume(root, receipt_path)

    state = load_state(root)
    attempt_path = root / state["engineering_attempt"]["path"]
    assert attempt_path.parent == root / "agent-lifecycle/attempts"
    assert not (tmp_path / "outside").exists()
