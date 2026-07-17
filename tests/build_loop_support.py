from __future__ import annotations

import json
from pathlib import Path

from agent_creation.engineering_handoff import create_handoff


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def create_build_handoff(root: Path) -> Path:
    sources = {
        "agent-lifecycle/agent-definition/project-brief.md": "# Brief\n\n## Requirements\n\n- FR1: Reliable answers.\n",
        "agent-lifecycle/architecture/agent-architecture.md": "# Architecture\n\nStatus: complete\n",
        "agent-lifecycle/architecture/decisions.md": "# Decisions\n\n## Workflow\n\nUse one bounded workflow.\n",
        "docs/references/agent-building-best-practices.md": "# Best practices\n\n## Tools\n\nUse deterministic tools.\n",
    }
    for relative, content in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    write_json(
        root / "agent-lifecycle/evals/suite.yaml",
        {
            "version": 1,
            "status": "complete",
            "cases": [{"id": "reliable-answer", "split": "held_in"}],
        },
    )
    paths = create_handoff(
        root,
        {
            "version": 1,
            "handoff_id": "build-loop-001",
            "kind": "build",
            "approval_status": "approved",
            "editable_paths": [
                {"path": "agent/prompts/system.md", "surface": "prompts"},
                {"path": "agent/tests/test_system_prompt.py", "surface": "agent_tests"},
            ],
            "recommendations": [
                {
                    "id": "improve-reliability",
                    "requirement_or_evidence": [
                        "agent-lifecycle/agent-definition/project-brief.md#requirements",
                        "agent-lifecycle/evals/suite.yaml#reliable-answer",
                    ],
                    "likely_cause_or_design_need": "The prompt needs an explicit response contract.",
                    "proposed_change": "Add a concise grounded-answer rule and its regression test.",
                    "source_rationale": {
                        "summary": "Deterministic contracts reduce avoidable model variance.",
                        "references": [
                            "docs/references/agent-building-best-practices.md#tools",
                            "agent-lifecycle/architecture/decisions.md#workflow",
                        ],
                    },
                    "expected_effect": {
                        "user": "Answers are more reliable.",
                        "business": "Fewer requests need rework.",
                    },
                    "acceptance_eval_ids": ["reliable-answer"],
                }
            ],
            "acceptance_gates": [
                {
                    "id": "focused-tests",
                    "kind": "focused_tests",
                    "command": "pytest -q agent/tests/test_system_prompt.py",
                    "success_criteria": "The prompt regression test passes.",
                },
                {
                    "id": "full-suite",
                    "kind": "full_suite",
                    "command": "pytest -q",
                    "success_criteria": "The full suite passes once.",
                },
                {
                    "id": "acceptance-evals",
                    "kind": "acceptance_evals",
                    "eval_ids": ["reliable-answer"],
                    "success_criteria": "The named eval passes.",
                },
                {
                    "id": "review",
                    "kind": "review",
                    "success_criteria": "Review has no blocking or high findings.",
                },
            ],
        },
    )
    return paths["manifest"]


def build_plan_request(manual_smoke: bool = False, testagent: bool = True) -> dict:
    smoke = {
        "id": "prompt-behavior",
        "action": "Run the prompt regression probe.",
        "expected_outcome": "The answer follows the grounded-answer rule.",
        "mode": "manual" if manual_smoke else "automated",
    }
    if manual_smoke:
        smoke["manual_reason"] = "A domain owner must judge whether the tone is acceptable."
    return {
        "version": 1,
        "requirements": [
            {"id": "FR1", "summary": "Produce reliable answers."},
            {"id": "NFR1", "summary": "Keep the implementation concise."},
        ],
        "units": [
            {
                "id": "1.1",
                "title": "Grounded response prompt",
                "requirement_ids": ["FR1", "NFR1"],
                "depends_on": [],
                "files": ["agent/prompts/system.md", "agent/tests/test_system_prompt.py"],
                "source_references": [
                    "docs/references/agent-building-best-practices.md#tools"
                ],
                "test_file": "agent/tests/test_system_prompt.py",
                "red_command": "pytest -q agent/tests/test_system_prompt.py",
                "expected_red": "grounded answer rule is missing",
                "implementation": "Add the rule required by the accepted handoff.",
                "focused_green_command": "pytest -q agent/tests/test_system_prompt.py",
                "self_verification": ["python -m compileall -q agent"],
                "smoke_tests": [smoke],
                "testagent": {
                    "enabled": testagent,
                    "probes": ["Ask for an answer that requires grounding."] if testagent else [],
                },
            }
        ],
        "review_sources": [
            "docs/references/agent-building-best-practices.md",
            "agent-lifecycle/architecture/agent-architecture.md",
        ],
        "full_suite_command": "pytest -q",
    }
