from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMMAND = REPOSITORY_ROOT / "scripts" / "agent-lifecycle"


def run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(COMMAND), "--root", str(root), *arguments],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def write(root: Path, relative: str, content: str = "fixture\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_goal_artifacts(root: Path) -> None:
    write(root, "agent-lifecycle/agent-definition/project-brief.md")
    write(root, "agent-lifecycle/agent-definition/success-metrics.yaml", "{}\n")
    write(root, "agent-lifecycle/agent-definition/business-value-model.yaml", "{}\n")


def write_architecture_artifacts(root: Path, handoff_id: str = "handoff-1") -> None:
    write(root, "agent-lifecycle/architecture/agent-architecture.md")
    write(root, "agent-lifecycle/architecture/decisions.md")
    write(
        root,
        "agent-lifecycle/handoffs/build-handoff.yaml",
        json.dumps({"handoff_id": handoff_id, "approval_status": "approved"}),
    )


def write_receipt(root: Path, name: str = "receipt.json", handoff_id: str = "handoff-1") -> Path:
    return write(
        root,
        f"agent-lifecycle/receipts/{name}",
        json.dumps(
            {
                "handoff_id": handoff_id,
                "result_status": "completed",
                "changed_files": ["agent/prompts/system.md"],
                "test_evidence": ["focused and full suites passed"],
                "review_outcome": "passed",
                "commit_sha": "0123456789abcdef",
                "architecture_changed": False,
            }
        ),
    )


def advance_first_build_to_engineering(root: Path, engineering_loop: str = "included") -> None:
    assert run(root, "start", "first-build", "--engineering-loop", engineering_loop).returncode == 0
    write_goal_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "eval_design"
    write(root, "agent-lifecycle/evals/suite.yaml", "{}\n")
    assert payload(run(root, "next"))["stage"] == "architecture"
    write_architecture_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "engineering"


def test_setup_persists_cli_selections_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "target"

    first = run(
        root,
        "setup",
        "--simulator-model",
        "simulator-model",
        "--judge-model",
        "judge-model",
        "--evidence-mode",
        "local",
        "--engineering-loop",
        "included",
    )
    second = run(
        root,
        "setup",
        "--simulator-model",
        "simulator-model",
        "--judge-model",
        "judge-model",
        "--evidence-mode",
        "local",
        "--engineering-loop",
        "included",
    )

    assert first.returncode == second.returncode == 0
    setup = json.loads((root / "agent-lifecycle/setup.yaml").read_text(encoding="utf-8"))
    assert setup == {
        "version": 1,
        "simulator_model": "simulator-model",
        "judge_model": "judge-model",
        "evidence_mode": "local",
        "engineering_loop": "included",
    }
    assert payload(second)["stage"] == "not_started"


def test_complete_first_build_with_included_loop_and_durable_resume(tmp_path: Path) -> None:
    root = tmp_path / "target"
    advance_first_build_to_engineering(root)

    route = payload(run(root, "next"))
    assert route["stage"] == "waiting_for_receipt"
    assert route["next"] == "/agent-build-loop"
    interrupted = payload(run(root, "status"))
    assert interrupted["stage"] == "waiting_for_receipt"
    assert payload(run(root, "resume", "--receipt", str(write_receipt(root))))["stage"] == "baseline"
    write(root, "agent-lifecycle/evals/baseline-decision.yaml", json.dumps({"decision": "accepted"}))

    completed = payload(run(root, "next"))

    assert completed["stage"] == "operational"
    assert completed["status"] == "complete"


def test_next_rejects_missing_artifact_and_returns_corrective_skill(tmp_path: Path) -> None:
    root = tmp_path / "target"
    start = run(root, "start", "first-build")
    assert start.returncode == 0

    result = run(root, "next")

    assert result.returncode == 1
    failure = payload(result)
    assert failure["stage"] == "goal_definition"
    assert failure["next"] == "/agent-goal-interview"
    assert failure["missing"] == [
        "agent-lifecycle/agent-definition/project-brief.md",
        "agent-lifecycle/agent-definition/success-metrics.yaml",
        "agent-lifecycle/agent-definition/business-value-model.yaml",
    ]
    assert payload(run(root, "status"))["stage"] == "goal_definition"


def test_external_loop_pauses_and_resumes_with_same_receipt_contract(tmp_path: Path) -> None:
    root = tmp_path / "target"
    advance_first_build_to_engineering(root, "external")

    waiting = payload(run(root, "next"))

    assert waiting["stage"] == "waiting_for_receipt"
    assert waiting["next"] == "Provide an engineering receipt from the selected external loop"
    receipt = write_receipt(root, "external.json")
    resumed = run(root, "resume", "--receipt", str(receipt))
    assert resumed.returncode == 0
    assert payload(resumed)["stage"] == "baseline"


def test_upstream_artifact_change_rewinds_to_earliest_affected_stage(tmp_path: Path) -> None:
    root = tmp_path / "target"
    assert run(root, "start", "first-build").returncode == 0
    write_goal_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "eval_design"
    write(root, "agent-lifecycle/evals/suite.yaml", "{}\n")
    assert payload(run(root, "next"))["stage"] == "architecture"
    write(root, "agent-lifecycle/agent-definition/project-brief.md", "changed upstream definition\n")

    status = payload(run(root, "status"))

    assert status["stage"] == "goal_definition"
    assert status["next"] == "/agent-goal-interview"
    assert status["changed"] == ["agent-lifecycle/agent-definition/project-brief.md"]


def test_complete_improvement_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "target"
    assert run(root, "start", "improvement", "--engineering-loop", "included").returncode == 0
    write(root, "agent-lifecycle/evidence/selected-evidence.yaml", "{}\n")
    assert payload(run(root, "next"))["stage"] == "diagnosis"
    write(
        root,
        "agent-lifecycle/handoffs/improvement-handoff.yaml",
        json.dumps({"handoff_id": "improvement-1", "approval_status": "approved"}),
    )
    assert payload(run(root, "next"))["stage"] == "engineering"
    assert payload(run(root, "next"))["stage"] == "waiting_for_receipt"
    assert payload(run(root, "resume", "--receipt", str(write_receipt(root, handoff_id="improvement-1"))))["stage"] == "held_in"
    write(root, "agent-lifecycle/evals/held-in-decision.yaml", json.dumps({"decision": "accepted"}))
    assert payload(run(root, "next"))["stage"] == "held_out"
    write(root, "agent-lifecycle/evals/held-out-decision.yaml", json.dumps({"decision": "accepted"}))
    assert payload(run(root, "next"))["stage"] == "learning"
    write(root, "agent-lifecycle/evidence/eval-loop-learning.yaml", "{}\n")

    completed = payload(run(root, "next"))

    assert completed["stage"] == "operational"
    assert completed["status"] == "complete"


@pytest.mark.parametrize(
    "arguments,diagnostic",
    [
        (("next",), "lifecycle has not started"),
        (("resume", "--receipt", "missing.json"), "not waiting for an engineering receipt"),
        (("start", "unsupported"), "invalid choice"),
    ],
)
def test_invalid_transitions_are_rejected(tmp_path: Path, arguments: tuple[str, ...], diagnostic: str) -> None:
    result = run(tmp_path / "target", *arguments)

    assert result.returncode != 0
    assert diagnostic in (result.stdout + result.stderr).lower()


def test_resume_rejects_malformed_or_failed_receipt_without_advancing(tmp_path: Path) -> None:
    root = tmp_path / "target"
    advance_first_build_to_engineering(root)
    assert payload(run(root, "next"))["stage"] == "waiting_for_receipt"
    malformed = write(root, "agent-lifecycle/receipts/malformed.json", json.dumps({"result_status": "failed"}))

    result = run(root, "resume", "--receipt", str(malformed))

    assert result.returncode == 1
    assert "completed receipt" in payload(result)["error"]
    assert payload(run(root, "status"))["stage"] == "waiting_for_receipt"


def test_unapproved_handoff_cannot_route_to_engineering(tmp_path: Path) -> None:
    root = tmp_path / "target"
    assert run(root, "start", "first-build").returncode == 0
    write_goal_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "eval_design"
    write(root, "agent-lifecycle/evals/suite.yaml", "{}\n")
    assert payload(run(root, "next"))["stage"] == "architecture"
    write_architecture_artifacts(root)
    write(
        root,
        "agent-lifecycle/handoffs/build-handoff.yaml",
        json.dumps({"handoff_id": "handoff-1", "approval_status": "pending"}),
    )

    result = run(root, "next")

    assert result.returncode == 1
    assert "approved handoff" in payload(result)["error"]
    assert payload(run(root, "status"))["stage"] == "architecture"
