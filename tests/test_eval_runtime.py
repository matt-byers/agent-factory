from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.eval_runtime import (
    GateDecision,
    LangSmithRunner,
    NativeEvalBindings,
    build_native_evaluators,
    decide_gate,
    deterministic_invariant_evaluator,
    native_reference_outputs,
    project_trial_artifact,
    run_native_simulated_trial,
    write_diagnostic_artifacts,
)
from agent_creation.target_adapter import EvalError, TrialResult


def eval_case() -> dict:
    return {
        "id": "fixture-case",
        "expected": {
            "outcome": "Resolve the request",
            "trajectory": {
                "required_tools": ["lookup"],
                "forbidden_tools": ["delete"],
                "ordered_tools": [],
            },
        },
        "graders": {
            "deterministic": [
                {"id": "lookup-used", "check": "tool_called", "arguments": {"tool": "lookup"}},
                {"id": "no-delete", "check": "tool_not_called", "arguments": {"tool": "delete"}},
                {"id": "resolved", "check": "outcome_equals", "arguments": {"path": "resolved", "value": True}},
            ],
            "rubrics": [
                {
                    "id": "answer-quality",
                    "criterion": "The final answer resolves the request.",
                    "evidence": "final_output",
                    "threshold": 0.8,
                }
            ],
        },
        "simulated_user": {"termination": {"max_turns": 4}},
    }


def complete_trial() -> TrialResult:
    return TrialResult(
        trial_id="trial-1",
        status="complete",
        assistant_messages=[{"role": "assistant", "content": "Resolved"}],
        tool_calls=[{"id": "call-1", "name": "lookup", "arguments": {}}],
        tool_results=[{"tool_call_id": "call-1", "content": "ok"}],
        state_snapshots=[{"resolved": True}],
        outcome={"resolved": True},
        latency_ms=12.5,
        tokens=20,
        cost=0.02,
        trace_refs=["trace-1"],
        errors=[],
    )


def test_local_runner_delegates_to_langsmith_evaluate_without_upload() -> None:
    calls: list[dict] = []

    def evaluate(target, **kwargs):
        calls.append({"target": target, **kwargs})
        return {"experiment_id": "local-1"}

    runner = LangSmithRunner(evaluate_fn=evaluate, aevaluate_fn=None)
    target = lambda inputs: inputs
    examples = [{"inputs": {"messages": []}}]
    evaluators = [lambda **kwargs: {"key": "pass", "score": 1}]

    result = runner.evaluate_local(target, examples, evaluators, experiment_prefix="fixture")

    assert result == {"experiment_id": "local-1"}
    assert calls == [
        {
            "target": target,
            "data": examples,
            "evaluators": evaluators,
            "experiment_prefix": "fixture",
            "upload_results": False,
        }
    ]


def test_async_local_runner_delegates_to_langsmith_aevaluate_without_upload() -> None:
    calls: list[dict] = []

    async def aevaluate(target, **kwargs):
        calls.append({"target": target, **kwargs})
        return {"experiment_id": "async-local-1"}

    runner = LangSmithRunner(evaluate_fn=None, aevaluate_fn=aevaluate)

    result = asyncio.run(runner.aevaluate_local(lambda value: value, [], [], experiment_prefix="async"))

    assert result == {"experiment_id": "async-local-1"}
    assert calls[0]["upload_results"] is False


