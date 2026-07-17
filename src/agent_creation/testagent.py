from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Callable
import uuid

from .simulated_user import SimulatedUserSession
from .target_adapter import (
    EvalError,
    ProtocolFailure,
    TargetAdapter,
    TargetSession,
    redact_diagnostic,
)


class TestAgentError(RuntimeError):
    pass


class TestAgentSession:
    __test__ = False

    def __init__(
        self,
        adapter: TargetAdapter,
        output_directory: Path,
        *,
        context: dict[str, Any] | None = None,
        mode: str = "human",
        seed: int = 0,
        session_id: str | None = None,
    ):
        if mode not in {"human", "simulated"}:
            raise ValueError("testagent mode must be human or simulated")
        self.adapter = adapter
        self.output_directory = output_directory
        self.session_id = session_id or str(uuid.uuid4())
        self.seed = seed
        self.path = output_directory / f"testagent-{self.session_id}.json"
        self.target_session: TargetSession | None = None
        self.active = False
        self.document: dict[str, Any] = {
            "version": 1,
            "evidence_type": "exploratory",
            "acceptance_gate": False,
            "session": {
                "id": self.session_id,
                "mode": mode,
                "seed": seed,
                "started_at": _now(),
                "context": context or {},
            },
            "turns": [],
            "errors": [],
            "termination": None,
        }

    def start(self) -> Path:
        if self.target_session is not None or self.document["termination"] is not None:
            return self.path
        self._persist()
        self.target_session = self.adapter.open_trial(self.session_id, self.seed)
        try:
            self.target_session.__enter__()
            self.active = True
            self.document["session"]["target_context"] = self.target_session.result.session_context
        except ProtocolFailure as failure:
            self._record_session_error(failure.error)
            self._terminate("target_start_failure", "inconclusive")
            self.target_session.__exit__()
        except (OSError, ValueError, TypeError) as error:
            self._record_session_error(EvalError("process_crash", "start", str(error)))
            self._terminate("target_start_failure", "inconclusive")
            self.target_session.__exit__()
        self._persist()
        return self.path

    def send(self, user_message: str) -> dict[str, Any]:
        if not self.active or self.target_session is None:
            raise TestAgentError("testagent session is not active")
        if not user_message.strip():
            raise ValueError("user message must not be empty")
        result = self.target_session.result
        before = {
            "messages": len(result.assistant_messages),
            "tool_calls": len(result.tool_calls),
            "tool_results": len(result.tool_results),
            "states": len(result.state_snapshots),
            "tokens": result.tokens,
            "cost": result.cost,
            "traces": len(result.trace_refs),
        }
        turn = {
            "index": len(self.document["turns"]),
            "user_message": user_message,
            "assistant_message": None,
            "tool_calls": [],
            "tool_results": [],
            "state": None,
            "telemetry": {
                "available": False,
                "tokens": 0,
                "cost": 0.0,
                "trace_refs": [],
            },
            "errors": [],
        }
        try:
            assistant = self.target_session.turn(user_message)
            turn["assistant_message"] = assistant
            turn["tool_calls"] = result.tool_calls[before["tool_calls"] :]
            turn["tool_results"] = result.tool_results[before["tool_results"] :]
            if len(result.state_snapshots) > before["states"]:
                turn["state"] = result.state_snapshots[-1]
            tokens = result.tokens - before["tokens"]
            cost = round(result.cost - before["cost"], 12)
            traces = result.trace_refs[before["traces"] :]
            turn["telemetry"] = {
                "available": bool(tokens or cost or traces),
                "tokens": tokens,
                "cost": cost,
                "trace_refs": traces,
            }
        except ProtocolFailure as failure:
            turn["errors"].append(failure.error.to_dict())
            self.document["errors"].append(failure.error.to_dict())
            self._terminate("target_turn_failure", "inconclusive")
            self._stop_target()
        except (OSError, ValueError, TypeError) as error:
            failure = EvalError("protocol_error", "turn", str(error))
            turn["errors"].append(failure.to_dict())
            self.document["errors"].append(failure.to_dict())
            self._terminate("target_turn_failure", "inconclusive")
            self._stop_target()
        self.document["turns"].append(turn)
        self._persist()
        return turn

    def close(self, reason: str = "completed") -> Path:
        if self.document["termination"] is not None:
            self._persist()
            return self.path
        status = "complete" if reason in {"completed", "user_exit"} else "stopped"
        if self.active and self.target_session is not None:
            try:
                self.target_session.finish()
            except ProtocolFailure as failure:
                self._record_session_error(failure.error)
                reason = "target_end_failure"
                status = "inconclusive"
            except (OSError, ValueError, TypeError) as error:
                self._record_session_error(EvalError("protocol_error", "end", str(error)))
                reason = "target_end_failure"
                status = "inconclusive"
        self._stop_target()
        self._terminate(reason, status)
        self._persist()
        return self.path

    def interrupt(self) -> Path:
        return self.close("interrupted")

    def _stop_target(self) -> None:
        if self.target_session is not None:
            self.target_session.__exit__()
        self.active = False

    def _record_session_error(self, error: EvalError) -> None:
        self.document["errors"].append(error.to_dict())

    def _terminate(self, reason: str, status: str) -> None:
        self.document["termination"] = {
            "reason": reason,
            "status": status,
            "ended_at": _now(),
        }

    def _persist(self) -> None:
        self.output_directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(_redact_artifact(self.document), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def run_simulated_session(
    adapter: TargetAdapter,
    case: dict[str, Any],
    output_directory: Path,
    *,
    propose: Callable[[dict[str, Any], str, int], str],
    trial_index: int = 0,
) -> Path:
    user = SimulatedUserSession.from_case(case, trial_index)
    context = {
        "scenario_id": case["id"],
        "persona": case["simulated_user"]["persona"],
        "private_truth": case["simulated_user"]["private_truth"],
        "disclosure_policy": case["simulated_user"]["disclosure_policy"],
        "stopping_conditions": case["simulated_user"]["termination"],
    }
    session = TestAgentSession(
        adapter,
        output_directory,
        context=context,
        mode="simulated",
        seed=case["seeds"][trial_index],
    )
    session.start()
    if not session.active:
        return session.path
    opening = case["input"]["initial_user_message"]
    turn = session.send(opening)
    maximum = case["simulated_user"]["termination"]["max_turns"]
    while session.active and len(session.document["turns"]) < maximum:
        assistant = _message_text(turn.get("assistant_message"))
        proposal = propose(case, assistant, len(session.document["turns"]) - 1)
        user_turn = user.respond(assistant, proposal)
        if user_turn.kind == "end":
            return session.close(user_turn.reason)
        turn = session.send(user_turn.text)
    if session.active:
        return session.close("maximum turns reached")
    return session.path


def run_human_session(
    adapter: TargetAdapter,
    output_directory: Path,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> list[Path]:
    paths: list[Path] = []
    session = TestAgentSession(adapter, output_directory, context={"interface": "terminal"})
    session.start()
    paths.append(session.path)
    output_fn(f"transcript: {session.path.resolve()}")
    if not session.active:
        return paths
    while True:
        try:
            message = input_fn("You: ").strip()
        except EOFError:
            session.close("user_exit")
            return paths
        except KeyboardInterrupt:
            session.interrupt()
            return paths
        if not message:
            continue
        if message == r"\quit":
            session.close("user_exit")
            return paths
        if message == r"\new":
            session.close("reset")
            session = TestAgentSession(adapter, output_directory, context={"interface": "terminal"})
            session.start()
            paths.append(session.path)
            output_fn(f"transcript: {session.path.resolve()}")
            if not session.active:
                return paths
            continue
        turn = session.send(message)
        assistant = _message_text(turn.get("assistant_message"))
        if assistant:
            output_fn(assistant)
        if turn["errors"]:
            output_fn(f"error: {turn['errors'][0]['category']}: {turn['errors'][0]['message']}")
        if not session.active:
            return paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a target agent directly and retain exploratory evidence."
    )
    parser.add_argument("--target-command", required=True, help="JSON argument array for the target")
    parser.add_argument("--scenario", type=Path, help="JSON case or suite for a bounded simulated run")
    parser.add_argument("--case", help="case id when --scenario contains a suite")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("agent-lifecycle/evidence/testagent"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    arguments = parser.parse_args()
    try:
        command = json.loads(arguments.target_command)
        adapter = TargetAdapter(command, timeout_seconds=arguments.timeout)
        if arguments.scenario is None:
            paths = run_human_session(adapter, arguments.output_dir)
            return 0 if paths and json.loads(paths[-1].read_text())["termination"]["status"] != "inconclusive" else 1
        case = _load_case(arguments.scenario, arguments.case)
        path = run_simulated_session(
            adapter,
            case,
            arguments.output_dir,
            propose=lambda _case, _assistant, _index: "Please continue.",
        )
        print(f"transcript: {path.resolve()}")
        return 0 if json.loads(path.read_text())["termination"]["status"] != "inconclusive" else 1
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError, TestAgentError) as error:
        print(f"testagent: {error}", file=sys.stderr)
        return 1


def _load_case(path: Path, case_id: str | None) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("scenario must be a JSON object")
    if "cases" not in value:
        return value
    cases = value.get("cases")
    if not isinstance(cases, list):
        raise ValueError("scenario cases must be a list")
    if not case_id:
        raise ValueError("--case is required for a scenario suite")
    selected = next(
        (item for item in cases if isinstance(item, dict) and item.get("id") == case_id),
        None,
    )
    if selected is None:
        raise ValueError(f"scenario case not found: {case_id}")
    return selected


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else json.dumps(content, sort_keys=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_artifact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized = "".join(character for character in str(key).casefold() if character.isalnum())
            if normalized in {
                "apikey",
                "accesstoken",
                "token",
                "secret",
                "secretkey",
                "password",
                "credential",
                "credentials",
            }:
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact_artifact(item)
        return redacted
    if isinstance(value, list):
        return [_redact_artifact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_artifact(item) for item in value]
    if isinstance(value, str):
        return redact_diagnostic(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
