from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.target_adapter import TargetAdapter


TARGET_PROGRAM = r'''
import json
import sys
import time

mode = sys.argv[1]
count = 0
for line in sys.stdin:
    request = json.loads(line)
    kind = request["type"]
    if mode == "timeout":
        time.sleep(2)
    if mode == "crash":
        raise RuntimeError("fixture crash")
    if mode == "malformed":
        print("not-json", flush=True)
        continue
    if mode == "missing":
        sys.exit(0)
    if kind == "start":
        count = 0
        print(json.dumps({"type": "started", "trial_id": request["trial_id"]}), flush=True)
    elif kind == "turn":
        count += 1
        if mode == "tool_failure":
            print(json.dumps({"type": "error", "category": "tool_failure", "message": "lookup failed", "retryable": False}), flush=True)
        elif mode == "provider_failure":
            print(json.dumps({"type": "error", "category": "provider_failure", "message": "rate limited", "retryable": True, "provider": "fixture"}), flush=True)
        else:
            print(json.dumps({
                "type": "turn_result",
                "assistant_message": {"role": "assistant", "content": f"reply-{count}"},
                "tool_calls": [{"id": f"call-{count}", "name": "lookup", "arguments": {"turn": count}}],
                "tool_results": [{"tool_call_id": f"call-{count}", "content": "ok"}],
                "state": {"turn": count},
                "outcome": {"resolved": count > 1},
                "usage": {"tokens": 10, "cost": 0.01},
                "trace_refs": [f"trace-{count}"]
            }), flush=True)
    elif kind == "end":
        print(json.dumps({"type": "ended", "outcome": {"resolved": count > 1}}), flush=True)
'''


@pytest.fixture
def target_program(tmp_path: Path) -> Path:
    path = tmp_path / "target.py"
    path.write_text(TARGET_PROGRAM, encoding="utf-8")
    return path


def adapter(target_program: Path, mode: str = "good", timeout: float = 0.5) -> TargetAdapter:
    return TargetAdapter([sys.executable, "-u", str(target_program), mode], timeout_seconds=timeout)


def test_jsonl_trial_preserves_multiturn_state_and_captures_evidence(target_program: Path) -> None:
    result = adapter(target_program).run_trial("trial-1", ["first", "second"], seed=7)

    assert result.status == "complete"
    assert [message["content"] for message in result.assistant_messages] == ["reply-1", "reply-2"]
    assert result.assistant_messages[0]["tool_calls"][0]["name"] == "lookup"
    assert result.tool_calls[1]["arguments"] == {"turn": 2}
    assert result.tool_results[0]["content"] == "ok"
    assert result.state_snapshots == [{"turn": 1}, {"turn": 2}]
    assert result.outcome == {"resolved": True}
    assert result.tokens == 20
    assert result.cost == pytest.approx(0.02)
    assert result.trace_refs == ["trace-1", "trace-2"]
    assert result.errors == []


def test_each_trial_gets_a_fresh_target_process(target_program: Path) -> None:
    target = adapter(target_program)

    first = target.run_trial("first", ["hello"], seed=1)
    second = target.run_trial("second", ["hello"], seed=2)

    assert first.assistant_messages[0]["content"] == "reply-1"
    assert second.assistant_messages[0]["content"] == "reply-1"


@pytest.mark.parametrize(
    "mode,category",
    [
        ("timeout", "timeout"),
        ("crash", "process_crash"),
        ("malformed", "malformed_output"),
        ("missing", "missing_result"),
        ("tool_failure", "tool_failure"),
        ("provider_failure", "provider_failure"),
    ],
)
def test_target_failures_are_typed_inconclusive_results(
    target_program: Path, mode: str, category: str
) -> None:
    result = adapter(target_program, mode, timeout=0.05).run_trial("failed", ["hello"], seed=1)

    assert result.status == "inconclusive"
    assert result.errors[0].category == category
    assert result.errors[0].stage in {"start", "turn", "end"}
    assert result.latency_ms >= 0


def test_command_is_an_argument_vector_not_a_shell_string() -> None:
    with pytest.raises(ValueError, match="argument vector"):
        TargetAdapter("python target.py")


def test_crash_diagnostic_redacts_secret_assignments(tmp_path: Path) -> None:
    path = tmp_path / "secret_target.py"
    path.write_text(
        "import sys\nsys.stderr.write('API_KEY=super-secret-value\\n')\nraise RuntimeError('failed')\n",
        encoding="utf-8",
    )

    result = TargetAdapter([sys.executable, str(path)], timeout_seconds=0.5).run_trial("secret", [], 1)

    assert result.status == "inconclusive"
    assert "super-secret-value" not in result.errors[0].message
    assert "[redacted]" in result.errors[0].message
