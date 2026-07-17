from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import uuid
from typing import Any, Awaitable, Callable

from .simulated_user import build_simulator_contract
from .target_adapter import EvalError, ProtocolFailure, TrialResult


class EvalRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class GateDecision:
    decision: str
    reason: str
    proceed: bool


class LangSmithRunner:
    def __init__(
        self,
        evaluate_fn: Callable[..., Any] | None,
        aevaluate_fn: Callable[..., Awaitable[Any]] | None,
    ):
        self.evaluate_fn = evaluate_fn
        self.aevaluate_fn = aevaluate_fn

    @classmethod
    def native(cls) -> "LangSmithRunner":
        from langsmith import aevaluate, evaluate

        return cls(evaluate, aevaluate)

    def evaluate_local(
        self,
        target: Callable[..., Any],
        examples: list[dict[str, Any]],
        evaluators: list[Callable[..., Any]],
        experiment_prefix: str,
    ) -> Any:
        if self.evaluate_fn is None:
            raise EvalRuntimeError("LangSmith evaluate is unavailable")
        return self.evaluate_fn(
            target,
            data=examples,
            evaluators=evaluators,
            experiment_prefix=experiment_prefix,
            upload_results=False,
        )

    async def aevaluate_local(
        self,
        target: Callable[..., Any],
        examples: list[dict[str, Any]],
        evaluators: list[Callable[..., Any]],
        experiment_prefix: str,
    ) -> Any:
        if self.aevaluate_fn is None:
            raise EvalRuntimeError("LangSmith aevaluate is unavailable")
        return await self.aevaluate_fn(
            target,
            data=examples,
            evaluators=evaluators,
            experiment_prefix=experiment_prefix,
            upload_results=False,
        )


@dataclass(frozen=True)
class NativeEvalBindings:
    trajectory_factory: Callable[..., Any]
    rubric_factory: Callable[..., Any]
    simulation_runner: Callable[..., Any]
    user_factory: Callable[..., Any]

    @classmethod
    def native(cls) -> "NativeEvalBindings":
        from agentevals.trajectory.match import create_trajectory_match_evaluator
        from openevals.llm import create_llm_as_judge
        from openevals.simulators import create_llm_simulated_user, run_multiturn_simulation

        return cls(
            create_trajectory_match_evaluator,
            create_llm_as_judge,
            run_multiturn_simulation,
            create_llm_simulated_user,
        )

    def simulate(self, **kwargs: Any) -> Any:
        return self.simulation_runner(**kwargs)

    def create_user(self, **kwargs: Any) -> Any:
        return self.user_factory(**kwargs)


def build_native_evaluators(
    case: dict[str, Any],
    bindings: NativeEvalBindings,
    judge_model: str,
) -> list[Any]:
    trajectory = case["expected"]["trajectory"]
    mode = "superset" if trajectory.get("required_tools") else "subset"
    evaluators = [bindings.trajectory_factory(trajectory_match_mode=mode)]
    for rubric in case["graders"]["rubrics"]:
        evaluators.append(
            bindings.rubric_factory(
                model=judge_model,
                prompt=rubric["criterion"] + "\nEvidence source: " + rubric["evidence"] + "\n{outputs}",
                feedback_key=rubric["id"],
            )
        )
    return evaluators


def native_reference_outputs(case: dict[str, Any]) -> dict[str, Any]:
    required_tools = case["expected"]["trajectory"].get("required_tools", [])
    messages: list[dict[str, Any]] = []
    if required_tools:
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": f"expected-{index}", "name": tool, "args": {}}
                    for index, tool in enumerate(required_tools)
                ],
            }
        )
    return {"messages": messages, "graders": case["graders"], "expected": case["expected"]}


