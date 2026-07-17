from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.agent_build_loop import BuildLoopError, commit_and_write_receipt, record_stage
from agent_creation.engineering_handoff import validate_receipt
from agent_creation.spec_plan import accept_build_plan, create_build_plan
from agent_creation.spec_plan import load_build_state
from build_loop_support import build_plan_request, create_build_handoff


def run_git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()


def prepare_attempt(root: Path, *, manual_smoke: bool = False, testagent: bool = True) -> Path:
    manifest = create_build_handoff(root)
    create_build_plan(root, "attempt-001", manifest, build_plan_request(manual_smoke, testagent))
    accept_build_plan(root, "attempt-001")
    return manifest


def complete_evidence(root: Path, *, include_testagent: bool = True) -> None:
    record_stage(root, "attempt-001", "red", "1.1", {
        "command": "pytest -q agent/tests/test_system_prompt.py",
        "exit_code": 1,
        "output": "AssertionError: grounded answer rule is missing",
    })
    record_stage(root, "attempt-001", "implementation", "1.1", {
        "changed_files": ["agent/prompts/system.md", "agent/tests/test_system_prompt.py"]
    })
    record_stage(root, "attempt-001", "focused_green", "1.1", {
        "command": "pytest -q agent/tests/test_system_prompt.py", "exit_code": 0
    })
    record_stage(root, "attempt-001", "self_verification", "1.1", {
        "commands": [{"command": "python -m compileall -q agent", "exit_code": 0}],
        "smoke_tests": [{"id": "prompt-behavior", "status": "Passed", "evidence": "Observed expected output."}],
    })
    if include_testagent:
        record_stage(root, "attempt-001", "testagent", "1.1", {
            "command": "testagent", "status": "Passed", "transcript": "Grounded answer returned."
        })
    record_stage(root, "attempt-001", "review", "1.1", {
        "sources": [
            "docs/references/agent-building-best-practices.md",
            "agent-lifecycle/architecture/agent-architecture.md",
        ],
        "blocking_findings": [],
        "high_findings": [],
        "outcome": "passed",
    })
    record_stage(root, "attempt-001", "full_suite", None, {
        "command": "pytest -q", "exit_code": 0, "output": "all tests passed"
    })


def test_build_loop_enforces_the_accepted_tdd_sequence(tmp_path: Path) -> None:
    prepare_attempt(tmp_path)

    with pytest.raises(BuildLoopError, match="red"):
        record_stage(tmp_path, "attempt-001", "implementation", "1.1", {
            "changed_files": ["agent/prompts/system.md"]
        })
    with pytest.raises(BuildLoopError, match="expected RED"):
        record_stage(tmp_path, "attempt-001", "red", "1.1", {
            "command": "pytest -q agent/tests/test_system_prompt.py",
            "exit_code": 0,
            "output": "passed",
        })
    with pytest.raises(BuildLoopError, match="evidence must contain an object"):
        record_stage(tmp_path, "attempt-001", "red", "1.1", [])

    complete_evidence(tmp_path)

    with pytest.raises(BuildLoopError, match="exactly once"):
        record_stage(tmp_path, "attempt-001", "full_suite", None, {
            "command": "pytest -q", "exit_code": 0
        })


def test_optional_testagent_is_required_only_when_the_plan_enables_it(tmp_path: Path) -> None:
    required = tmp_path / "required"
    prepare_attempt(required, testagent=True)
    with pytest.raises(BuildLoopError, match="testagent"):
        complete_evidence(required, include_testagent=False)

    skipped = tmp_path / "skipped"
    prepare_attempt(skipped, testagent=False)
    complete_evidence(skipped, include_testagent=False)


