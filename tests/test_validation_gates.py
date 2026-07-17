from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.engineering_handoff import digest
from agent_creation.eval_design import create_suite_artifacts
from agent_creation.lifecycle import advance, load_state
from agent_creation.validation_gates import (
    ValidationGateError,
    evaluate_held_in,
    evaluate_held_out,
    load_released_held_out_cases,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def case(identifier: str, split: str) -> dict:
    return {
        "id": identifier,
        "split": split,
        "tags": [
            "smoke",
            "capability",
            "regression",
            "edge",
            "positive",
            "negative",
            "representative",
            "adversarial",
            *( ["held-out"] if split == "held_out" else []),
        ],
        "trials": 2,
        "seeds": [11, 22],
        "input": {"initial_user_message": "Resolve this request."},
        "simulated_user": {
            "persona": "A user with a bounded request.",
            "private_truth": [{"id": "fact", "value": "Known fact", "reveal_on": ["fact"]}],
            "disclosure_policy": {
                "mode": "progressive",
                "max_facts_per_turn": 1,
                "fallback": "next_unrevealed",
            },
            "termination": {
                "success_condition": "The request is resolved.",
                "max_turns": 3,
                "stall_turns": 1,
            },
        },
        "expected": {
            "outcome": "Resolve the request.",
            "trajectory": {
                "required_tools": [],
                "forbidden_tools": [],
                "ordered_tools": [],
            },
        },
        "graders": {
            "deterministic": [{"id": "hard-pass", "check": "no_error", "arguments": {}}],
            "rubrics": [
                {
                    "id": "quality",
                    "criterion": "The answer resolves the request.",
                    "evidence": "final_output",
                    "threshold": 0.75,
                }
            ],
        },
    }


def setup_validation(root: Path, *, stage: str = "held_in", architecture_changed: bool = False) -> None:
    suite = {
        "version": 1,
        "status": "complete",
        "name": "improvement-validation",
        "metrics": [
            {
                "id": "hard-pass-rate",
                "name": "Hard invariant pass rate",
                "kind": "deterministic",
                "aggregation": "pass_rate",
                "threshold": 1.0,
            },
            {
                "id": "quality-score",
                "name": "Quality",
                "kind": "qualitative",
                "aggregation": "mean",
                "threshold": 0.75,
            },
            {
                "id": "latency",
                "name": "Latency",
                "kind": "operational",
                "aggregation": "mean",
                "threshold": 500,
            },
        ],
        "cases": [case("held-in-core", "held_in"), case("held-out-regression", "held_out")],
    }
    create_suite_artifacts(suite, root)
    prompt = root / "agent/prompts/system.md"
    tool = root / "agent/tools/lookup.py"
    prompt.parent.mkdir(parents=True)
    tool.parent.mkdir(parents=True)
    prompt.write_text("Improved prompt.\n", encoding="utf-8")
    tool.write_text("TOOL_NAME = 'lookup'\n", encoding="utf-8")
    write_json(
        root / "agent-lifecycle/evals/agent-baseline.yaml",
        {
            "version": 1,
            "status": "operational",
            "target_command": ["python", "agent/run.py"],
            "suite_sha256": digest(root / "agent-lifecycle/evals/suite.yaml"),
            "run_path": "agent-lifecycle/evals/original-baseline.json",
            "run_sha256": "a" * 64,
            "prompt_sha256": {"agent/prompts/system.md": "b" * 64},
            "toolset_sha256": {"agent/tools/lookup.py": "c" * 64},
            "comparison": {
                "quality": 0.9,
                "hard_invariant_pass_rate": 1.0,
                "latency_ms": 100.0,
                "cost": 0.1,
                "trial_count": 2,
            },
        },
    )
    write_json(
        root / "agent-lifecycle/state.yaml",
        {
            "version": 1,
            "lifecycle": "improvement",
            "stage": stage,
            "status": "active",
            "engineering_loop": "included",
            "artifact_fingerprints": {},
            "receipt": {
                "path": "agent-lifecycle/receipts/improvement.json",
                "sha256": "d" * 64,
                "handoff_id": "improvement-001",
                "architecture_changed": architecture_changed,
                "manifest_path": "agent-lifecycle/handoffs/improvement-001/manifest.json",
                "manifest_sha256": "e" * 64,
                "architecture_before_sha256": {},
            },
            "engineering_attempt": None,
            "baseline_evaluation": None,
        },
    )


def trial(case_id: str, index: int, *, quality: float = 0.92, latency: float = 105, cost: float = 0.105) -> dict:
    return {
        "trial_id": f"{case_id}:{index}",
        "status": "complete",
        "assistant_messages": [{"role": "assistant", "content": "Resolved."}],
        "tool_calls": [],
        "tool_results": [],
        "state_snapshots": [],
        "outcome": {"resolved": True},
        "metrics": {"latency_ms": latency, "tokens": 20, "cost": cost},
        "scores": [
            {"key": "hard-pass", "score": 1.0, "threshold": 1.0},
            {"key": "quality", "score": quality, "threshold": 0.75},
        ],
        "trace_refs": [],
        "errors": [],
    }


def run(root: Path, split: str, **trial_values: float) -> dict:
    case_id = "held-in-core" if split == "held_in" else "held-out-regression"
    return {
        "version": 1,
        "status": "complete",
        "split": split,
        "suite_sha256": digest(root / "agent-lifecycle/evals/suite.yaml"),
        "target_command": ["python", "agent/run.py"],
        "cases": [
            {
                "case_id": case_id,
                "trials": [trial(case_id, index, **trial_values) for index in range(2)],
            }
        ],
    }


def write_run(root: Path, name: str, payload: dict) -> Path:
    path = root / f"agent-lifecycle/evals/{name}.json"
    write_json(path, payload)
    return path


def release_held_out(root: Path) -> None:
    held_in = write_run(root, "candidate-held-in", run(root, "held_in"))
    assert evaluate_held_in(root, held_in)["decision"] == "accepted"
    assert advance(root)["stage"] == "held_out"


def test_held_out_is_sealed_until_complete_held_in_passes(tmp_path: Path) -> None:
    setup_validation(tmp_path)

    with pytest.raises(ValidationGateError, match="not released"):
        load_released_held_out_cases(tmp_path)
    with pytest.raises(ValidationGateError, match="held-out validation"):
        evaluate_held_out(tmp_path, write_run(tmp_path, "early-held-out", run(tmp_path, "held_out")))

    release_held_out(tmp_path)

    released = load_released_held_out_cases(tmp_path)
    assert [item["id"] for item in released] == ["held-out-regression"]
    assert released[0]["input"]["initial_user_message"] == "Resolve this request."


def test_accepted_candidate_compares_all_dimensions_and_replaces_baseline_once(
    tmp_path: Path,
) -> None:
    setup_validation(tmp_path)
    original = (tmp_path / "agent-lifecycle/evals/agent-baseline.yaml").read_bytes()
    release_held_out(tmp_path)
    held_out = write_run(tmp_path, "candidate-held-out", run(tmp_path, "held_out"))

    first = evaluate_held_out(tmp_path, held_out)
    promoted = (tmp_path / "agent-lifecycle/evals/agent-baseline.yaml").read_bytes()
    second = evaluate_held_out(tmp_path, held_out)
    baseline = json.loads(promoted)

    assert first == second
    assert first["decision"] == "accepted"
    assert set(first["comparison"]) >= {
        "quality",
        "hard_invariant_pass_rate",
        "latency_ms",
        "cost",
    }
    assert promoted != original
    assert (tmp_path / "agent-lifecycle/evals/agent-baseline.yaml").read_bytes() == promoted
    assert baseline["comparison"] == first["comparison"]
    assert baseline["validation"]["held_out_run_sha256"] == digest(held_out)
    assert advance(tmp_path)["stage"] == "learning"


@pytest.mark.parametrize("mutation,reason", [
    (lambda result: result["cases"].clear(), "required held-in case is missing"),
    (lambda result: result["cases"][0]["trials"].pop(), "incomplete trial coverage"),
    (lambda result: result.update(status="incomplete"), "run status"),
])
def test_missing_cases_results_or_trials_are_inconclusive(
    tmp_path: Path, mutation, reason: str
) -> None:
    setup_validation(tmp_path)
    artifact = run(tmp_path, "held_in")
    mutation(artifact)

    decision = evaluate_held_in(tmp_path, write_run(tmp_path, "incomplete-held-in", artifact))

    assert decision["decision"] == "inconclusive"
    assert reason in decision["reason"]
    assert not (tmp_path / "agent-lifecycle/evals/held-out-release.json").exists()
    assert load_state(tmp_path)["stage"] == "held_in"


def test_provider_failure_is_inconclusive_without_quality_verdict(tmp_path: Path) -> None:
    setup_validation(tmp_path)
    artifact = run(tmp_path, "held_in")
    failed = artifact["cases"][0]["trials"][0]
    failed["status"] = "inconclusive"
    failed["errors"] = [
        {"category": "provider_failure", "stage": "simulation", "message": "unavailable"}
    ]

    decision = evaluate_held_in(tmp_path, write_run(tmp_path, "provider-failure", artifact))

    assert decision["decision"] == "inconclusive"
    assert decision["owner"] == "provider"
    assert not (tmp_path / "agent-lifecycle/evals/held-out-release.json").exists()


def test_missing_accepted_baseline_is_inconclusive_at_held_in(tmp_path: Path) -> None:
    setup_validation(tmp_path)
    (tmp_path / "agent-lifecycle/evals/agent-baseline.yaml").unlink()

    decision = evaluate_held_in(
        tmp_path,
        write_run(tmp_path, "missing-baseline-held-in", run(tmp_path, "held_in")),
    )

    assert decision["decision"] == "inconclusive"
    assert decision["owner"] == "harness"
    assert "accepted agent baseline" in decision["reason"]


def test_repeating_accepted_held_in_recreates_only_its_release(tmp_path: Path) -> None:
    setup_validation(tmp_path)
    run_path = write_run(tmp_path, "recover-release-held-in", run(tmp_path, "held_in"))
    decision = evaluate_held_in(tmp_path, run_path)
    release = tmp_path / "agent-lifecycle/evals/held-out-release.json"
    release.unlink()

    repeated = evaluate_held_in(tmp_path, run_path)

    assert repeated == decision
    assert release.is_file()


def test_hard_invariant_failure_rejects_without_releasing_held_out(tmp_path: Path) -> None:
    setup_validation(tmp_path)
    artifact = run(tmp_path, "held_in")
    artifact["cases"][0]["trials"][0]["scores"][0]["score"] = 0.0

    decision = evaluate_held_in(tmp_path, write_run(tmp_path, "hard-failure", artifact))

    assert decision["decision"] == "rejected"
    assert decision["owner"] == "target_agent"
    assert not (tmp_path / "agent-lifecycle/evals/held-out-release.json").exists()
    assert load_state(tmp_path)["stage"] == "learning"


@pytest.mark.parametrize(
    "trial_values,reason",
    [
        ({"quality": 0.8}, "quality regression"),
        ({"latency": 121}, "latency regression"),
        ({"cost": 0.121}, "cost regression"),
    ],
)
def test_held_out_regressions_reject_without_replacing_baseline(
    tmp_path: Path, trial_values: dict[str, float], reason: str
) -> None:
    setup_validation(tmp_path)
    release_held_out(tmp_path)
    baseline_path = tmp_path / "agent-lifecycle/evals/agent-baseline.yaml"
    original = baseline_path.read_bytes()

    decision = evaluate_held_out(
        tmp_path,
        write_run(tmp_path, "regressed-held-out", run(tmp_path, "held_out", **trial_values)),
    )

    assert decision["decision"] == "rejected"
    assert reason in decision["reason"]
    assert baseline_path.read_bytes() == original
    assert advance(tmp_path)["stage"] == "learning"


def test_missing_baseline_comparison_keeps_held_out_inconclusive(tmp_path: Path) -> None:
    setup_validation(tmp_path)
    release_held_out(tmp_path)
    baseline_path = tmp_path / "agent-lifecycle/evals/agent-baseline.yaml"
    baseline = json.loads(baseline_path.read_text())
    del baseline["comparison"]
    write_json(baseline_path, baseline)

    decision = evaluate_held_out(
        tmp_path,
        write_run(tmp_path, "no-baseline-held-out", run(tmp_path, "held_out")),
    )

    assert decision["decision"] == "inconclusive"
    assert "baseline comparison" in decision["reason"]
    assert load_state(tmp_path)["stage"] == "held_out"


def test_non_finite_comparison_tolerance_fails_closed(tmp_path: Path) -> None:
    setup_validation(tmp_path)
    release_held_out(tmp_path)

    with pytest.raises(ValidationGateError, match="tolerances"):
        evaluate_held_out(
            tmp_path,
            write_run(tmp_path, "invalid-policy-held-out", run(tmp_path, "held_out")),
            max_cost_ratio=float("nan"),
        )


def test_validation_requires_improvement_receipt_and_architecture_reconciliation(
    tmp_path: Path,
) -> None:
    setup_validation(tmp_path, stage="architecture_reconciliation", architecture_changed=True)

    with pytest.raises(ValidationGateError, match="held-in validation"):
        evaluate_held_in(
            tmp_path,
            write_run(tmp_path, "blocked-held-in", run(tmp_path, "held_in")),
        )

    state = json.loads((tmp_path / "agent-lifecycle/state.yaml").read_text())
    state.update(lifecycle="first-build", stage="held_in")
    write_json(tmp_path / "agent-lifecycle/state.yaml", state)
    with pytest.raises(ValidationGateError, match="target-agent improvement"):
        evaluate_held_in(
            tmp_path,
            write_run(tmp_path, "wrong-lifecycle", run(tmp_path, "held_in")),
        )


def test_eval_agent_exposes_native_validation_commands_and_contract() -> None:
    result = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-eval"), "--help"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    skill = (REPOSITORY_ROOT / ".claude/skills/eval-agent/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert result.returncode == 0, result.stderr
    assert "held-in" in result.stdout and "held-out" in result.stdout
    assert "hard invariants, latency, and cost" in skill
    assert "replaces the baseline atomically" in skill