def run_native_simulated_trial(
    case: dict[str, Any],
    adapter: Any,
    bindings: NativeEvalBindings,
    simulator_model: str,
    trial_index: int,
) -> TrialResult:
    if not 0 <= trial_index < case["trials"]:
        raise EvalRuntimeError("trial index is outside configured seeds")
    contract = build_simulator_contract(case)
    trial_id = f"{case['id']}:{trial_index}"
    session = adapter.open_trial(trial_id, case["seeds"][trial_index])
    try:
        with session:
            user = bindings.create_user(
                system=contract.simulator_prompt,
                model=simulator_model,
                fixed_responses=[contract.target_opening],
            )
            active_thread_id: str | None = None

            def app(message: Any, *, thread_id: str, **_: Any) -> dict[str, Any]:
                nonlocal active_thread_id
                if active_thread_id is None:
                    active_thread_id = thread_id
                elif active_thread_id != thread_id:
                    raise EvalRuntimeError("OpenEvals changed thread_id within one trial")
                if isinstance(message, dict):
                    payload = message
                else:
                    payload = {"role": "user", "content": getattr(message, "content", str(message))}
                return session.turn(payload)

            bindings.simulate(
                app=app,
                user=user,
                max_turns=case["simulated_user"]["termination"]["max_turns"],
            )
            return session.finish()
    except ProtocolFailure as failure:
        session.result.status = "inconclusive"
        session.result.errors.append(failure.error)
        return session.result
    except Exception as error:
        session.result.status = "inconclusive"
        session.result.errors.append(EvalError("provider_failure", "simulation", str(error), True))
        return session.result