def test_failed_testagent_review_and_full_suite_do_not_advance_or_commit(tmp_path: Path) -> None:
    prepare_attempt(tmp_path, testagent=True)
    record_stage(tmp_path, "attempt-001", "red", "1.1", {
        "command": "pytest -q agent/tests/test_system_prompt.py",
        "exit_code": 1,
        "output": "grounded answer rule is missing",
    })
    record_stage(tmp_path, "attempt-001", "implementation", "1.1", {
        "changed_files": ["agent/prompts/system.md", "agent/tests/test_system_prompt.py"]
    })
    record_stage(tmp_path, "attempt-001", "focused_green", "1.1", {
        "command": "pytest -q agent/tests/test_system_prompt.py", "exit_code": 0
    })
    record_stage(tmp_path, "attempt-001", "self_verification", "1.1", {
        "commands": [{"command": "python -m compileall -q agent", "exit_code": 0}],
        "smoke_tests": [{"id": "prompt-behavior", "status": "Passed", "evidence": "Observed."}],
    })
    with pytest.raises(BuildLoopError, match="passing bounded transcript"):
        record_stage(tmp_path, "attempt-001", "testagent", "1.1", {
            "command": "testagent", "status": "Failed", "transcript": "Boundary probe failed."
        })
    record_stage(tmp_path, "attempt-001", "testagent", "1.1", {
        "command": "testagent", "status": "Passed", "transcript": "Boundary probe recovered."
    })
    with pytest.raises(BuildLoopError, match="blocking or high"):
        record_stage(tmp_path, "attempt-001", "review", "1.1", {
            "sources": [
                "docs/references/agent-building-best-practices.md",
                "agent-lifecycle/architecture/agent-architecture.md",
            ],
            "blocking_findings": [], "high_findings": ["Unbounded prompt change"], "outcome": "failed",
        })
    record_stage(tmp_path, "attempt-001", "review", "1.1", {
        "sources": [
            "docs/references/agent-building-best-practices.md",
            "agent-lifecycle/architecture/agent-architecture.md",
        ],
        "blocking_findings": [], "high_findings": [], "outcome": "passed",
    })
    with pytest.raises(BuildLoopError, match="full suite command must pass"):
        record_stage(tmp_path, "attempt-001", "full_suite", None, {
            "command": "pytest -q", "exit_code": 1, "output": "one regression"
        })
    assert not (tmp_path / "agent-lifecycle/attempts/attempt-001/engineering-receipt.json").exists()
    failures = load_build_state(tmp_path, "attempt-001")["failures"]
    assert [(item["stage"], item["unit_id"]) for item in failures] == [
        ("testagent", "1.1"),
        ("review", "1.1"),
        ("full_suite", None),
    ]

    record_stage(tmp_path, "attempt-001", "full_suite", None, {
        "command": "pytest -q", "exit_code": 0, "output": "all tests passed"
    })


def test_explicit_commit_contains_only_allowlisted_files_and_writes_receipt(tmp_path: Path) -> None:
    run_git(tmp_path, "init", "-q")
    run_git(tmp_path, "config", "user.name", "Test Operator")
    run_git(tmp_path, "config", "user.email", "operator@example.com")
    baseline = tmp_path / "README.md"
    baseline.write_text("baseline\n", encoding="utf-8")
    run_git(tmp_path, "add", "README.md")
    run_git(tmp_path, "commit", "-q", "-m", "baseline")
    manifest = prepare_attempt(tmp_path)
    complete_evidence(tmp_path)
    prompt = tmp_path / "agent/prompts/system.md"
    test = tmp_path / "agent/tests/test_system_prompt.py"
    unrelated = tmp_path / "surrounding-app.txt"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    test.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("Use grounded answers.\n", encoding="utf-8")
    test.write_text("def test_prompt():\n    assert True\n", encoding="utf-8")
    unrelated.write_text("preserve me\n", encoding="utf-8")

    receipt_path = commit_and_write_receipt(
        tmp_path, "attempt-001", "agent: implement accepted plan", architecture_changed=False
    )

    committed = set(run_git(tmp_path, "show", "--pretty=format:", "--name-only", "HEAD").splitlines())
    status = run_git(tmp_path, "status", "--short")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert committed == {"agent/prompts/system.md", "agent/tests/test_system_prompt.py"}
    assert "?? surrounding-app.txt" in status
    assert receipt["build_plan_sha256"]
    assert receipt["changed_files"] == sorted(committed)
    assert [item.split(":", 1)[0] for item in receipt["test_evidence"]] == [
        "unit 1.1 RED",
        "unit 1.1 focused GREEN",
        "unit 1.1 self-verification and smoke tests",
        "unit 1.1 testagent",
        "unit 1.1 review",
        "full suite",
    ]
    assert validate_receipt(receipt, manifest) == []


def test_repository_build_loop_skill_contains_only_the_interchangeable_contract() -> None:
    content = (REPOSITORY_ROOT / ".claude/skills/agent-build-loop/SKILL.md").read_text(
        encoding="utf-8"
    )

    ordered = [
        "Plan acceptance", "RED", "Implementation", "Focused GREEN", "Self-verification",
        "testagent", "Review", "Full suite", "Commit", "Receipt",
    ]
    positions = [content.index(item) for item in ordered]
    assert positions == sorted(positions)
    assert "one full suite" in content
    assert "exact allowlist" in content
    assert len(content.splitlines()) < 140
