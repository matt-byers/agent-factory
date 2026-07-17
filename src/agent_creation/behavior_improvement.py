from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from .engineering_handoff import create_handoff
from .target_adapter import redact_diagnostic


FAILURE_CLASSES = {
    "target_agent",
    "eval_definition",
    "simulated_user",
    "provider",
    "target_data",
    "harness",
    "evidence",
    "surrounding_application",
    "inconclusive",
}
REPAIR_ROUTES = {
    "eval_definition": "eval_repair",
    "simulated_user": "eval_repair",
    "target_data": "eval_repair",
    "harness": "eval_repair",
    "provider": "evidence_repair",
    "evidence": "evidence_repair",
}
EXTERNAL_OWNERS = {
    "database": "database_owner",
    "application_service": "application_service_owner",
    "api": "api_owner",
    "authentication": "authentication_owner",
    "infrastructure": "infrastructure_owner",
    "ui": "ui_owner",
    "ux": "ux_owner",
}


class BehaviorImprovementError(ValueError):
    pass


@dataclass(frozen=True)
class FailureReport:
    failure_id: str
    failure_class: str
    reproducible: bool
    summary: str
    causal_mechanism: str
    proposed_change: str
    evidence_refs: tuple[str, ...]
    editable_paths: tuple[Mapping[str, str], ...]
    acceptance_eval_ids: tuple[str, ...]
    affected_case_ids: tuple[str, ...]
    expected_user_effect: str
    expected_business_effect: str
    external_component: str | None = None

    def __post_init__(self) -> None:
        if self.failure_class not in FAILURE_CLASSES:
            raise BehaviorImprovementError(
                f"unsupported failure class: {self.failure_class}"
            )


@dataclass(frozen=True)
class OwnershipDecision:
    owner: str
    route: str
    reason: str
    create_engineering_handoff: bool
    external_owner: str | None = None
    editable_paths: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True)
class HypothesisProbe:
    hypothesis: str
    messages: tuple[str, ...]
    max_turns: int


def assign_failure_ownership(report: FailureReport) -> OwnershipDecision:
    if report.failure_class == "target_agent":
        if report.reproducible:
            return OwnershipDecision(
                "target_agent",
                "engineering_handoff",
                "reproducible target-agent behavior is supported by retained evidence",
                True,
                editable_paths=report.editable_paths,
            )
        return OwnershipDecision(
            "inconclusive",
            "evidence_collection",
            "target-agent behavior was not reproduced",
            False,
        )
    if report.failure_class in REPAIR_ROUTES:
        return OwnershipDecision(
            report.failure_class,
            REPAIR_ROUTES[report.failure_class],
            "the owning eval or evidence surface must be repaired before diagnosis resumes",
            False,
        )
    if report.failure_class == "surrounding_application":
        external_owner = EXTERNAL_OWNERS.get(
            report.external_component or "", "surrounding_application_owner"
        )
        return OwnershipDecision(
            "surrounding_application",
            "external_owner",
            "the failure is outside the target agent harness and context",
            False,
            external_owner=external_owner,
        )
    return OwnershipDecision(
        "inconclusive",
        "evidence_collection",
        "available evidence cannot support an owned change",
        False,
    )


