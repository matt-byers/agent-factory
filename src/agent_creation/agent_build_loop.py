from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from .engineering_handoff import digest, load_manifest
from .spec_plan import (
    BuildPlanError,
    assert_accepted_plan,
    plan_path,
    save_build_state,
)


UNIT_STAGES = ("red", "implementation", "focused_green", "self_verification", "testagent", "review")


class BuildLoopError(ValueError):
    pass


def unit_for(state: dict[str, Any], unit_id: str | None) -> dict[str, Any]:
    unit = next((item for item in state["request"]["units"] if item["id"] == unit_id), None)
    if unit is None:
        raise BuildLoopError(f"unknown unit: {unit_id}")
    for dependency in unit["depends_on"]:
        if "review" not in state["progress"][dependency]["completed_stages"]:
            raise BuildLoopError(f"unit {unit_id} depends on reviewed unit {dependency}")
    return unit


def require_fields(evidence: dict[str, Any], fields: tuple[str, ...], stage: str) -> None:
    missing = [field for field in fields if field not in evidence]
    if missing:
        raise BuildLoopError(f"{stage} evidence is missing: {', '.join(missing)}")


def manual_status(plan: str, smoke_id: str) -> str:
    heading = f"#### {smoke_id} [manual]"
    start = plan.find(heading)
    if start < 0:
        return "Pending"
    end = plan.find("\n#### ", start + len(heading))
    if end < 0:
        end = plan.find("\n### ", start + len(heading))
    section = plan[start : end if end >= 0 else len(plan)]
    for line in section.splitlines():
        if line.startswith("- Status:"):
            return line.split(":", 1)[1].strip()
    return "Pending"


