from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.baseline_evaluation import (
    BaselineEvaluationError,
    evaluate_baseline,
    validate_baseline_decision,
)
from agent_creation.engineering_handoff import digest
from agent_creation.lifecycle import advance, load_state, status


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def eval_case(identifier: str, split: str) -> dict:
    tags = [
        "smoke",
        "capability",
        "regression",
        "edge",
        "positive",
        "negative",
        "representative",
        "adversarial",
    ]
    if split == "held_out":
        tags.append("held-out")
    return {
        "id": identifier,
        "split": split,
        "tags": tags,
        "trials": 1,
        "seeds": [17],
        "input": {"initial_user_message": "Resolve this request."},
        "simulated_user": {
            "persona": "A support customer.",
            "private_truth": [{"id": "fact", "value": "Known fact", "reveal_on": ["fact"]}],
            "disclosure_policy": {
                "mode": "progressive",
                "max_facts_per_turn": 1,
                "fallback": "next_unrevealed",
            },
            "termination": {"success_condition": "Resolved", "max_turns": 3, "stall_turns": 1},
        },
        "expected": {
            "outcome": "Resolve the request.",
            "trajectory": {"required_tools": [], "forbidden_tools": [], "ordered_tools": []},
        },
        "graders": {
            "deterministic": [{"id": "no-error", "check": "no_error", "arguments": {}}],
            "rubrics": [
                {
                    "id": "answer-quality",
                    "criterion": "The answer resolves the request.",
                    "evidence": "final_output",
                    "threshold": 0.8,
                }
            ],
        },
    }


def setup_baseline(root: Path) -> Path:
    suite = {
        "version": 1,
        "status": "complete",
        "name": "baseline-suite",
        "metrics": [
            {
                "id": "hard-pass",
                "name": "Hard pass",
                "kind": "deterministic",
                "aggregation": "pass_rate",
                "threshold": 1.0,
            },
            {
                "id": "quality",
                "name": "Quality",
                "kind": "qualitative",
                "aggregation": "mean",
                "threshold": 0.8,
            },
            {
                "id": "turns",
                "name": "Turns",
                "kind": "operational",
                "aggregation": "mean",
                "threshold": 3,
            },
        ],
        "cases": [
            eval_case("core-resolution", "held_in"),
            eval_case("boundary-resolution", "held_in"),
            eval_case("sealed-regression", "held_out"),
        ],
    }
    suite_path = root / "agent-lifecycle/evals/suite.yaml"
    write_json(suite_path, suite)
    write_json(
        root / "agent-lifecycle/state.yaml",
        {
            "version": 1,
            "lifecycle": "first-build",
            "stage": "baseline",
            "status": "active",
            "engineering_loop": "included",
            "artifact_fingerprints": {},
            "receipt": {"path": "agent-lifecycle/receipts/completed.json", "sha256": "a" * 64},
            "engineering_attempt": None,
            "baseline_evaluation": None,
        },
    )
    prompt = root / "agent/prompts/system.md"
    tool = root / "agent/tools/retrieve_policy.py"
    prompt.parent.mkdir(parents=True)
    tool.parent.mkdir(parents=True)
    prompt.write_text("Answer using grounded evidence.\n", encoding="utf-8")
    tool.write_text("TOOL_NAME = 'retrieve-policy'\n", encoding="utf-8")
    return suite_path


def passing_trial(case_id: str) -> dict:
    return {
        "trial_id": f"{case_id}:0",
        "status": "complete",
        "assistant_messages": [{"role": "assistant", "content": "Resolved."}],
        "tool_calls": [],
        "tool_results": [],
        "state_snapshots": [],
        "outcome": {"resolved": True},
        "metrics": {"latency_ms": 10, "tokens": 20, "cost": 0.01},
        "scores": [
            {"key": "no-error", "score": 1.0, "threshold": 1.0},
            {"key": "answer-quality", "score": 0.9, "threshold": 0.8},
        ],
        "trace_refs": [],
        "errors": [],
    }


