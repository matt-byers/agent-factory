from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.eval_design import (
    EvalDesignError,
    create_suite_artifacts,
    load_held_out_case,
    target_example,
    validate_suite,
)
from agent_creation.lifecycle import LifecycleError, Stage, validate_stage_artifacts


def case(
    identifier: str,
    *tags: str,
    split: str = "held_in",
) -> dict:
    return {
        "id": identifier,
        "split": split,
        "tags": list(tags),
        "trials": 2,
        "seeds": [11, 29],
        "input": {"initial_user_message": f"Public request for {identifier}"},
        "simulated_user": {
            "persona": "A concise user with information they reveal progressively.",
            "private_truth": [
                {
                    "id": "account-tier",
                    "value": "The account is enterprise.",
                    "reveal_on": ["account", "plan"],
                }
            ],
            "disclosure_policy": {
                "mode": "progressive",
                "max_facts_per_turn": 1,
                "fallback": "next_unrevealed",
            },
            "termination": {
                "success_condition": "The requested task is completed or safely refused.",
                "max_turns": 6,
                "stall_turns": 2,
            },
        },
        "expected": {
            "outcome": "Resolve the public request without inventing private facts.",
            "trajectory": {
                "required_tools": ["lookup_record"],
                "forbidden_tools": ["delete_record"],
                "ordered_tools": [],
            },
        },
        "graders": {
            "deterministic": [
                {
                    "id": "no-delete",
                    "check": "tool_not_called",
                    "arguments": {"tool": "delete_record"},
                }
            ],
            "rubrics": [
                {
                    "id": "resolution-quality",
                    "criterion": "The final response directly resolves the stated request.",
                    "evidence": "final_output",
                    "threshold": 0.8,
                }
            ],
        },
    }


def complete_suite() -> dict:
    return {
        "version": 1,
        "status": "complete",
        "name": "fixture-agent-evals",
        "metrics": [
            {
                "id": "hard-pass-rate",
                "name": "Deterministic invariant pass rate",
                "kind": "deterministic",
                "aggregation": "pass_rate",
                "threshold": 1.0,
            },
            {
                "id": "quality-score",
                "name": "Narrow rubric quality",
                "kind": "qualitative",
                "aggregation": "mean",
                "threshold": 0.8,
            },
            {
                "id": "turn-count",
                "name": "Conversation turns",
                "kind": "operational",
                "aggregation": "mean",
                "threshold": 6,
            },
        ],
        "cases": [
            case("smoke-positive", "smoke", "positive", "representative"),
            case("core-capability", "capability", "positive", "representative"),
            case("known-regression", "regression", "positive"),
            case("boundary-edge", "edge", "negative"),
            case("hostile-input", "adversarial", "negative"),
            case(
                "unseen-held-out",
                "held-out",
                "edge",
                "adversarial",
                split="held_out",
            ),
        ],
    }


def test_complete_suite_has_required_coverage_graders_metrics_and_trials() -> None:
    assert validate_suite(complete_suite()) == []


@pytest.mark.parametrize(
    "mutation,diagnostic",
    [
        (lambda suite: suite["cases"][0].pop("expected"), "expected is required"),
        (lambda suite: suite["cases"][0]["graders"].update(deterministic=[]), "deterministic grader"),
        (lambda suite: suite["cases"][0].update(seeds=[11]), "one seed per trial"),
        (lambda suite: suite["metrics"][0].update(threshold=1.1), "threshold"),
    ],
)
def test_invalid_case_and_metric_contracts_return_actionable_errors(mutation, diagnostic: str) -> None:
    suite = complete_suite()
    mutation(suite)

    assert diagnostic in "; ".join(validate_suite(suite))


@pytest.mark.parametrize(
    "tag",
    ["smoke", "capability", "regression", "edge", "positive", "negative", "representative", "adversarial"],
)
def test_required_coverage_cannot_be_omitted(tag: str) -> None:
    suite = complete_suite()
    for item in suite["cases"]:
        item["tags"] = [value for value in item["tags"] if value != tag]

    assert f"coverage tag is required: {tag}" in validate_suite(suite)


def test_held_out_case_is_sealed_outside_public_suite(tmp_path: Path) -> None:
    paths = create_suite_artifacts(complete_suite(), tmp_path)
    public_suite = json.loads(paths["suite"].read_text(encoding="utf-8"))
    held_out = next(item for item in public_suite["cases"] if item["split"] == "held_out")
    sealed_path = tmp_path / held_out["sealed_ref"]

    assert "input" not in held_out
    assert "simulated_user" not in held_out
    assert "expected" not in held_out
    assert sealed_path.is_file()
    assert held_out["sha256"] == hashlib.sha256(sealed_path.read_bytes()).hexdigest()
    with pytest.raises(EvalDesignError, match="held-out gate"):
        load_held_out_case(tmp_path, held_out, release=False)
    assert load_held_out_case(tmp_path, held_out, release=True)["id"] == "unseen-held-out"


def test_held_out_loader_rejects_manifest_path_outside_sealed_directory(tmp_path: Path) -> None:
    manifest = {
        "id": "unseen-held-out",
        "split": "held_out",
        "tags": ["held-out"],
        "sealed_ref": "outside.json",
        "sha256": "0" * 64,
    }

    with pytest.raises(EvalDesignError, match="sealed held-out directory"):
        load_held_out_case(tmp_path, manifest, release=True)


def test_target_example_never_contains_private_truth_or_reference_answers() -> None:
    selected = complete_suite()["cases"][0]

    payload = json.dumps(target_example(selected), sort_keys=True)

    assert "Public request" in payload
    assert "enterprise" not in payload
    assert "expected" not in payload
    assert "grader" not in payload


def test_cli_validates_generated_suite(tmp_path: Path) -> None:
    paths = create_suite_artifacts(complete_suite(), tmp_path)

    result = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/agent-eval-designer"), "validate", "--suite", str(paths["suite"])],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"errors": [], "status": "valid"}


def test_skill_and_templates_define_the_eval_design_workflow() -> None:
    skill = (REPOSITORY_ROOT / ".claude/skills/agent-eval-designer/SKILL.md").read_text(encoding="utf-8")
    case_template = REPOSITORY_ROOT / ".claude/skills/agent-eval-designer/assets/case-template.yaml"
    suite_template = REPOSITORY_ROOT / ".claude/skills/agent-eval-designer/assets/suite-template.yaml"

    assert "scripts/agent-eval-designer" in skill
    assert "held-out" in skill
    assert "agent-lifecycle/agent-definition" in skill
    assert case_template.is_file()
    assert suite_template.is_file()


def test_lifecycle_rejects_pending_eval_suite() -> None:
    stage = Stage("eval_design", "/agent-eval-designer", ("agent-lifecycle/evals/suite.yaml",))

    with pytest.raises(LifecycleError, match="suite.status must be complete"):
        validate_stage_artifacts(REPOSITORY_ROOT, {"lifecycle": "first-build"}, stage)