def validate_stage(
    root: Path,
    state: dict[str, Any],
    stage: str,
    unit: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    if not isinstance(evidence, dict):
        raise BuildLoopError(f"{stage} evidence must contain an object")
    progress = state["progress"][unit["id"]]
    completed = progress["completed_stages"]
    testagent_enabled = unit["testagent"]["enabled"]
    required_sequence = ["red", "implementation", "focused_green", "self_verification"]
    if testagent_enabled:
        required_sequence.append("testagent")
    required_sequence.append("review")
    expected = required_sequence[len(completed)] if len(completed) < len(required_sequence) else None
    if stage != expected:
        raise BuildLoopError(f"stage {stage} cannot run before {expected or 'unit completion'}")
    if stage == "red":
        require_fields(evidence, ("command", "exit_code", "output"), stage)
        if not isinstance(evidence["command"], str) or not isinstance(evidence["exit_code"], int) or not isinstance(evidence["output"], str):
            raise BuildLoopError("RED evidence has invalid field types")
        if evidence["command"] != unit["red_command"]:
            raise BuildLoopError("RED command does not match the accepted plan")
        if evidence["exit_code"] == 0 or unit["expected_red"] not in evidence["output"]:
            raise BuildLoopError("expected RED was not captured for the intended reason")
    elif stage == "implementation":
        require_fields(evidence, ("changed_files",), stage)
        changed = evidence["changed_files"]
        if not isinstance(changed, list) or not changed or not all(isinstance(path, str) for path in changed):
            raise BuildLoopError("implementation changed files must be a non-empty string list")
        if len(set(changed)) != len(changed) or not set(changed).issubset(set(unit["files"])):
            raise BuildLoopError("implementation changed files must remain within the unit exact allowlist")
    elif stage == "focused_green":
        require_fields(evidence, ("command", "exit_code"), stage)
        if evidence["command"] != unit["focused_green_command"] or evidence["exit_code"] != 0:
            raise BuildLoopError("focused GREEN must use the accepted command and pass")
    elif stage == "self_verification":
        require_fields(evidence, ("commands", "smoke_tests"), stage)
        commands = evidence["commands"]
        if not isinstance(commands, list) or not all(isinstance(item, dict) for item in commands):
            raise BuildLoopError("self verification commands must contain evidence objects")
        if not isinstance(evidence["smoke_tests"], list) or not all(
            isinstance(item, dict) for item in evidence["smoke_tests"]
        ):
            raise BuildLoopError("smoke tests must contain evidence objects")
        expected_commands = unit["self_verification"]
        if [item.get("command") for item in commands] != expected_commands or any(
            item.get("exit_code") != 0 for item in commands
        ):
            raise BuildLoopError("all planned self verification commands must pass")
        automated = {item.get("id"): item for item in evidence["smoke_tests"]}
        plan = plan_path(root, state["attempt_id"]).read_text(encoding="utf-8")
        for smoke in unit["smoke_tests"]:
            if smoke["mode"] == "manual":
                if manual_status(plan, smoke["id"]) != "Passed":
                    raise BuildLoopError(f"manual smoke test is not Passed: {smoke['id']}")
            else:
                result = automated.get(smoke["id"])
                if not isinstance(result, dict) or result.get("status") != "Passed" or not result.get("evidence"):
                    raise BuildLoopError(f"automated smoke test must pass with evidence: {smoke['id']}")
    elif stage == "testagent":
        require_fields(evidence, ("command", "status", "transcript"), stage)
        if evidence["command"] != "testagent" or evidence["status"] != "Passed" or not evidence["transcript"]:
            raise BuildLoopError("testagent must retain a passing bounded transcript")
    elif stage == "review":
        require_fields(evidence, ("sources", "blocking_findings", "high_findings", "outcome"), stage)
        if not all(isinstance(evidence[field], list) for field in ("sources", "blocking_findings", "high_findings")):
            raise BuildLoopError("review sources and findings must be lists")
        if set(evidence["sources"]) != set(state["request"]["review_sources"]):
            raise BuildLoopError("review must use every source named in the accepted plan")
        if evidence["blocking_findings"] or evidence["high_findings"] or evidence["outcome"] != "passed":
            raise BuildLoopError("review cannot complete with blocking or high findings")


def record_stage(
    root: Path,
    attempt_id: str,
    stage: str,
    unit_id: str | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise BuildLoopError(f"{stage} evidence must contain an object")
    try:
        state = assert_accepted_plan(root, attempt_id)
    except BuildPlanError as error:
        raise BuildLoopError(str(error)) from error
    if state.get("commit_sha"):
        raise BuildLoopError("committed attempts cannot accept more evidence")
    if stage == "full_suite":
        if state.get("full_suite") is not None:
            raise BuildLoopError("the full suite must run exactly once")
        incomplete = [
            unit["id"]
            for unit in state["request"]["units"]
            if "review" not in state["progress"][unit["id"]]["completed_stages"]
        ]
        if incomplete:
            raise BuildLoopError("full suite requires every unit review: " + ", ".join(incomplete))
        try:
            require_fields(evidence, ("command", "exit_code", "output"), stage)
            if evidence["command"] != state["request"]["full_suite_command"] or evidence["exit_code"] != 0:
                raise BuildLoopError("the accepted full suite command must pass")
        except BuildLoopError as error:
            state["failures"].append(
                {"stage": stage, "unit_id": None, "error": str(error), "evidence": evidence}
            )
            save_build_state(root, attempt_id, state)
            raise
        state["full_suite"] = evidence
        state["status"] = "ready_to_commit"
    else:
        if stage not in UNIT_STAGES:
            raise BuildLoopError(f"unsupported build stage: {stage}")
        unit = unit_for(state, unit_id)
        try:
            validate_stage(root, state, stage, unit, evidence)
        except BuildLoopError as error:
            state["failures"].append(
                {"stage": stage, "unit_id": unit["id"], "error": str(error), "evidence": evidence}
            )
            save_build_state(root, attempt_id, state)
            raise
        progress = state["progress"][unit["id"]]
        progress["completed_stages"].append(stage)
        progress["evidence"][stage] = evidence
        state["status"] = "running"
    save_build_state(root, attempt_id, state)
    return state


def run_git(root: Path, arguments: list[str]) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BuildLoopError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def commit_and_write_receipt(
    root: Path,
    attempt_id: str,
    message: str,
    architecture_changed: bool,
) -> Path:
    try:
        state = assert_accepted_plan(root, attempt_id)
    except BuildPlanError as error:
        raise BuildLoopError(str(error)) from error
    if state.get("status") != "ready_to_commit" or state.get("full_suite") is None:
        raise BuildLoopError("an accepted plan and one passing full suite are required before commit")
    changed = sorted(
        {
            path
            for progress in state["progress"].values()
            for path in progress["evidence"]["implementation"]["changed_files"]
        }
    )
    manifest_path = root / state["handoff_manifest"]
    manifest = load_manifest(manifest_path)
    allowlist = {item["path"] for item in manifest["editable_paths"]}
    if not changed or not set(changed).issubset(allowlist):
        raise BuildLoopError("commit paths must match the exact handoff allowlist")
    status_lines = run_git(root, ["status", "--porcelain", "--", *changed]).splitlines()
    observed = {line[3:] for line in status_lines if len(line) > 3}
    if observed != set(changed):
        raise BuildLoopError("every declared changed file, and no other allowed file, must be modified")
    run_git(root, ["add", "--", *changed])
    run_git(root, ["commit", "-m", message, "--", *changed])
    commit_sha = run_git(root, ["rev-parse", "HEAD"])
    committed = set(run_git(root, ["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"]).splitlines())
    if committed != set(changed):
        raise BuildLoopError("explicit commit contained paths outside the accepted change set")
    evidence = []
    for unit in state["request"]["units"]:
        progress = state["progress"][unit["id"]]
        evidence.extend(
            [
                f"unit {unit['id']} RED: {progress['evidence']['red']['command']} failed as intended",
                f"unit {unit['id']} focused GREEN: {progress['evidence']['focused_green']['command']} passed",
                f"unit {unit['id']} self-verification and smoke tests: passed",
            ]
        )
        if unit["testagent"]["enabled"]:
            evidence.append(f"unit {unit['id']} testagent: passed")
        evidence.append(f"unit {unit['id']} review: passed")
    evidence.append("full suite: passed")
    receipt = {
        "version": 1,
        "handoff_id": manifest["handoff_id"],
        "manifest_sha256": digest(manifest_path),
        "build_plan_sha256": digest(plan_path(root, attempt_id)),
        "result_status": "completed",
        "changed_files": changed,
        "test_evidence": evidence,
        "review_outcome": "passed",
        "commit_sha": commit_sha,
        "architecture_changed": architecture_changed,
    }
    receipt_path = plan_path(root, attempt_id).parent / "engineering-receipt.json"
    if receipt_path.is_symlink():
        raise BuildLoopError("engineering receipt must be a regular repository file")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    state["status"] = "committed"
    state["commit_sha"] = commit_sha
    state["receipt"] = str(receipt_path.relative_to(root))
    save_build_state(root, attempt_id, state)
    return receipt_path