def test_native_bindings_delegate_trajectory_rubrics_and_simulation() -> None:
    calls: list[tuple[str, dict]] = []

    def trajectory_factory(**kwargs):
        calls.append(("trajectory", kwargs))
        return "trajectory-evaluator"

    def rubric_factory(**kwargs):
        calls.append(("rubric", kwargs))
        return "rubric-evaluator"

    def simulation_runner(**kwargs):
        calls.append(("simulation", kwargs))
        return {"trajectory": []}

    def user_factory(**kwargs):
        calls.append(("user", kwargs))
        return "simulated-user"

    bindings = NativeEvalBindings(trajectory_factory, rubric_factory, simulation_runner, user_factory)
    evaluators = build_native_evaluators(eval_case(), bindings, judge_model="fixture:model")
    simulation = bindings.simulate(app="target", user="simulated-user", max_turns=4)

    assert evaluators == ["trajectory-evaluator", "rubric-evaluator"]
    assert calls[0] == ("trajectory", {"trajectory_match_mode": "superset"})
    assert calls[1][0] == "rubric"
    assert calls[1][1]["feedback_key"] == "answer-quality"
    assert simulation == {"trajectory": []}
    assert calls[2] == ("simulation", {"app": "target", "user": "simulated-user", "max_turns": 4})


def test_agent_evals_reference_contains_expected_tool_trajectory() -> None:
    reference = native_reference_outputs(eval_case())

    assert reference["messages"] == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "expected-0", "name": "lookup", "args": {}}],
        }
    ]
    assert reference["graders"] == eval_case()["graders"]


def test_native_simulation_uses_one_target_session_for_all_turns() -> None:
    opened: list[tuple[str, int]] = []

    class Session:
        def __init__(self):
            self.result = complete_trial()
            self.result.assistant_messages = []
            self.turns = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def turn(self, message):
            self.turns += 1
            reply = {"role": "assistant", "content": f"reply-{self.turns}"}
            self.result.assistant_messages.append(reply)
            return reply

        def finish(self):
            return self.result

    class Adapter:
        def open_trial(self, trial_id, seed):
            opened.append((trial_id, seed))
            return Session()

    def simulation_runner(**kwargs):
        kwargs["app"]({"role": "user", "content": "first"}, thread_id="one")
        kwargs["app"]({"role": "user", "content": "second"}, thread_id="one")
        return {"trajectory": []}

    bindings = NativeEvalBindings(
        lambda **kwargs: None,
        lambda **kwargs: None,
        simulation_runner,
        lambda **kwargs: "native-user",
    )
    selected = eval_case() | {
        "split": "held_in",
        "tags": ["capability", "positive"],
        "trials": 1,
        "seeds": [17],
        "input": {"initial_user_message": "start"},
        "simulated_user": {
            "persona": "Fixture user",
            "private_truth": [{"id": "fact", "value": "secret", "reveal_on": ["fact"]}],
            "disclosure_policy": {"mode": "progressive", "max_facts_per_turn": 1, "fallback": "next_unrevealed"},
            "termination": {"success_condition": "done", "max_turns": 4, "stall_turns": 2},
        },
    }

    result = run_native_simulated_trial(selected, Adapter(), bindings, "fixture:model", 0)

    assert opened == [("fixture-case:0", 17)]
    assert [message["content"] for message in result.assistant_messages] == ["reply-1", "reply-2"]


def test_custom_evaluator_is_limited_to_declared_deterministic_invariants() -> None:
    scores = deterministic_invariant_evaluator(
        outputs={
            "tool_calls": [{"name": "lookup"}],
            "outcome": {"resolved": True},
            "errors": [],
        },
        reference_outputs={"graders": eval_case()["graders"]},
    )

    assert scores == [
        {"key": "lookup-used", "score": 1.0, "comment": "tool_called passed"},
        {"key": "no-delete", "score": 1.0, "comment": "tool_not_called passed"},
        {"key": "resolved", "score": 1.0, "comment": "outcome_equals passed"},
    ]


def test_compact_projection_keeps_trajectory_outcome_metrics_and_typed_errors() -> None:
    artifact = project_trial_artifact(
        complete_trial(),
        scores=[{"key": "quality", "score": 0.9, "threshold": 0.8}],
    )

    assert artifact == {
        "trial_id": "trial-1",
        "status": "complete",
        "assistant_messages": [{"role": "assistant", "content": "Resolved"}],
        "tool_calls": [{"id": "call-1", "name": "lookup", "arguments": {}}],
        "tool_results": [{"tool_call_id": "call-1", "content": "ok"}],
        "state_snapshots": [{"resolved": True}],
        "outcome": {"resolved": True},
        "metrics": {"latency_ms": 12.5, "tokens": 20, "cost": 0.02},
        "scores": [{"key": "quality", "score": 0.9, "threshold": 0.8}],
        "trace_refs": ["trace-1"],
        "errors": [],
    }


