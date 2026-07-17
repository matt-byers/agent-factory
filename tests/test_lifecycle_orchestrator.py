from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.business_value import INPUT_FIELDS, calculate_model, render_markdown
from agent_creation.eval_design import create_suite_artifacts
from agent_creation.engineering_handoff import create_handoff, digest, route_manifest
from agent_creation.baseline_evaluation import evaluate_baseline
from agent_creation.validation_gates import evaluate_held_in, evaluate_held_out
from agent_creation.eval_compound_learnings import record_eval_loop_learning


COMMAND = REPOSITORY_ROOT / "scripts" / "agent-lifecycle"


def run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(COMMAND), "--root", str(root), *arguments],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def write(root: Path, relative: str, content: str = "fixture\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_goal_artifacts(root: Path) -> None:
    write(
        root,
        "agent-lifecycle/agent-definition/project-brief.md",
        """# Agent Project Brief

Status: complete

## Purpose
Fixture purpose.
## Target Users
Fixture users.
## User Problem
Fixture problem.
## Current Workflow
Fixture workflow.
## Agent Scope
Fixture scope.
## Accuracy, Latency, and Cost Priorities
Fixture priorities.
## Risks and Failure Cost
Fixture risk.
## Success Outcomes
- `fixture-outcome` (user): Fixture outcome.
""",
    )
    write(
        root,
        "agent-lifecycle/agent-definition/success-metrics.yaml",
        json.dumps(
            {
                "version": 1,
                "status": "complete",
                "outcomes": [
                    {
                        "id": "fixture-outcome",
                        "type": "user",
                        "description": "Fixture outcome",
                        "observation": "Fixture observation",
                    }
                ],
                "metrics": [
                    {
                        "id": "fixture-metric",
                        "name": "Fixture metric",
                        "outcome_ids": ["fixture-outcome"],
                        "direction": "increase",
                        "baseline": {"value": 1, "unit": "count", "source": "fixture"},
                        "target": {"value": 2, "unit": "count"},
                        "data_source": "fixture",
                        "owner": "fixture",
                        "cadence": "weekly",
                    }
                ],
            }
        ),
    )
    values = {
        "eligible_volume": 1000,
        "adoption_rate": 0.5,
        "baseline_success_rate": 0.5,
        "target_success_rate": 0.6,
        "attribution_rate": 1,
        "revenue_per_success": 10,
        "gross_margin_rate": 1,
        "minutes_saved_per_adopted_task": 0,
        "loaded_labor_cost_per_hour": 0,
        "error_rate_reduction": 0,
        "cost_per_error": 0,
        "loss_rate_reduction": 0,
        "loss_per_event": 0,
        "variable_run_cost_per_adopted_task": 0,
        "annual_fixed_cost": 0,
        "implementation_cost": 0,
    }
    scenario = {
        **values,
        "evidence": {
            field: {"assumption": "Fixture", "source": "Fixture", "owner": "Fixture"}
            for field in INPUT_FIELDS
        },
    }
    projection = calculate_model(
        {
            "version": 1,
            "currency": "USD",
            "economic_units": {
                "revenue": "gross profit",
                "time_savings": "labor capacity",
                "rework_avoidance": "rework cost",
                "loss_avoidance": "loss exposure",
            },
            "scenarios": {name: scenario for name in ("conservative", "base", "upside")},
        }
    )
    write(
        root,
        "agent-lifecycle/agent-definition/business-value-model.yaml",
        json.dumps(projection, indent=2, sort_keys=True) + "\n",
    )
    write(
        root,
        "agent-lifecycle/agent-definition/business-value-model.md",
        render_markdown(projection),
    )


def handoff_request(handoff_id: str, kind: str) -> dict:
    return {
        "version": 1,
        "handoff_id": handoff_id,
        "kind": kind,
        "approval_status": "approved",
        "editable_paths": [{"path": "agent/prompts/system.md", "surface": "prompts"}],
        "recommendations": [
            {
                "id": "fixture-change",
                "requirement_or_evidence": [
                    "agent-lifecycle/agent-definition/project-brief.md#purpose",
                    "agent-lifecycle/evals/suite.yaml#fixture-case",
                ],
                "likely_cause_or_design_need": "Fixture design need.",
                "proposed_change": "Update the fixture agent prompt.",
                "source_rationale": {
                    "summary": "Fixture source rationale.",
                    "references": [
                        "docs/references/agent-building-best-practices.md#tools",
                        "agent-lifecycle/architecture/decisions.md#decision",
                    ],
                },
                "expected_effect": {
                    "user": "Fixture user effect.",
                    "business": "Fixture business effect.",
                },
                "acceptance_eval_ids": ["fixture-case"],
            }
        ],
        "acceptance_gates": [
            {
                "id": "focused-tests",
                "kind": "focused_tests",
                "command": "pytest focused",
                "success_criteria": "Focused tests pass.",
            },
            {
                "id": "full-suite",
                "kind": "full_suite",
                "command": "pytest",
                "success_criteria": "Full suite passes.",
            },
            {
                "id": "acceptance-evals",
                "kind": "acceptance_evals",
                "eval_ids": ["fixture-case"],
                "success_criteria": "Acceptance eval passes.",
            },
            {
                "id": "review",
                "kind": "review",
                "success_criteria": "Review passes.",
            },
        ],
    }


def write_architecture_artifacts(
    root: Path, handoff_id: str = "handoff-1", kind: str = "build"
) -> None:
    write(root, "agent-lifecycle/architecture/agent-architecture.md")
    write(root, "agent-lifecycle/architecture/decisions.md")
    write(root, "docs/references/agent-building-best-practices.md", "# Best practices\n\n## Tools\nFixture.\n")
    create_handoff(
        root,
        handoff_request(handoff_id, kind),
    )


def write_eval_artifacts(root: Path) -> None:
    eval_case = {
        "id": "fixture-case",
        "split": "held_in",
        "tags": ["smoke", "capability", "regression", "edge", "positive", "negative", "representative", "adversarial"],
        "trials": 1,
        "seeds": [1],
        "input": {"initial_user_message": "Fixture request"},
        "simulated_user": {
            "persona": "Fixture persona",
            "private_truth": [{"id": "fact", "value": "Fixture fact", "reveal_on": ["fact"]}],
            "disclosure_policy": {"mode": "progressive", "max_facts_per_turn": 1, "fallback": "next_unrevealed"},
            "termination": {"success_condition": "Fixture done", "max_turns": 2, "stall_turns": 1},
        },
        "expected": {
            "outcome": "Fixture outcome",
            "trajectory": {"required_tools": [], "forbidden_tools": [], "ordered_tools": []},
        },
        "graders": {
            "deterministic": [{"id": "fixture-check", "check": "no_error", "arguments": {}}],
            "rubrics": [{"id": "fixture-rubric", "criterion": "Fixture quality", "evidence": "final_output", "threshold": 0.8}],
        },
    }
    held_out = json.loads(json.dumps(eval_case))
    held_out.update(id="fixture-held-out", split="held_out", tags=["held-out", "edge", "adversarial"])
    create_suite_artifacts(
        {
            "version": 1,
            "status": "complete",
            "name": "fixture-suite",
            "metrics": [
                {"id": "hard-pass", "name": "Hard pass", "kind": "deterministic", "aggregation": "pass_rate", "threshold": 1.0},
                {"id": "quality", "name": "Quality", "kind": "qualitative", "aggregation": "mean", "threshold": 0.8},
                {"id": "turns", "name": "Turns", "kind": "operational", "aggregation": "mean", "threshold": 2},
            ],
            "cases": [eval_case, held_out],
        },
        root,
    )


def write_receipt(root: Path, name: str = "receipt.json", handoff_id: str = "handoff-1") -> Path:
    kind = "build" if (root / "agent-lifecycle/handoffs/build-handoff.yaml").is_file() else "improvement"
    manifest_path = route_manifest(root, kind)
    return write(
        root,
        f"agent-lifecycle/receipts/{name}",
        json.dumps(
            {
                "version": 1,
                "handoff_id": handoff_id,
                "manifest_sha256": digest(manifest_path),
                "result_status": "completed",
                "changed_files": ["agent/prompts/system.md"],
                "test_evidence": ["focused and full suites passed"],
                "review_outcome": "passed",
                "commit_sha": "0123456789abcdef",
                "architecture_changed": False,
            }
        ),
    )


def advance_first_build_to_engineering(root: Path, engineering_loop: str = "included") -> None:
    assert run(root, "start", "first-build", "--engineering-loop", engineering_loop).returncode == 0
    write_goal_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "eval_design"
    write_eval_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "architecture"
    write_architecture_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "awaiting_engineering"


def test_setup_persists_cli_selections_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "target"

    first = run(
        root,
        "setup",
        "--simulator-model",
        "simulator-model",
        "--judge-model",
        "judge-model",
        "--evidence-mode",
        "local",
        "--engineering-loop",
        "included",
    )
    second = run(
        root,
        "setup",
        "--simulator-model",
        "simulator-model",
        "--judge-model",
        "judge-model",
        "--evidence-mode",
        "local",
        "--engineering-loop",
        "included",
    )

    assert first.returncode == second.returncode == 0
    setup = json.loads((root / "agent-lifecycle/setup.yaml").read_text(encoding="utf-8"))
    assert setup == {
        "version": 1,
        "simulator_model": "simulator-model",
        "judge_model": "judge-model",
        "evidence_mode": "local",
        "engineering_loop": "included",
    }
    assert payload(second)["stage"] == "not_started"


def test_complete_first_build_with_included_loop_and_durable_resume(tmp_path: Path) -> None:
    root = tmp_path / "target"
    advance_first_build_to_engineering(root)

    interrupted = payload(run(root, "status"))
    assert interrupted["stage"] == "awaiting_engineering"
    assert interrupted["next"] == "/agent-build-loop"
    assert payload(run(root, "resume", "--receipt", str(write_receipt(root))))["stage"] == "baseline"
    write(root, "agent/prompts/system.md", "Fixture operational prompt.\n")
    suite_path = root / "agent-lifecycle/evals/suite.yaml"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = []
    for case in suite["cases"]:
        if case["split"] != "held_in":
            continue
        scores = [
            {"key": grader["id"], "score": 1.0, "threshold": 1.0}
            for grader in case["graders"]["deterministic"]
        ]
        scores.extend(
            {
                "key": rubric["id"],
                "score": rubric["threshold"],
                "threshold": rubric["threshold"],
            }
            for rubric in case["graders"]["rubrics"]
        )
        cases.append(
            {
                "case_id": case["id"],
                "trials": [
                        {
                            "trial_id": f"{case['id']}:0",
                            "status": "complete",
                            "metrics": {"latency_ms": 0, "cost": 0},
                            "scores": scores,
                            "errors": [],
                    }
                ],
            }
        )
    native_run = root / "agent-lifecycle/evals/native-baseline-run.json"
    write(
        root,
        "agent-lifecycle/evals/native-baseline-run.json",
        json.dumps(
            {
                "version": 1,
                "status": "complete",
                "split": "held_in",
                "suite_sha256": digest(suite_path),
                "target_command": ["python", "agent/run.py"],
                "metrics": [
                    {
                        "id": metric["id"],
                        "value": metric["threshold"]
                        if metric["kind"] != "operational"
                        else 0,
                    }
                    for metric in suite["metrics"]
                ],
                "cases": cases,
            }
        ),
    )
    evaluate_baseline(root, native_run, ["python", "agent/run.py"])

    completed = payload(run(root, "next"))

    assert completed["stage"] == "operational"
    assert completed["status"] == "complete"


def test_next_rejects_missing_artifact_and_returns_corrective_skill(tmp_path: Path) -> None:
    root = tmp_path / "target"
    start = run(root, "start", "first-build")
    assert start.returncode == 0

    result = run(root, "next")

    assert result.returncode == 1
    failure = payload(result)
    assert failure["stage"] == "goal_definition"
    assert failure["next"] == "/agent-goal-interview"
    assert failure["missing"] == [
        "agent-lifecycle/agent-definition/project-brief.md",
        "agent-lifecycle/agent-definition/success-metrics.yaml",
        "agent-lifecycle/agent-definition/business-value-model.yaml",
    ]
    assert payload(run(root, "status"))["stage"] == "goal_definition"


def test_external_loop_pauses_and_resumes_with_same_receipt_contract(tmp_path: Path) -> None:
    root = tmp_path / "target"
    advance_first_build_to_engineering(root, "external")

    waiting = payload(run(root, "status"))

    assert waiting["stage"] == "awaiting_engineering"
    assert waiting["next"] == "Provide an engineering receipt from the selected external loop"
    receipt = write_receipt(root, "external.json")
    resumed = run(root, "resume", "--receipt", str(receipt))
    assert resumed.returncode == 0
    assert payload(resumed)["stage"] == "baseline"


def test_upstream_artifact_change_rewinds_to_earliest_affected_stage(tmp_path: Path) -> None:
    root = tmp_path / "target"
    assert run(root, "start", "first-build").returncode == 0
    write_goal_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "eval_design"
    write_eval_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "architecture"
    write(root, "agent-lifecycle/agent-definition/project-brief.md", "changed upstream definition\n")

    status = payload(run(root, "status"))

    assert status["stage"] == "goal_definition"
    assert status["next"] == "/agent-goal-interview"
    assert status["changed"] == ["agent-lifecycle/agent-definition/project-brief.md"]


def test_complete_improvement_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "target"
    assert run(root, "start", "improvement", "--engineering-loop", "included").returncode == 0
    write(root, "agent-lifecycle/evidence/selected-evidence.yaml", "{}\n")
    assert payload(run(root, "next"))["stage"] == "diagnosis"
    write_goal_artifacts(root)
    write_eval_artifacts(root)
    write_architecture_artifacts(root, "improvement-1", "improvement")
    assert payload(run(root, "next"))["stage"] == "awaiting_engineering"
    assert payload(run(root, "resume", "--receipt", str(write_receipt(root, handoff_id="improvement-1"))))["stage"] == "held_in"
    write(root, "agent/prompts/system.md", "Improved fixture prompt.\n")
    suite_path = root / "agent-lifecycle/evals/suite.yaml"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    write(
        root,
        "agent-lifecycle/evals/agent-baseline.yaml",
        json.dumps(
            {
                "version": 1,
                "status": "operational",
                "target_command": ["python", "agent/run.py"],
                "suite_sha256": digest(suite_path),
                "run_path": "agent-lifecycle/evals/original.json",
                "run_sha256": "a" * 64,
                "prompt_sha256": {},
                "toolset_sha256": {},
                "comparison": {
                    "quality": 0.8,
                    "hard_invariant_pass_rate": 1.0,
                    "latency_ms": 1.0,
                    "cost": 0.01,
                    "trial_count": 1,
                },
            }
        ),
    )

    def native_run(case_id: str, split: str) -> dict:
        return {
            "version": 1,
            "status": "complete",
            "split": split,
            "suite_sha256": digest(suite_path),
            "target_command": ["python", "agent/run.py"],
            "cases": [
                {
                    "case_id": case_id,
                    "trials": [
                        {
                            "trial_id": f"{case_id}:0",
                            "status": "complete",
                            "metrics": {"latency_ms": 1.0, "cost": 0.01},
                            "scores": [
                                {"key": "fixture-check", "score": 1.0, "threshold": 1.0},
                                {"key": "fixture-rubric", "score": 0.8, "threshold": 0.8},
                            ],
                            "errors": [],
                        }
                    ],
                }
            ],
        }

    held_in_run = write(
        root,
        "agent-lifecycle/evals/improvement-held-in.json",
        json.dumps(native_run("fixture-case", "held_in")),
    )
    assert evaluate_held_in(root, held_in_run)["decision"] == "accepted"
    assert payload(run(root, "next"))["stage"] == "held_out"
    held_out_run = write(
        root,
        "agent-lifecycle/evals/improvement-held-out.json",
        json.dumps(native_run("fixture-held-out", "held_out")),
    )
    assert evaluate_held_out(root, held_out_run)["decision"] == "accepted"
    assert payload(run(root, "next"))["stage"] == "learning"
    completed = record_eval_loop_learning(
        root,
        [],
        no_op_reason="The accepted fixture exposed no eval-loop weakness.",
    )["lifecycle"]

    assert completed["stage"] == "operational"
    assert completed["status"] == "complete"


@pytest.mark.parametrize(
    "arguments,diagnostic",
    [
        (("next",), "lifecycle has not started"),
        (("resume", "--receipt", "missing.json"), "not waiting for an engineering receipt"),
        (("start", "unsupported"), "invalid choice"),
    ],
)
def test_invalid_transitions_are_rejected(tmp_path: Path, arguments: tuple[str, ...], diagnostic: str) -> None:
    result = run(tmp_path / "target", *arguments)

    assert result.returncode != 0
    assert diagnostic in (result.stdout + result.stderr).lower()


def test_resume_rejects_malformed_or_failed_receipt_without_advancing(tmp_path: Path) -> None:
    root = tmp_path / "target"
    advance_first_build_to_engineering(root)
    assert payload(run(root, "status"))["stage"] == "awaiting_engineering"
    malformed = write(root, "agent-lifecycle/receipts/malformed.json", json.dumps({"result_status": "failed"}))

    result = run(root, "resume", "--receipt", str(malformed))

    assert result.returncode == 1
    assert "completed receipt" in payload(result)["error"]
    assert payload(run(root, "status"))["stage"] == "awaiting_engineering"


def test_unapproved_handoff_cannot_route_to_engineering(tmp_path: Path) -> None:
    root = tmp_path / "target"
    assert run(root, "start", "first-build").returncode == 0
    write_goal_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "eval_design"
    write_eval_artifacts(root)
    assert payload(run(root, "next"))["stage"] == "architecture"
    write_architecture_artifacts(root)
    write(
        root,
        "agent-lifecycle/handoffs/build-handoff.yaml",
        json.dumps({"handoff_id": "handoff-1", "approval_status": "pending"}),
    )

    result = run(root, "next")

    assert result.returncode == 1
    assert "approved handoff" in payload(result)["error"]
    assert payload(run(root, "status"))["stage"] == "architecture"
