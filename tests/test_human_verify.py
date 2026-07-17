from __future__ import annotations

from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.human_verify import HumanVerificationError, record_manual_evidence
from agent_creation.spec_plan import accept_build_plan, create_build_plan
from build_loop_support import build_plan_request, create_build_handoff


def test_human_verify_records_dated_evidence_only_in_the_owning_plan(tmp_path: Path) -> None:
    manifest = create_build_handoff(tmp_path)
    plan = create_build_plan(tmp_path, "attempt-001", manifest, build_plan_request(manual_smoke=True))
    assert "Status: Pending" in plan.read_text(encoding="utf-8")
    accept_build_plan(tmp_path, "attempt-001")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}

    record_manual_evidence(
        tmp_path,
        "attempt-001",
        "1.1",
        "prompt-behavior",
        "Passed",
        "Domain owner approved the tone in terminal transcript run-17.",
        "2026-07-17",
    )

    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}
    content = plan.read_text(encoding="utf-8")
    assert before == after
    assert "Status: Passed" in content
    assert "Date: 2026-07-17" in content
    assert "Evidence: Domain owner approved the tone in terminal transcript run-17." in content


def test_human_verify_rejects_automated_checks_and_invalid_statuses(tmp_path: Path) -> None:
    manifest = create_build_handoff(tmp_path)
    create_build_plan(tmp_path, "attempt-001", manifest, build_plan_request(manual_smoke=False))
    accept_build_plan(tmp_path, "attempt-001")

    with pytest.raises(HumanVerificationError, match="automated"):
        record_manual_evidence(
            tmp_path,
            "attempt-001",
            "1.1",
            "prompt-behavior",
            "Passed",
            "Observed output.",
            "2026-07-17",
        )


def test_failed_manual_evidence_remains_in_the_owning_plan(tmp_path: Path) -> None:
    manifest = create_build_handoff(tmp_path)
    plan = create_build_plan(tmp_path, "attempt-001", manifest, build_plan_request(manual_smoke=True))
    accept_build_plan(tmp_path, "attempt-001")

    record_manual_evidence(
        tmp_path,
        "attempt-001",
        "1.1",
        "prompt-behavior",
        "Failed",
        "Domain owner found an unacceptable unsupported claim.",
        "2026-07-17",
    )

    content = plan.read_text(encoding="utf-8")
    assert "Status: Failed" in content
    assert "Status: Pending" not in content
    with pytest.raises(HumanVerificationError, match="Passed, Failed, or Blocked"):
        record_manual_evidence(
            tmp_path,
            "attempt-001",
            "1.1",
            "prompt-behavior",
            "Pending",
            "Not run.",
            "2026-07-17",
        )


def test_repository_human_verify_skill_keeps_the_plan_as_source_of_truth() -> None:
    content = (REPOSITORY_ROOT / ".claude/skills/human-verify/SKILL.md").read_text(encoding="utf-8")

    assert "build-plan.md" in content
    assert "only durable status" in content
    assert all(status in content for status in ("Passed", "Failed", "Blocked"))
    assert len(content.splitlines()) < 100
