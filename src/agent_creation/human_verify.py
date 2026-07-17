from __future__ import annotations

from pathlib import Path
import re

from .spec_plan import assert_accepted_plan, plan_path


STATUSES = {"Passed", "Failed", "Blocked"}


class HumanVerificationError(ValueError):
    pass


def record_manual_evidence(
    root: Path,
    attempt_id: str,
    unit_id: str,
    smoke_id: str,
    status: str,
    evidence: str,
    observed_date: str,
) -> Path:
    state = assert_accepted_plan(root, attempt_id)
    if status not in STATUSES:
        raise HumanVerificationError("manual status must be Passed, Failed, or Blocked")
    if not evidence.strip() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", observed_date):
        raise HumanVerificationError("manual evidence and an ISO date are required")
    unit = next((item for item in state["request"]["units"] if item["id"] == unit_id), None)
    if unit is None:
        raise HumanVerificationError(f"unknown unit: {unit_id}")
    smoke = next((item for item in unit["smoke_tests"] if item["id"] == smoke_id), None)
    if smoke is None:
        raise HumanVerificationError(f"unknown smoke test: {smoke_id}")
    if smoke["mode"] != "manual":
        raise HumanVerificationError("automated checks cannot be recorded through human verification")
    path = plan_path(root, attempt_id)
    content = path.read_text(encoding="utf-8")
    heading = f"#### {smoke_id} [manual]"
    start = content.find(heading)
    if start < 0:
        raise HumanVerificationError("manual smoke test is missing from the owning plan")
    end = content.find("\n#### ", start + len(heading))
    if end < 0:
        end = content.find("\n### ", start + len(heading))
    if end < 0:
        end = len(content)
    section = content[start:end]
    section = re.sub(r"^- Status:.*$", f"- Status: {status}", section, flags=re.MULTILINE)
    section = re.sub(r"^- Date:.*$", f"- Date: {observed_date}", section, flags=re.MULTILINE)
    section = re.sub(r"^- Evidence:.*$", f"- Evidence: {evidence.strip()}", section, flags=re.MULTILINE)
    path.write_text(content[:start] + section + content[end:], encoding="utf-8")
    assert_accepted_plan(root, attempt_id)
    return path
