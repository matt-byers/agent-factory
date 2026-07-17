from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.target_adapter import TargetAdapter
from agent_creation.testagent import TestAgentSession, run_simulated_session


def write_target(path: Path, *, crash_on_start: bool = False) -> list[str]:
    source = """
import json
import sys

turns = 0
for line in sys.stdin:
    request = json.loads(line)
    if request["type"] == "start":
        if CRASH_ON_START:
            sys.stderr.write("API_KEY=must-not-leak\\n")
            raise SystemExit(7)
        print(json.dumps({
            "type": "started",
            "session_context": {
                "system_prompt": "fixture prompt API_KEY=context-secret",
                "tools": ["lookup"],
                "api_key": "direct-secret",
            },
        }), flush=True)
    elif request["type"] == "turn":
        message = request["message"]
        if message == "protocol tool failure":
            print(json.dumps({
                "type": "error",
                "category": "tool_failure",
                "message": "lookup failed",
            }), flush=True)
            continue
        turns += 1
        response = {
            "type": "turn_result",
            "assistant_message": {
                "role": "assistant",
                "content": f"reply {turns}: {message}",
            },
            "tool_calls": [],
            "tool_results": [],
            "state": {"turns": turns},
        }
        if message == "tool result failure":
            response["tool_calls"] = [{"id": "call-1", "name": "lookup", "args": {}}]
            response["tool_results"] = [{"tool_call_id": "call-1", "status": "error", "content": "offline"}]
        if message != "no telemetry":
            response["usage"] = {"tokens": 5, "cost": 0.01}
            response["trace_refs"] = [f"trace-{turns}"]
        print(json.dumps(response), flush=True)
    elif request["type"] == "end":
        print(json.dumps({"type": "ended", "outcome": {"turns": turns}}), flush=True)
        break
""".replace("CRASH_ON_START", "True" if crash_on_start else "False")
    path.write_text(source, encoding="utf-8")
    return [sys.executable, str(path)]


