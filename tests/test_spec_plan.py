from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.spec_plan import BuildPlanError, accept_build_plan, create_build_plan, load_build_state
from agent_creation.agent_build_loop import BuildLoopError, record_stage
from build_loop_support import build_plan_request, create_build_handoff


def test_spec_plan_creates_and_accepts_self_contained_tdd_units(tmp_path: Path) -> None:
    manifest = create_build_handoff(tmp_path)

    plan_path = create_build_plan(tmp_path, "attempt-001", manifest, build_plan_request())
    plan = plan_path.read_text(encoding="utf-8")
    state = load_build_state(tmp_path, "attempt-001")

    assert plan_path == tmp_path / "agent-lifecycle/attempts/attempt-001/build-plan.md"
    assert state["status"] == "draft"
    assert state["handoff_manifest_sha256"]
    for expected in (
        "## Requirements",
        "## Approved acceptance gates",
        "## Unit 1.1 — Grounded response prompt",
        "### Exact files",
        "### Tests-first RED",
        "### Focused GREEN",
        "### Self-verification",
        "### Smoke tests",
        "### Review",
        "## Full suite",
    ):
        assert expected in plan

    accepted = accept_build_plan(tmp_path, "attempt-001")

    assert accepted["status"] == "accepted"
    assert accepted["accepted_plan_sha256"]


def test_implementation_evidence_is_rejected_before_explicit_acceptance(tmp_path: Path) -> None:
    manifest = create_build_handoff(tmp_path)
    create_build_plan(tmp_path, "attempt-001", manifest, build_plan_request())

    with pytest.raises(BuildLoopError, match="explicit plan acceptance"):
        record_stage(tmp_path, "attempt-001", "red", "1.1", {
            "command": "pytest -q agent/tests/test_system_prompt.py",
            "exit_code": 1,
            "output": "grounded answer rule is missing",
        })


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        (lambda request: request["units"][0]["files"].append("app/database.py"), "exact handoff allowlist"),
        (lambda request: request["units"][0].update(requirement_ids=["FR1"]), "not mapped to a unit"),
        (lambda request: request["units"][0].update(depends_on=["1.1"]), "dependency cycle"),
        (lambda request: request["units"][0].update(self_verification=[]), "self verification"),
        (lambda request: request.update(full_suite_command="pytest wrong"), "approved handoff gate"),
        (lambda request: request.update(review_sources=["unbound.md"]), "not bound by the approved handoff"),
    ],
)
def test_spec_plan_rejects_incomplete_or_out_of_scope_units(
    tmp_path: Path, mutation, diagnostic: str
) -> None:
    manifest = create_build_handoff(tmp_path)
    request = build_plan_request()
    mutation(request)

    with pytest.raises(BuildPlanError, match=diagnostic):
        create_build_plan(tmp_path, "attempt-001", manifest, request)


def test_repository_spec_plan_skill_is_concise_and_handoff_driven() -> None:
    content = (REPOSITORY_ROOT / ".claude/skills/spec-plan/SKILL.md").read_text(encoding="utf-8")

    assert "approved engineering handoff" in content
    assert "scripts/agent-build-loop create-plan" in content
    assert "explicit acceptance" in content
    assert "self-contained" in content
    assert len(content.splitlines()) < 120


def test_build_state_symlink_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text('{"version": 1}', encoding="utf-8")
    path = tmp_path / "agent-lifecycle/attempts/attempt-001/build-state.json"
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)

    with pytest.raises(BuildPlanError, match="regular repository file"):
        load_build_state(tmp_path, "attempt-001")
