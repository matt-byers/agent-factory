from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
import selectors
import subprocess
import time
from typing import Any


ERROR_CATEGORIES = {
    "timeout",
    "process_crash",
    "malformed_output",
    "missing_result",
    "protocol_error",
    "tool_failure",
    "provider_failure",
}
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)\s*([=:])\s*([^\s'\";,]+)"
)
BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[^\s'\";,]+")


@dataclass(frozen=True)
class EvalError:
    category: str
    stage: str
    message: str
    retryable: bool = False
    provider: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", redact_diagnostic(self.message))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrialResult:
    trial_id: str
    status: str
    assistant_messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    state_snapshots: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    tokens: int = 0
    cost: float = 0.0
    trace_refs: list[str] = field(default_factory=list)
    errors: list[EvalError] = field(default_factory=list)


class ProtocolFailure(Exception):
    def __init__(self, error: EvalError):
        self.error = error
        super().__init__(error.message)


class TargetAdapter:
    def __init__(self, command: list[str], timeout_seconds: float = 30.0):
        if not isinstance(command, list) or not command or not all(
            isinstance(argument, str) and argument for argument in command
        ):
            raise ValueError("target command must be a non-empty argument vector")
        if timeout_seconds <= 0:
            raise ValueError("target timeout must be positive")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def open_trial(self, trial_id: str, seed: int) -> "TargetSession":
        return TargetSession(self, trial_id, seed)

    def run_trial(self, trial_id: str, user_messages: list[str], seed: int) -> TrialResult:
        started_at = time.monotonic()
        result = TrialResult(trial_id=trial_id, status="complete")
        process: subprocess.Popen[str] | None = None
        stage = "start"
        try:
            process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            response = self._exchange(
                process,
                {"type": "start", "trial_id": trial_id, "seed": seed},
                stage,
            )
            self._require_type(response, "started", stage)
            for turn_index, message in enumerate(user_messages):
                stage = "turn"
                response = self._exchange(
                    process,
                    {"type": "turn", "turn_index": turn_index, "message": message},
                    stage,
                )
                if response.get("type") == "error":
                    raise ProtocolFailure(self._response_error(response, stage))
                self._require_type(response, "turn_result", stage)
                self._capture_turn(result, response)
            stage = "end"
            response = self._exchange(process, {"type": "end"}, stage)
            if response.get("type") == "error":
                raise ProtocolFailure(self._response_error(response, stage))
            self._require_type(response, "ended", stage)
            if isinstance(response.get("outcome"), dict):
                result.outcome = response["outcome"]
        except ProtocolFailure as failure:
            result.status = "inconclusive"
            result.errors.append(failure.error)
        except (OSError, ValueError, TypeError) as error:
            result.status = "inconclusive"
            result.errors.append(EvalError("protocol_error", stage, str(error)))
        finally:
            self._stop(process)
            result.latency_ms = round((time.monotonic() - started_at) * 1000, 3)
        return result

    def _exchange(
        self,
        process: subprocess.Popen[str],
        request: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        if process.stdin is None or process.stdout is None:
            raise ProtocolFailure(EvalError("process_crash", stage, "target pipes are unavailable"))
        try:
            process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise ProtocolFailure(self._process_error(process, stage, str(error))) from error
        selector = selectors.DefaultSelector()
        try:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(self.timeout_seconds):
                raise ProtocolFailure(
                    EvalError("timeout", stage, f"target did not respond within {self.timeout_seconds:g}s", True)
                )
            line = process.stdout.readline()
        finally:
            selector.close()
        if not line:
            return_code = process.poll()
            if return_code not in {None, 0}:
                raise ProtocolFailure(self._process_error(process, stage, f"target exited with {return_code}"))
            raise ProtocolFailure(EvalError("missing_result", stage, "target closed stdout without a result"))
        try:
            response = json.loads(line)
        except json.JSONDecodeError as error:
            raise ProtocolFailure(EvalError("malformed_output", stage, f"target emitted invalid JSON: {error}")) from error
        if not isinstance(response, dict):
            raise ProtocolFailure(EvalError("malformed_output", stage, "target result must be an object"))
        return response

    def _process_error(self, process: subprocess.Popen[str], stage: str, fallback: str) -> EvalError:
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass
        stderr = ""
        if process.stderr is not None and process.poll() is not None:
            stderr = process.stderr.read().strip()
        return EvalError("process_crash", stage, redact_diagnostic(stderr or fallback))

    def _require_type(self, response: dict[str, Any], expected: str, stage: str) -> None:
        if response.get("type") != expected:
            raise ProtocolFailure(
                EvalError("protocol_error", stage, f"expected {expected}, received {response.get('type')!r}")
            )

    def _response_error(self, response: dict[str, Any], stage: str) -> EvalError:
        category = response.get("category")
        if category not in ERROR_CATEGORIES:
            category = "protocol_error"
        return EvalError(
            category=category,
            stage=stage,
            message=str(response.get("message") or "target reported an error"),
            retryable=bool(response.get("retryable", False)),
            provider=str(response["provider"]) if response.get("provider") else None,
        )

    def _capture_turn(self, result: TrialResult, response: dict[str, Any]) -> None:
        message = response.get("assistant_message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ProtocolFailure(EvalError("malformed_output", "turn", "assistant_message is required"))
        captured: dict[str, list[dict[str, Any]]] = {}
        for source in ("tool_calls", "tool_results"):
            values = response.get(source, [])
            if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
                raise ProtocolFailure(EvalError("malformed_output", "turn", f"{source} must be an object list"))
            captured[source] = values
        native_message = dict(message)
        if captured["tool_calls"]:
            native_message["tool_calls"] = captured["tool_calls"]
        result.assistant_messages.append(native_message)
        result.tool_calls.extend(captured["tool_calls"])
        result.tool_results.extend(captured["tool_results"])
        state = response.get("state")
        if state is not None:
            if not isinstance(state, dict):
                raise ProtocolFailure(EvalError("malformed_output", "turn", "state must be an object"))
            result.state_snapshots.append(state)
        if isinstance(response.get("outcome"), dict):
            result.outcome = response["outcome"]
        usage = response.get("usage", {})
        if not isinstance(usage, dict):
            raise ProtocolFailure(EvalError("malformed_output", "turn", "usage must be an object"))
        result.tokens += int(usage.get("tokens", 0))
        result.cost += float(usage.get("cost", 0.0))
        trace_refs = response.get("trace_refs", [])
        if not isinstance(trace_refs, list) or not all(isinstance(value, str) for value in trace_refs):
            raise ProtocolFailure(EvalError("malformed_output", "turn", "trace_refs must be a string list"))
        result.trace_refs.extend(trace_refs)

    def _stop(self, process: subprocess.Popen[str] | None) -> None:
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.2)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


class TargetSession:
    def __init__(self, adapter: TargetAdapter, trial_id: str, seed: int):
        self.adapter = adapter
        self.trial_id = trial_id
        self.seed = seed
        self.result = TrialResult(trial_id=trial_id, status="complete")
        self.process: subprocess.Popen[str] | None = None
        self.started_at = 0.0
        self.finished = False

    def __enter__(self) -> "TargetSession":
        self.started_at = time.monotonic()
        self.process = subprocess.Popen(
            self.adapter.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        response = self.adapter._exchange(
            self.process,
            {"type": "start", "trial_id": self.trial_id, "seed": self.seed},
            "start",
        )
        self.adapter._require_type(response, "started", "start")
        return self

    def turn(self, message: str | dict[str, Any]) -> dict[str, Any]:
        if self.process is None or self.finished:
            raise ProtocolFailure(EvalError("protocol_error", "turn", "target session is not active"))
        content = message.get("content") if isinstance(message, dict) else message
        response = self.adapter._exchange(
            self.process,
            {"type": "turn", "turn_index": len(self.result.assistant_messages), "message": str(content or "")},
            "turn",
        )
        if response.get("type") == "error":
            raise ProtocolFailure(self.adapter._response_error(response, "turn"))
        self.adapter._require_type(response, "turn_result", "turn")
        self.adapter._capture_turn(self.result, response)
        return self.result.assistant_messages[-1]

    def finish(self) -> TrialResult:
        if self.finished:
            return self.result
        if self.process is None:
            raise ProtocolFailure(EvalError("protocol_error", "end", "target session is not active"))
        response = self.adapter._exchange(self.process, {"type": "end"}, "end")
        if response.get("type") == "error":
            raise ProtocolFailure(self.adapter._response_error(response, "end"))
        self.adapter._require_type(response, "ended", "end")
        if isinstance(response.get("outcome"), dict):
            self.result.outcome = response["outcome"]
        self.finished = True
        return self.result

    def __exit__(self, *_: Any) -> bool:
        self.adapter._stop(self.process)
        self.result.latency_ms = round((time.monotonic() - self.started_at) * 1000, 3)
        return False


def redact_diagnostic(value: str, limit: int = 4000) -> str:
    redacted = SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", value)
    redacted = BEARER_TOKEN.sub("Bearer [redacted]", redacted)
    return redacted[:limit]