def deterministic_invariant_evaluator(
    *,
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> list[dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    for grader in reference_outputs["graders"]["deterministic"]:
        check = grader["check"]
        arguments = grader["arguments"]
        passed = _run_check(check, arguments, outputs)
        scores.append(
            {
                "key": grader["id"],
                "score": 1.0 if passed else 0.0,
                "comment": f"{check} {'passed' if passed else 'failed'}",
            }
        )
    return scores


def _run_check(check: str, arguments: dict[str, Any], outputs: dict[str, Any]) -> bool:
    tools = [str(call.get("name")) for call in outputs.get("tool_calls", []) if isinstance(call, dict)]
    if check == "tool_called":
        return arguments.get("tool") in tools
    if check == "tool_not_called":
        return arguments.get("tool") not in tools
    if check == "outcome_equals":
        value: Any = outputs.get("outcome", {})
        for part in str(arguments.get("path", "")).split("."):
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
        return value == arguments.get("value")
    if check == "no_error":
        return not outputs.get("errors")
    raise EvalRuntimeError(f"unsupported deterministic invariant: {check}")


def project_trial_artifact(
    trial: TrialResult,
    scores: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "trial_id": trial.trial_id,
        "status": trial.status,
        "assistant_messages": trial.assistant_messages,
        "tool_calls": trial.tool_calls,
        "tool_results": trial.tool_results,
        "state_snapshots": trial.state_snapshots,
        "outcome": trial.outcome,
        "metrics": {
            "latency_ms": trial.latency_ms,
            "tokens": trial.tokens,
            "cost": trial.cost,
        },
        "scores": scores,
        "trace_refs": trial.trace_refs,
        "errors": [error.to_dict() for error in trial.errors],
    }


def write_diagnostic_artifacts(
    output_directory: Path,
    artifacts: list[dict[str, Any]],
) -> Path:
    run_directory = output_directory / f"run-{uuid.uuid4().hex[:12]}"
    run_directory.mkdir(parents=True, exist_ok=False)
    raw = {"version": 1, "results": artifacts}
    aggregate = {
        "version": 1,
        "trial_count": len(artifacts),
        "complete_count": sum(artifact.get("status") == "complete" for artifact in artifacts),
        "inconclusive_count": sum(artifact.get("status") != "complete" for artifact in artifacts),
    }
    _atomic_write(run_directory / "raw.json", json.dumps(raw, indent=2, sort_keys=True) + "\n")
    _atomic_write(run_directory / "aggregate.json", json.dumps(aggregate, indent=2, sort_keys=True) + "\n")
    return run_directory


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def decide_gate(
    artifacts: list[dict[str, Any]],
    *,
    gate: str,
    baseline: list[dict[str, Any]] | None = None,
    allowed_delta: float = 0.05,
) -> GateDecision:
    if gate not in {"held_in", "held_out"}:
        raise EvalRuntimeError("gate must be held_in or held_out")
    if not artifacts:
        return GateDecision("inconclusive", "no eval results were produced", False)
    if any(artifact.get("status") != "complete" or artifact.get("errors") for artifact in artifacts):
        return GateDecision("inconclusive", "provider, target, harness, or eval failure", False)
    current = _score_index(artifacts)
    if not current:
        return GateDecision("inconclusive", "required score measurements are missing", False)
    if any(value["score"] < value["threshold"] for value in current.values()):
        return GateDecision("reject", "required agent-quality or deterministic score failed", False)
    if gate == "held_in":
        return GateDecision("accept", "all required evals passed", True)
    if baseline is None:
        return GateDecision("inconclusive", "held-out baseline is missing", False)
    if not baseline or any(
        artifact.get("status") != "complete" or artifact.get("errors") for artifact in baseline
    ):
        return GateDecision("inconclusive", "held-out baseline is invalid", False)
    previous = _score_index(baseline)
    if set(previous) != set(current):
        return GateDecision("inconclusive", "held-out score measurements are incomplete", False)
    if any(current[key]["score"] - previous[key]["score"] < -allowed_delta for key in current):
        return GateDecision("reject", "held-out score regression exceeded the allowed delta", False)
    return GateDecision("accept", "all required evals passed", True)


def comparison_summary(
    artifacts: list[dict[str, Any]],
    *,
    deterministic_keys: set[str],
    quality_keys: set[str],
) -> dict[str, Any]:
    if deterministic_keys & quality_keys:
        raise EvalRuntimeError("deterministic and quality score keys must be distinct")
    hard_results: list[float] = []
    quality_results: list[float] = []
    latencies: list[float] = []
    costs: list[float] = []
    for artifact in artifacts:
        scores = artifact.get("scores")
        metrics = artifact.get("metrics")
        if not isinstance(scores, list) or not isinstance(metrics, dict):
            raise EvalRuntimeError("native comparison artifact is missing scores or metrics")
        for score in scores:
            if not isinstance(score, dict) or not isinstance(score.get("key"), str):
                continue
            key = score["key"]
            try:
                value = float(score["score"])
                threshold = float(score["threshold"])
            except (KeyError, TypeError, ValueError) as error:
                raise EvalRuntimeError(f"native comparison score is malformed: {key}") from error
            if not math.isfinite(value) or not math.isfinite(threshold):
                raise EvalRuntimeError(f"native comparison score is not finite: {key}")
            if key in deterministic_keys:
                hard_results.append(1.0 if value >= threshold else 0.0)
            if key in quality_keys:
                quality_results.append(value)
        try:
            latency = float(metrics["latency_ms"])
            cost = float(metrics["cost"])
        except (KeyError, TypeError, ValueError) as error:
            raise EvalRuntimeError("native comparison latency or cost is missing") from error
        if not math.isfinite(latency) or not math.isfinite(cost) or latency < 0 or cost < 0:
            raise EvalRuntimeError("native comparison latency or cost is invalid")
        latencies.append(latency)
        costs.append(cost)
    if not artifacts or not hard_results or not quality_results:
        raise EvalRuntimeError("native comparison measurements are incomplete")
    return {
        "quality": sum(quality_results) / len(quality_results),
        "hard_invariant_pass_rate": sum(hard_results) / len(hard_results),
        "latency_ms": sum(latencies) / len(latencies),
        "cost": sum(costs) / len(costs),
        "trial_count": len(artifacts),
    }


def _score_index(artifacts: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float]]:
    indexed: dict[tuple[str, str], dict[str, float]] = {}
    for artifact in artifacts:
        trial_id = str(artifact.get("trial_id") or "")
        scores = artifact.get("scores")
        if not isinstance(scores, list):
            continue
        for score in scores:
            if not isinstance(score, dict) or "key" not in score or "score" not in score:
                continue
            threshold = score.get("threshold", 1.0)
            numeric_score = float(score["score"])
            numeric_threshold = float(threshold)
            if math.isfinite(numeric_score) and math.isfinite(numeric_threshold):
                indexed[(trial_id, str(score["key"]))] = {
                    "score": numeric_score,
                    "threshold": numeric_threshold,
                }
    return indexed