def run_artifact(root: Path) -> dict:
    suite = root / "agent-lifecycle/evals/suite.yaml"
    return {
        "version": 1,
        "status": "complete",
        "split": "held_in",
        "suite_sha256": digest(suite),
        "target_command": ["python", "agent/run.py"],
        "metrics": [
            {"id": "hard-pass", "value": 1.0},
            {"id": "quality", "value": 0.9},
            {"id": "turns", "value": 2},
        ],
        "cases": [
            {"case_id": identifier, "trials": [passing_trial(identifier)]}
            for identifier in ("core-resolution", "boundary-resolution")
        ],
    }


def evaluate(root: Path, artifact: dict) -> dict:
    path = root / "native-held-in-run.json"
    write_json(path, artifact)
    return evaluate_baseline(root, path, ["python", "agent/run.py"])


def test_complete_passing_held_in_run_records_prompt_toolset_and_enters_operational(
    tmp_path: Path,
) -> None:
    suite = setup_baseline(tmp_path)

    decision = evaluate(tmp_path, run_artifact(tmp_path))
    result = advance(tmp_path)
    baseline_path = tmp_path / "agent-lifecycle/evals/agent-baseline.yaml"
    baseline = json.loads(baseline_path.read_text())

    assert decision["decision"] == "accepted"
    assert validate_baseline_decision(tmp_path) == []
    assert result["lifecycle"] == "first-build"
    assert result["stage"] == "operational"
    assert result["status"] == "complete"
    assert result["next"] == "Lifecycle complete"
    assert result["baseline_evaluation"]["decision"] == "accepted"
    assert baseline["status"] == "operational"
    assert baseline["suite_sha256"] == hashlib.sha256(suite.read_bytes()).hexdigest()
    assert baseline["target_command"] == ["python", "agent/run.py"]
    assert baseline["prompt_sha256"] == {
        "agent/prompts/system.md": digest(tmp_path / "agent/prompts/system.md")
    }
    assert baseline["toolset_sha256"] == {
        "agent/tools/retrieve_policy.py": digest(tmp_path / "agent/tools/retrieve_policy.py")
    }
    assert not (tmp_path / "agent-lifecycle/evals/baseline-diagnostic.json").exists()


def test_operational_prompt_or_toolset_drift_reopens_baseline_validation(tmp_path: Path) -> None:
    setup_baseline(tmp_path)
    evaluate(tmp_path, run_artifact(tmp_path))
    advance(tmp_path)
    prompt = tmp_path / "agent/prompts/system.md"
    prompt.write_text("Changed after baseline.\n", encoding="utf-8")

    result = status(tmp_path)

    assert result["stage"] == "baseline"
    assert result["next"] == "/eval-agent"
    assert result["changed"] == ["agent/prompts/system.md"]


def test_agent_quality_failure_routes_to_improvement_with_one_diagnostic(tmp_path: Path) -> None:
    setup_baseline(tmp_path)
    artifact = run_artifact(tmp_path)
    artifact["cases"][0]["trials"][0]["scores"][1]["score"] = 0.4

    decision = evaluate(tmp_path, artifact)
    state = load_state(tmp_path)
    diagnostic = json.loads(
        (tmp_path / "agent-lifecycle/evals/baseline-diagnostic.json").read_text()
    )

    assert decision["decision"] == "rejected"
    assert decision["owner"] == "target_agent"
    assert decision["route"] == "/agent-self-improvement"
    assert state["stage"] == "baseline"
    assert state["baseline_evaluation"]["route"] == "/agent-self-improvement"
    assert diagnostic["issues"][0]["case_id"] == "core-resolution"
    assert len(list((tmp_path / "agent-lifecycle/evals").glob("*diagnostic*"))) == 1
    assert not (tmp_path / "agent-lifecycle/evals/agent-baseline.yaml").exists()