def run_hypothesis_probes(
    probes: Sequence[HypothesisProbe],
    runner: Callable[[HypothesisProbe], Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if not probes:
        raise BehaviorImprovementError("at least one hypothesis probe is required")
    if len(probes) > 3:
        raise BehaviorImprovementError("run at most 3 testagent hypothesis probes")
    hypotheses = [probe.hypothesis for probe in probes]
    if any(not hypothesis.strip() for hypothesis in hypotheses) or len(set(hypotheses)) != len(
        hypotheses
    ):
        raise BehaviorImprovementError("hypothesis probes must use unique non-empty names")
    results: list[dict[str, Any]] = []
    for probe in probes:
        if probe.max_turns < 1 or probe.max_turns > 4:
            raise BehaviorImprovementError("each hypothesis probe may use at most 4 turns")
        if not probe.messages or len(probe.messages) > probe.max_turns:
            raise BehaviorImprovementError("probe messages must fit within its turn bound")
        result = dict(runner(probe))
        results.append(
            {
                "hypothesis": probe.hypothesis,
                "max_turns": probe.max_turns,
                "evidence_type": "exploratory",
                "acceptance_gate": False,
                **result,
            }
        )
    return tuple(results)


def run_direct_repair(
    report: FailureReport,
    decision: OwnershipDecision,
    *,
    repair: Callable[[FailureReport], str],
    rerun: Callable[[tuple[str, ...]], Sequence[str]],
) -> dict[str, Any]:
    if decision != assign_failure_ownership(report):
        raise BehaviorImprovementError("repair decision does not match the failure report")
    if decision.route not in {"eval_repair", "evidence_repair"}:
        raise BehaviorImprovementError("direct repair requires eval or evidence ownership")
    repair_artifact = repair(report)
    rerun_artifacts = tuple(rerun(report.affected_case_ids))
    if not repair_artifact or not rerun_artifacts:
        raise BehaviorImprovementError("repair and affected-case rerun artifacts are required")
    return {
        "repair_artifact": repair_artifact,
        "rerun_artifacts": rerun_artifacts,
        "next_route": "diagnosis",
        "agent_validation_required": False,
    }


def create_agent_improvement_handoff(
    root: Path, report: FailureReport, *, approved: bool
) -> dict[str, Path]:
    decision = assign_failure_ownership(report)
    if not decision.create_engineering_handoff:
        raise BehaviorImprovementError(
            "only a reproducible target-agent failure may create an engineering handoff"
        )
    if not approved:
        raise BehaviorImprovementError("agent improvement recommendation must be approved")
    handoff_id = f"improvement-{_identifier(report.failure_id)}"
    recommendation_id = f"repair-{_identifier(report.failure_id)}"
    request = {
        "version": 1,
        "handoff_id": handoff_id,
        "kind": "improvement",
        "approval_status": "approved",
        "editable_paths": [dict(item) for item in report.editable_paths],
        "recommendations": [
            {
                "id": recommendation_id,
                "requirement_or_evidence": list(report.evidence_refs),
                "likely_cause_or_design_need": redact_diagnostic(report.causal_mechanism),
                "proposed_change": redact_diagnostic(report.proposed_change),
                "source_rationale": {
                    "summary": (
                        "Use the smallest agent-owned change supported by reproducible evidence, "
                        "then evaluate its observable effect."
                    ),
                    "references": [
                        "docs/references/agent-building-best-practices.md#eval-grounded-harness-improvement"
                    ],
                },
                "expected_effect": {
                    "user": redact_diagnostic(report.expected_user_effect),
                    "business": redact_diagnostic(report.expected_business_effect),
                },
                "acceptance_eval_ids": list(report.acceptance_eval_ids),
            }
        ],
        "acceptance_gates": [
            {
                "id": "focused-tests",
                "kind": "focused_tests",
                "command": ".venv/bin/python -m pytest -q agent/tests",
                "success_criteria": "Focused tests for the changed agent surface pass.",
            },
            {
                "id": "full-suite",
                "kind": "full_suite",
                "command": ".venv/bin/python -m pytest -q",
                "success_criteria": "The repository deterministic suite passes.",
            },
            {
                "id": "acceptance-evals",
                "kind": "acceptance_evals",
                "eval_ids": list(report.acceptance_eval_ids),
                "success_criteria": "Every evidence-linked acceptance eval meets its threshold.",
            },
            {
                "id": "self-review",
                "kind": "review",
                "success_criteria": "Architecture, simplicity, and security review passes.",
            },
        ],
    }
    return create_handoff(root, request)


def analyze_testagent_transcript(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BehaviorImprovementError(f"transcript is missing or invalid: {path}") from error
    if not isinstance(document, dict) or not isinstance(document.get("turns"), list):
        raise BehaviorImprovementError("testagent transcript must contain a turns list")
    lines = text.splitlines()
    tool_calls: list[dict[str, Any]] = []
    call_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    repeated: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for turn_index, turn in enumerate(document["turns"]):
        if not isinstance(turn, dict):
            continue
        results = {
            str(item.get("tool_call_id")): item
            for item in turn.get("tool_results", [])
            if isinstance(item, dict) and item.get("tool_call_id") is not None
        }
        for call in turn.get("tool_calls", []):
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "")
            name = str(call.get("name") or "unknown")
            result = results.get(call_id, {})
            status = str(result.get("status") or "missing")
            failed = status not in {"ok", "success", "complete", "completed"}
            item = {
                "turn": turn.get("turn_index", turn_index),
                "tool": name,
                "call_id": call_id,
                "status": status,
                "failed": failed,
                "call_line": _line_number(lines, '"id"', call_id),
                "result_line": _line_number(lines, '"tool_call_id"', call_id),
                "result": _redact(result.get("content")),
            }
            tool_calls.append(item)
            call_counts[name] += 1
            if failed:
                failure_counts[name] += 1
                signature = json.dumps(_redact(result.get("content")), sort_keys=True)
                repeated[(name, signature)].append(item)
    repeated_failures = [
        {
            "tool": name,
            "signature": signature,
            "count": len(items),
            "result_lines": [item["result_line"] for item in items],
        }
        for (name, signature), items in sorted(repeated.items())
        if len(items) > 1
    ]
    termination = document.get("termination")
    return {
        "source": str(path.resolve()),
        "turn_count": len(document["turns"]),
        "tool_call_counts": dict(sorted(call_counts.items())),
        "failed_tool_counts": dict(sorted(failure_counts.items())),
        "tool_calls": tool_calls,
        "repeated_failures": repeated_failures,
        "errors": [
            _redact(error)
            for turn in document["turns"]
            if isinstance(turn, dict)
            for error in turn.get("errors", [])
            if isinstance(error, dict)
        ],
        "termination": _redact(termination) if isinstance(termination, dict) else {},
    }


def render_transcript_analysis(analysis: Mapping[str, Any]) -> str:
    lines = [
        "# Agent Transcript Evidence",
        "",
        f"Source: `{analysis['source']}`",
        f"Turns: {analysis['turn_count']}",
        "",
        "## Tool Call Counts",
        "",
    ]
    lines.extend(
        f"- {name}: {count}"
        for name, count in analysis.get("tool_call_counts", {}).items()
    )
    if not analysis.get("tool_call_counts"):
        lines.append("- none")
    lines.extend(["", "## Failed Tool Counts", ""])
    lines.extend(
        f"- {name}: {count}"
        for name, count in analysis.get("failed_tool_counts", {}).items()
    )
    if not analysis.get("failed_tool_counts"):
        lines.append("- none")
    lines.extend(["", "## Tool Calls", ""])
    for item in analysis.get("tool_calls", []):
        marker = "FAILED" if item["failed"] else "ok"
        lines.append(
            f"- {marker}: `{item['tool']}` turn {item['turn']} at line {item['call_line']}; "
            f"result line {item['result_line']}"
        )
    lines.extend(["", "## Repeated Failure Signatures", ""])
    for item in analysis.get("repeated_failures", []):
        lines.append(f"- `{item['tool']}` x{item['count']}: {item['signature']}")
    if not analysis.get("repeated_failures"):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _line_number(lines: Sequence[str], key: str, value: str) -> int:
    if not value:
        return 0
    pattern = re.compile(rf"{re.escape(key)}\s*:\s*{re.escape(json.dumps(value))}")
    return next((index for index, line in enumerate(lines, 1) if pattern.search(line)), 0)


def _identifier(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not normalized or not normalized[0].isalpha():
        raise BehaviorImprovementError("failure id must contain a leading letter")
    return normalized


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return redact_diagnostic(value)
    return value