def test_gate_accepts_complete_passing_native_results() -> None:
    decision = decide_gate(
        [project_trial_artifact(complete_trial(), [{"key": "quality", "score": 0.9, "threshold": 0.8}])],
        gate="held_in",
    )

    assert decision == GateDecision("accept", "all required evals passed", True)


def test_gate_rejects_agent_quality_or_deterministic_failure() -> None:
    artifact = project_trial_artifact(
        complete_trial(),
        [{"key": "quality", "score": 0.4, "threshold": 0.8}],
    )

    assert decide_gate([artifact], gate="held_in").decision == "reject"


def test_gate_is_inconclusive_for_provider_harness_or_missing_measurement() -> None:
    failed = complete_trial()
    failed.status = "inconclusive"
    failed.errors = [EvalError("provider_failure", "turn", "rate limited", True, "fixture")]
    artifact = project_trial_artifact(failed, [])

    assert decide_gate([artifact], gate="held_in").decision == "inconclusive"
    assert decide_gate([], gate="held_in").decision == "inconclusive"
    complete_without_scores = project_trial_artifact(complete_trial(), [])
    assert decide_gate([complete_without_scores], gate="held_in").decision == "inconclusive"


def test_held_out_comparison_rejects_regression_and_accepts_stable_scores() -> None:
    baseline = [{"trial_id": "trial-1", "status": "complete", "scores": [{"key": "quality", "score": 0.9, "threshold": 0.8}], "errors": []}]
    regressed = [{"trial_id": "trial-1", "status": "complete", "scores": [{"key": "quality", "score": 0.7, "threshold": 0.8}], "errors": []}]
    stable = [{"trial_id": "trial-1", "status": "complete", "scores": [{"key": "quality", "score": 0.88, "threshold": 0.8}], "errors": []}]

    assert decide_gate(regressed, gate="held_out", baseline=baseline, allowed_delta=0.05).decision == "reject"
    assert decide_gate(stable, gate="held_out", baseline=baseline, allowed_delta=0.05).decision == "accept"


def test_held_out_comparison_is_inconclusive_when_baseline_is_invalid() -> None:
    current = [{"trial_id": "trial-1", "status": "complete", "scores": [{"key": "quality", "score": 0.9, "threshold": 0.8}], "errors": []}]
    baseline = [{"trial_id": "trial-1", "status": "inconclusive", "scores": [], "errors": [{"category": "provider_failure"}]}]

    assert decide_gate(current, gate="held_out", baseline=baseline).decision == "inconclusive"


def test_cli_lists_cases_without_running_or_writing_artifacts(tmp_path: Path) -> None:
    suite = tmp_path / "suite.yaml"
    suite.write_text(json.dumps({"cases": [{"id": "case-a", "split": "held_in", "tags": ["smoke"]}]}), encoding="utf-8")

    result = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-eval"), "list", "--suite", str(suite)],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == [{"id": "case-a", "split": "held_in", "tags": ["smoke"]}]
    assert list(tmp_path.iterdir()) == [suite]


def test_diagnostic_artifacts_are_compact_and_opt_in(tmp_path: Path) -> None:
    artifact = project_trial_artifact(complete_trial(), [{"key": "quality", "score": 0.9}])

    run_directory = write_diagnostic_artifacts(tmp_path, [artifact])

    assert sorted(path.name for path in run_directory.iterdir()) == ["aggregate.json", "raw.json"]
    assert json.loads((run_directory / "aggregate.json").read_text(encoding="utf-8")) == {
        "version": 1,
        "trial_count": 1,
        "complete_count": 1,
        "inconclusive_count": 0,
    }
