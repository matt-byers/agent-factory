from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.behavior_improvement import (
    BehaviorImprovementError,
    FailureReport,
    HypothesisProbe,
    analyze_testagent_transcript,
    assign_failure_ownership,
    create_agent_improvement_handoff,
    run_direct_repair,
    run_hypothesis_probes,
)
from agent_creation.engineering_handoff import load_manifest, verify_handoff


def report(failure_class: str, *, reproducible: bool = True) -> FailureReport:
    return FailureReport(
        failure_id=f"{failure_class}-failure",
        failure_class=failure_class,
        reproducible=reproducible,
        summary="The observed behavior prevents the user outcome.",
        causal_mechanism="The agent selects an unsuitable action after valid evidence is available.",
        proposed_change="Tighten the tool contract and deterministic recovery path.",
        evidence_refs=("agent-lifecycle/evidence/selected-evidence.yaml#trace",),
        editable_paths=(
            {"path": "agent/tools/lookup.py", "surface": "agent_tool_contracts"},
        ),
        acceptance_eval_ids=("core-resolution",),
        affected_case_ids=("core-resolution",),
        expected_user_effect="Users receive a complete supported answer.",
        expected_business_effect="Avoidable retries and handling time decrease.",
    )


def write_handoff_sources(root: Path) -> None:
    sources = {
        "agent-lifecycle/agent-definition/project-brief.md": "# Brief\n\nStatus: complete\n",
        "agent-lifecycle/architecture/agent-architecture.md": "# Architecture\n\nStatus: complete\n",
        "agent-lifecycle/architecture/decisions.md": "# Decisions\n\nStatus: complete\n",
        "docs/references/agent-building-best-practices.md": (
            "# Best practices\n\n## Tool design\nUse deterministic contracts. [S2]\n\n"
            "## Eval-grounded harness improvement\nUse reproducible evidence. [S11]\n"
        ),
        "agent-lifecycle/evidence/selected-evidence.yaml": json.dumps(
            {"trace": {"source_link": "https://trace.example/one"}}
        ),
    }
    for relative, content in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    suite = root / "agent-lifecycle/evals/suite.yaml"
    suite.parent.mkdir(parents=True, exist_ok=True)
    suite.write_text(
        json.dumps(
            {
                "version": 1,
                "status": "complete",
                "cases": [{"id": "core-resolution", "split": "held_in"}],
            }
        ),
        encoding="utf-8",
    )