@pytest.mark.parametrize(
    ("category", "owner", "route"),
    [
        ("eval_failure", "eval", "/eval-agent repair-eval"),
        ("provider_failure", "provider", "/eval-agent repair-provider"),
        ("data_failure", "data", "/agent-eval-designer"),
        ("harness_failure", "harness", "/eval-agent repair-harness"),
    ],
)
def test_non_agent_failures_route_to_the_owning_repair_path(
    tmp_path: Path, category: str, owner: str, route: str
) -> None:
    setup_baseline(tmp_path)
    artifact = run_artifact(tmp_path)
    trial = artifact["cases"][0]["trials"][0]
    trial["status"] = "inconclusive"
    trial["errors"] = [{"category": category, "stage": "evaluation", "message": "fixture failure"}]

    decision = evaluate(tmp_path, artifact)

    assert decision["decision"] == "inconclusive"
    assert decision["owner"] == owner
    assert decision["route"] == route
    with pytest.raises(Exception, match="baseline evaluation did not pass"):
        advance(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "owner", "reason"),
    [
        (lambda artifact: artifact.update(status="incomplete"), "harness", "run status"),
        (lambda artifact: artifact["cases"].pop(), "data", "held-in case"),
        (lambda artifact: artifact["cases"][0]["trials"][0]["scores"].pop(), "eval", "grader score"),
        (lambda artifact: artifact["metrics"].pop(), "eval", "aggregate metric"),
        (
            lambda artifact: artifact["cases"][0]["trials"][0].pop("metrics"),
            "harness",
            "comparison artifact",
        ),
        (lambda artifact: artifact["metrics"][0].update(value=float("nan")), "eval", "not finite"),
        (lambda artifact: artifact.update(suite_sha256="0" * 64), "data", "suite"),
    ],
)
def test_incomplete_or_stale_results_never_create_an_operational_baseline(
    tmp_path: Path, mutation, owner: str, reason: str
) -> None:
    setup_baseline(tmp_path)
    artifact = run_artifact(tmp_path)
    mutation(artifact)

    decision = evaluate(tmp_path, artifact)

    assert decision["decision"] == "inconclusive"
    assert decision["owner"] == owner
    assert reason in decision["reason"]
    assert load_state(tmp_path)["stage"] == "baseline"
    assert not (tmp_path / "agent-lifecycle/evals/agent-baseline.yaml").exists()


def test_infrastructure_failure_takes_precedence_over_agent_failure(tmp_path: Path) -> None:
    setup_baseline(tmp_path)
    artifact = run_artifact(tmp_path)
    artifact["cases"][0]["trials"][0]["scores"][1]["score"] = 0.4
    second = artifact["cases"][1]["trials"][0]
    second["status"] = "inconclusive"
    second["errors"] = [
        {"category": "provider_failure", "stage": "simulation", "message": "rate limited"}
    ]

    decision = evaluate(tmp_path, artifact)

    assert decision["owner"] == "provider"
    assert decision["decision"] == "inconclusive"


def test_malformed_artifact_and_target_command_mismatch_fail_closed(tmp_path: Path) -> None:
    setup_baseline(tmp_path)
    path = tmp_path / "native-held-in-run.json"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(BaselineEvaluationError, match="must contain an object"):
        evaluate_baseline(tmp_path, path, ["python", "agent/run.py"])

    write_json(path, run_artifact(tmp_path))
    with pytest.raises(BaselineEvaluationError, match="target command"):
        evaluate_baseline(tmp_path, path, ["python", "other.py"])


def test_missing_suite_routes_to_data_repair_with_one_diagnostic(tmp_path: Path) -> None:
    suite = setup_baseline(tmp_path)
    artifact = run_artifact(tmp_path)
    suite.unlink()

    decision = evaluate(tmp_path, artifact)

    assert decision["decision"] == "inconclusive"
    assert decision["owner"] == "data"
    assert decision["route"] == "/agent-eval-designer"
    assert (tmp_path / "agent-lifecycle/evals/baseline-diagnostic.json").is_file()
