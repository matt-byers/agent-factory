from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.engineering_handoff import digest
from agent_creation.eval_compound_learnings import (
    EvalCompoundLearningError,
    record_eval_loop_learning,
    validate_eval_loop_learning,
)
from agent_creation.lifecycle import LifecycleError, advance, load_state


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def setup_learning(root: Path, decision: str, *, split: str = "held_out") -> str:
    run_path = root / f"agent-lifecycle/evals/candidate-{split}.json"
    write_json(run_path, {"version": 1, "status": "complete", "split": split})
    decision_path = root / f"agent-lifecycle/evals/{split.replace('_', '-')}-decision.yaml"
    write_json(
        decision_path,
        {
            "version": 1,
            "status": "complete",
            "split": split,
            "decision": decision,
            "owner": "target_agent",
            "reason": f"Fixture {decision} decision.",
            "source": {"path": str(run_path.relative_to(root)), "sha256": digest(run_path)},
            "comparison": {
                "quality": 0.8,
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
            "stage": "learning",
            "status": "active",
            "engineering_loop": "included",
            "artifact_fingerprints": {},
            "receipt": {"sha256": "a" * 64},
            "engineering_attempt": None,
            "baseline_evaluation": None,
        },
    )
    return f"{run_path.relative_to(root)}#result"


def write(root: Path, relative: str, content: str = "updated\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def update(category: str, path: str, evidence_ref: str) -> dict:
    return {
        "id": f"improve-{category.replace('_', '-')}",
        "category": category,
        "summary": f"Improve the {category.replace('_', ' ')} contract.",
        "evidence_refs": [evidence_ref],
        "changed_paths": [path],
    }


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_records_evidence_supported_learning_and_returns_operational(
    tmp_path: Path, decision: str
) -> None:
    evidence_ref = setup_learning(tmp_path, decision)
    changed = "agent-lifecycle/evals/suite.yaml"
    write(tmp_path, changed)

    result = record_eval_loop_learning(
        tmp_path,
        [update("eval_case", changed, evidence_ref)],
    )

    artifact = result["learning"]
    assert artifact["attempt_decision"] == decision
    assert artifact["outcome"] == "updated"
    assert artifact["improvements"][0]["category"] == "eval_case"
    assert artifact["improvements"][0]["evidence"][0]["sha256"] == digest(
        tmp_path / "agent-lifecycle/evals/candidate-held_out.json"
    )
    assert artifact["improvements"][0]["changes"][0] == {
        "path": changed,
        "sha256": digest(tmp_path / changed),
    }
    assert result["lifecycle"]["stage"] == "operational"
    assert result["lifecycle"]["status"] == "complete"
    assert load_state(tmp_path)["artifact_fingerprints"]["learning"]
    assert validate_eval_loop_learning(tmp_path) == []


@pytest.mark.parametrize(
    "category,path",
    [
        ("eval_case", "agent-lifecycle/evals/suite.yaml"),
        ("simulated_user", "src/agent_creation/simulated_user.py"),
        ("rubric", "src/agent_creation/eval_design.py"),
        ("evidence", "src/agent_creation/production_evidence.py"),
        ("provider", "src/agent_creation/eval_providers.py"),
        ("comparison_gate", "src/agent_creation/validation_gates.py"),
        ("operator_guidance", ".claude/skills/eval-agent/SKILL.md"),
    ],
)
def test_all_eval_loop_categories_have_bounded_surfaces(
    tmp_path: Path, category: str, path: str
) -> None:
    evidence_ref = setup_learning(tmp_path, "rejected")
    write(tmp_path, path)

    result = record_eval_loop_learning(tmp_path, [update(category, path, evidence_ref)])

    assert result["learning"]["improvements"][0]["category"] == category
    assert result["lifecycle"]["stage"] == "operational"


def test_no_op_is_recorded_and_closes_the_lifecycle(tmp_path: Path) -> None:
    setup_learning(tmp_path, "accepted")

    result = record_eval_loop_learning(
        tmp_path,
        [],
        no_op_reason="The attempt exposed no evidence-supported eval-loop weakness.",
    )

    assert result["learning"]["outcome"] == "no_op"
    assert result["learning"]["improvements"] == []
    assert result["lifecycle"]["stage"] == "operational"


@pytest.mark.parametrize(
    "category,path",
    [
        ("eval_case", "agent/prompts/system.md"),
        ("operator_guidance", ".claude/skills/agent-build-loop/SKILL.md"),
        ("operator_guidance", ".claude/skills/spec-plan/SKILL.md"),
        ("evidence", "src/application/database.py"),
        ("provider", "src/agent_creation/eval_providers.py.bak"),
    ],
)
def test_rejects_target_agent_build_loop_and_other_out_of_scope_edits(
    tmp_path: Path, category: str, path: str
) -> None:
    evidence_ref = setup_learning(tmp_path, "rejected")
    write(tmp_path, path)

    with pytest.raises(EvalCompoundLearningError, match="outside the .* scope"):
        record_eval_loop_learning(tmp_path, [update(category, path, evidence_ref)])

    assert not (tmp_path / "agent-lifecycle/evidence/eval-loop-learning.yaml").exists()
    assert load_state(tmp_path)["stage"] == "learning"


def test_rejects_missing_or_stale_evidence_and_unsupported_decisions(tmp_path: Path) -> None:
    evidence_ref = setup_learning(tmp_path, "rejected")
    changed = "agent-lifecycle/evals/suite.yaml"
    write(tmp_path, changed)
    (tmp_path / "agent-lifecycle/evals/candidate-held_out.json").write_text(
        "changed\n", encoding="utf-8"
    )

    with pytest.raises(EvalCompoundLearningError, match="decision source changed"):
        record_eval_loop_learning(tmp_path, [update("eval_case", changed, evidence_ref)])

    setup_learning(tmp_path, "inconclusive")
    with pytest.raises(EvalCompoundLearningError, match="accepted or rejected"):
        record_eval_loop_learning(tmp_path, [], no_op_reason="No conclusive attempt.")


def test_requires_evidence_and_rejects_category_path_mismatch(tmp_path: Path) -> None:
    evidence_ref = setup_learning(tmp_path, "rejected")
    changed = "src/agent_creation/eval_providers.py"
    write(tmp_path, changed)

    missing = update("provider", changed, evidence_ref)
    missing["evidence_refs"] = []
    with pytest.raises(EvalCompoundLearningError, match="evidence"):
        record_eval_loop_learning(tmp_path, [missing])

    with pytest.raises(EvalCompoundLearningError, match="outside the eval_case scope"):
        record_eval_loop_learning(tmp_path, [update("eval_case", changed, evidence_ref)])


def test_lifecycle_rejects_a_tampered_learning_artifact(tmp_path: Path) -> None:
    evidence_ref = setup_learning(tmp_path, "rejected")
    changed = "agent-lifecycle/evals/suite.yaml"
    write(tmp_path, changed)
    artifact_path = tmp_path / "agent-lifecycle/evidence/eval-loop-learning.yaml"
    write_json(
        artifact_path,
        {
            "version": 1,
            "status": "complete",
            "attempt_decision": "rejected",
            "decision": {
                "path": "agent-lifecycle/evals/held-out-decision.yaml",
                "sha256": "0" * 64,
            },
            "outcome": "updated",
            "improvements": [update("eval_case", changed, evidence_ref)],
            "no_op_reason": None,
        },
    )

    assert validate_eval_loop_learning(tmp_path)
    with pytest.raises(LifecycleError, match="eval-loop learning is invalid"):
        advance(tmp_path)
    assert load_state(tmp_path)["stage"] == "learning"


def test_skill_is_generic_and_enforces_the_runtime_contract() -> None:
    skill = (REPOSITORY_ROOT / ".claude/skills/eval-compound-learnings/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "record_eval_loop_learning" in skill
    assert "accepted or rejected" in skill
    assert "no-op" in skill
    assert "target agent" in skill
    assert "engineering-loop" in skill
    assert "Shop For Me" not in skill