def transcript(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_repository_command_is_discoverable_and_helpful() -> None:
    assert "PATH_add bin" in (REPOSITORY_ROOT / ".envrc").read_text(encoding="utf-8")
    environment = dict(os.environ)
    environment["PATH"] = f"{REPOSITORY_ROOT / 'bin'}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        ["testagent", "--help"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--target-command" in result.stdout
    assert "--scenario" in result.stdout


def test_human_cli_preserves_continuity_and_prints_transcript_path(tmp_path: Path) -> None:
    target = write_target(tmp_path / "target.py")

    result = subprocess.run(
        [
            str(REPOSITORY_ROOT / "bin/testagent"),
            "--target-command",
            json.dumps(target),
            "--output-dir",
            str(tmp_path / "transcripts"),
        ],
        cwd=REPOSITORY_ROOT,
        input="hello\nagain\n\\quit\n",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "reply 1: hello" in result.stdout
    assert "reply 2: again" in result.stdout
    path = Path(next(line.split("transcript: ", 1)[1] for line in result.stdout.splitlines() if line.startswith("transcript: ")))
    document = transcript(path)
    assert [turn["user_message"] for turn in document["turns"]] == ["hello", "again"]
    assert document["termination"]["reason"] == "user_exit"


def test_session_persists_rich_exploratory_evidence_after_every_turn(tmp_path: Path) -> None:
    adapter = TargetAdapter(write_target(tmp_path / "target.py"), timeout_seconds=1)
    session = TestAgentSession(adapter, tmp_path / "transcripts", context={"prompt": "fixture"})

    session.start()
    assert transcript(session.path)["turns"] == []
    first = session.send("tool result failure")
    after_first = transcript(session.path)

    assert first["assistant_message"]["content"].startswith("reply 1")
    assert after_first["evidence_type"] == "exploratory"
    assert after_first["acceptance_gate"] is False
    assert after_first["session"]["context"] == {"prompt": "fixture"}
    assert after_first["session"]["target_context"] == {
        "system_prompt": "fixture prompt API_KEY=[redacted]",
        "tools": ["lookup"],
        "api_key": "[redacted]",
    }
    assert "context-secret" not in session.path.read_text(encoding="utf-8")
    assert "direct-secret" not in session.path.read_text(encoding="utf-8")
    assert after_first["turns"][0]["tool_calls"][0]["name"] == "lookup"
    assert after_first["turns"][0]["tool_results"][0]["status"] == "error"
    assert after_first["turns"][0]["state"] == {"turns": 1}
    assert after_first["turns"][0]["telemetry"] == {
        "available": True,
        "tokens": 5,
        "cost": 0.01,
        "trace_refs": ["trace-1"],
    }

    session.send("second")
    assert len(transcript(session.path)["turns"]) == 2
    session.close("completed")
    assert transcript(session.path)["termination"]["reason"] == "completed"


def test_separate_sessions_and_reset_are_isolated(tmp_path: Path) -> None:
    adapter = TargetAdapter(write_target(tmp_path / "target.py"), timeout_seconds=1)
    first = TestAgentSession(adapter, tmp_path / "transcripts")
    first.start()
    first.send("first")
    first.close("reset")
    second = TestAgentSession(adapter, tmp_path / "transcripts")
    second.start()
    second.send("second")
    second.close("user_exit")

    assert first.path != second.path
    assert transcript(first.path)["session"]["id"] != transcript(second.path)["session"]["id"]
    assert transcript(first.path)["turns"][0]["assistant_message"]["content"] == "reply 1: first"
    assert transcript(second.path)["turns"][0]["assistant_message"]["content"] == "reply 1: second"
    assert transcript(first.path)["termination"]["reason"] == "reset"


def test_interruption_is_persisted_and_closes_target(tmp_path: Path) -> None:
    session = TestAgentSession(
        TargetAdapter(write_target(tmp_path / "target.py"), timeout_seconds=1),
        tmp_path / "transcripts",
    )
    session.start()
    session.send("before interrupt")

    session.interrupt()

    document = transcript(session.path)
    assert document["termination"]["reason"] == "interrupted"
    assert document["termination"]["status"] == "stopped"


def test_target_crash_is_typed_redacted_and_readable(tmp_path: Path) -> None:
    session = TestAgentSession(
        TargetAdapter(write_target(tmp_path / "crash.py", crash_on_start=True), timeout_seconds=1),
        tmp_path / "transcripts",
    )

    session.start()

    document = transcript(session.path)
    assert document["termination"]["status"] == "inconclusive"
    assert document["errors"][0]["category"] == "process_crash"
    assert "must-not-leak" not in json.dumps(document)
    assert session.path.is_file()


def test_protocol_tool_failure_and_missing_telemetry_are_explicit(tmp_path: Path) -> None:
    session = TestAgentSession(
        TargetAdapter(write_target(tmp_path / "target.py"), timeout_seconds=1),
        tmp_path / "transcripts",
    )
    session.start()
    session.send("no telemetry")
    session.send("protocol tool failure")

    document = transcript(session.path)
    assert document["turns"][0]["telemetry"]["available"] is False
    assert document["turns"][1]["errors"][0]["category"] == "tool_failure"
    assert document["termination"]["status"] == "inconclusive"


def simulated_case() -> dict[str, Any]:
    return {
        "id": "bounded-probe",
        "split": "held_in",
        "tags": ["capability", "positive"],
        "trials": 1,
        "seeds": [7],
        "input": {"initial_user_message": "Help with my account."},
        "simulated_user": {
            "persona": "A cautious account owner.",
            "private_truth": [
                {"id": "tier", "value": "My plan is enterprise.", "reveal_on": ["plan"]}
            ],
            "disclosure_policy": {
                "mode": "progressive",
                "max_facts_per_turn": 1,
                "fallback": "next_unrevealed",
            },
            "termination": {
                "success_condition": "The account request is resolved.",
                "max_turns": 2,
                "stall_turns": 1,
            },
        },
        "expected": {
            "outcome": "Resolve the request.",
            "trajectory": {"required_tools": [], "forbidden_tools": [], "ordered_tools": []},
        },
        "graders": {
            "deterministic": [{"id": "safe", "check": "no_error", "arguments": {}}],
            "rubrics": [
                {
                    "id": "quality",
                    "criterion": "Resolve the request.",
                    "evidence": "final_output",
                    "threshold": 0.8,
                }
            ],
        },
    }


def test_simulated_user_session_is_bounded_and_uses_case_policy(tmp_path: Path) -> None:
    path = run_simulated_session(
        TargetAdapter(write_target(tmp_path / "target.py"), timeout_seconds=1),
        simulated_case(),
        tmp_path / "transcripts",
        propose=lambda _case, _assistant, index: "Please continue" if index == 0 else "Please continue",
    )

    document = transcript(path)
    assert document["session"]["mode"] == "simulated"
    assert document["session"]["context"]["scenario_id"] == "bounded-probe"
    assert len(document["turns"]) <= 2
    assert document["termination"]["reason"] in {
        "maximum turns reached",
        "no new information to disclose",
    }
    assert document["evidence_type"] == "exploratory"