def test_generic_transcript_analyzer_extracts_failures_and_line_evidence(tmp_path: Path) -> None:
    transcript = tmp_path / "testagent.json"
    transcript.write_text(
        json.dumps(
            {
                "turns": [
                    {
                        "turn_index": 0,
                        "tool_calls": [
                            {"id": "call-1", "name": "lookup", "args": {"query": "policy"}}
                        ],
                        "tool_results": [
                            {
                                "tool_call_id": "call-1",
                                "status": "error",
                                "content": "dependency unavailable token=hidden-secret",
                            }
                        ],
                        "errors": [],
                    },
                    {
                        "turn_index": 1,
                        "tool_calls": [
                            {"id": "call-2", "name": "lookup", "args": {"query": "policy"}}
                        ],
                        "tool_results": [
                            {
                                "tool_call_id": "call-2",
                                "status": "error",
                                "content": "dependency unavailable token=hidden-secret",
                            }
                        ],
                        "errors": [],
                    },
                ],
                "termination": {"status": "stopped", "reason": "stall"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    analysis = analyze_testagent_transcript(transcript)

    assert analysis["tool_call_counts"] == {"lookup": 2}
    assert analysis["failed_tool_counts"] == {"lookup": 2}
    assert analysis["repeated_failures"][0]["count"] == 2
    assert "hidden-secret" not in json.dumps(analysis)
    assert all(item["call_line"] > 0 and item["result_line"] > 0 for item in analysis["tool_calls"])
    assert analysis["termination"] == {"status": "stopped", "reason": "stall"}

    result = subprocess.run(
        [
            sys.executable,
            str(
                REPOSITORY_ROOT
                / ".claude/skills/agent-behavior-review/scripts/analyze_transcript.py"
            ),
            str(transcript),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "# Agent Transcript Evidence" in result.stdout
    assert "lookup: 2" in result.stdout
    assert "hidden-secret" not in result.stdout


@pytest.mark.parametrize(
    "failure_class,reproducible,route,owner",
    [
        ("target_agent", True, "engineering_handoff", "target_agent"),
        ("target_agent", False, "evidence_collection", "inconclusive"),
        ("eval_definition", True, "eval_repair", "eval_definition"),
        ("simulated_user", True, "eval_repair", "simulated_user"),
        ("provider", True, "evidence_repair", "provider"),
        ("evidence", True, "evidence_repair", "evidence"),
        ("target_data", True, "eval_repair", "target_data"),
        ("harness", True, "eval_repair", "harness"),
        ("surrounding_application", True, "external_owner", "surrounding_application"),
        ("inconclusive", False, "evidence_collection", "inconclusive"),
    ],
)
def test_failure_ownership_is_deterministic(
    failure_class: str, reproducible: bool, route: str, owner: str
) -> None:
    decision = assign_failure_ownership(report(failure_class, reproducible=reproducible))

    assert decision.owner == owner
    assert decision.route == route
    assert decision.create_engineering_handoff is (route == "engineering_handoff")


@pytest.mark.parametrize(
    "component,expected_owner",
    [
        ("database", "database_owner"),
        ("application_service", "application_service_owner"),
        ("api", "api_owner"),
        ("authentication", "authentication_owner"),
        ("infrastructure", "infrastructure_owner"),
        ("ui", "ui_owner"),
        ("ux", "ux_owner"),
    ],
)
def test_surrounding_application_routes_to_explicit_external_owner(
    component: str, expected_owner: str
) -> None:
    failure = report("surrounding_application")
    failure = FailureReport(**{**failure.__dict__, "external_component": component})

    decision = assign_failure_ownership(failure)

    assert decision.external_owner == expected_owner
    assert decision.editable_paths == ()
    assert decision.create_engineering_handoff is False


def test_bounded_testagent_probes_compare_hypotheses_without_becoming_gates() -> None:
    calls: list[HypothesisProbe] = []

    def runner(probe: HypothesisProbe) -> dict[str, Any]:
        calls.append(probe)
        return {"transcript": f"probe-{probe.hypothesis}.json", "reproduced": True}

    probes = (
        HypothesisProbe("missing-context", ("ambiguous request", "clarification"), max_turns=2),
        HypothesisProbe("tool-contract", ("fully specified request",), max_turns=1),
    )
    results = run_hypothesis_probes(probes, runner)

    assert calls == list(probes)
    assert [item["hypothesis"] for item in results] == ["missing-context", "tool-contract"]
    assert all(item["evidence_type"] == "exploratory" for item in results)
    assert all(item["acceptance_gate"] is False for item in results)

    with pytest.raises(BehaviorImprovementError, match="at most 3"):
        run_hypothesis_probes(probes + probes, runner)
    with pytest.raises(BehaviorImprovementError, match="at most 4 turns"):
        run_hypothesis_probes((HypothesisProbe("unbounded", ("x",), max_turns=5),), runner)


@pytest.mark.parametrize(
    "failure_class",
    ["eval_definition", "simulated_user", "provider", "evidence", "target_data", "harness"],
)
def test_direct_repairs_rerun_affected_cases_back_to_diagnosis(failure_class: str) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    failure = report(failure_class)
    decision = assign_failure_ownership(failure)

    result = run_direct_repair(
        failure,
        decision,
        repair=lambda item: calls.append(("repair", item.affected_case_ids)) or "repair.json",
        rerun=lambda case_ids: calls.append(("rerun", case_ids)) or ("rerun.json",),
    )

    assert calls == [
        ("repair", ("core-resolution",)),
        ("rerun", ("core-resolution",)),
    ]
    assert result == {
        "repair_artifact": "repair.json",
        "rerun_artifacts": ("rerun.json",),
        "next_route": "diagnosis",
        "agent_validation_required": False,
    }


def test_only_reproducible_target_agent_failure_creates_evidence_linked_handoff(
    tmp_path: Path,
) -> None:
    write_handoff_sources(tmp_path)

    paths = create_agent_improvement_handoff(tmp_path, report("target_agent"), approved=True)
    manifest = load_manifest(paths["manifest"])
    specification = paths["implementation_spec"].read_text(encoding="utf-8")

    assert verify_handoff(paths["manifest"]) == []
    assert manifest["kind"] == "improvement"
    assert manifest["editable_paths"] == [
        {"path": "agent/tools/lookup.py", "surface": "agent_tool_contracts"}
    ]
    assert "agent-lifecycle/evidence/selected-evidence.yaml#trace" in specification
    assert "docs/references/agent-building-best-practices.md#eval-grounded-harness-improvement" in specification
    assert "core-resolution" in specification
    assert paths["route"].name == "improvement-handoff.yaml"


@pytest.mark.parametrize(
    "failure_class,reproducible",
    [
        ("target_agent", False),
        ("eval_definition", True),
        ("simulated_user", True),
        ("provider", True),
        ("evidence", True),
        ("target_data", True),
        ("harness", True),
        ("surrounding_application", True),
        ("inconclusive", False),
    ],
)
def test_non_agent_failures_cannot_create_engineering_handoffs(
    tmp_path: Path, failure_class: str, reproducible: bool
) -> None:
    write_handoff_sources(tmp_path)

    with pytest.raises(BehaviorImprovementError, match="reproducible target-agent"):
        create_agent_improvement_handoff(
            tmp_path, report(failure_class, reproducible=reproducible), approved=True
        )

    assert not (tmp_path / "agent-lifecycle/handoffs/improvement-handoff.yaml").exists()


def test_unapproved_target_agent_recommendation_cannot_create_handoff(tmp_path: Path) -> None:
    write_handoff_sources(tmp_path)

    with pytest.raises(BehaviorImprovementError, match="must be approved"):
        create_agent_improvement_handoff(tmp_path, report("target_agent"), approved=False)

    assert not (tmp_path / "agent-lifecycle/handoffs/improvement-handoff.yaml").exists()


def test_generic_skills_and_flat_agent_pairs_are_present_and_aligned() -> None:
    behavior_skill = (
        REPOSITORY_ROOT / ".claude/skills/agent-behavior-review/SKILL.md"
    ).read_text(encoding="utf-8")
    improvement_skill = (
        REPOSITORY_ROOT / ".claude/skills/agent-self-improvement/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "testagent" in behavior_skill
    assert "docs/references/agent-building-best-practices.md" in behavior_skill
    assert "reproducible target-agent" in improvement_skill
    assert "selected engineering loop" in improvement_skill
    assert "held-in" in improvement_skill and "held-out" in improvement_skill
    for name in ("live-transcript-reviewer", "finding-fragment-writer", "final-spec-compiler"):
        assert (REPOSITORY_ROOT / f".claude/agents/{name}.md").is_file()
        assert (REPOSITORY_ROOT / f".codex/agents/{name}.toml").is_file()
        assert not (REPOSITORY_ROOT / f".claude/agents/behavior-review/{name}.md").exists()

    result = subprocess.run(
        [sys.executable, "scripts/agent-config/verify_agent_config.py"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "AGENT-CONFIG GREEN" in result.stdout
