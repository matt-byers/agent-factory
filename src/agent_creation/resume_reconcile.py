from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .architecture_planner import (
    ARCHITECTURE_PATH,
    DECISIONS_PATH,
    ArchitecturePlanningError,
    create_architecture_artifacts,
    validate_architecture_artifacts,
)
from .engineering_handoff import digest, load_manifest


MARKER_PATH = Path("agent-lifecycle/architecture/reconciliation.json")
STATE_PATH = Path("agent-lifecycle/state.yaml")
MARKER_FIELDS = {
    "version",
    "status",
    "receipt_path",
    "receipt_sha256",
    "manifest_sha256",
    "request_sha256",
    "implementation_sha256",
    "before_sha256",
    "after_sha256",
    "reconciled_files",
}


class ReconciliationError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ReconciliationError([f"{label} must be a regular repository file"])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReconciliationError([f"{label} is missing or invalid: {error}"]) from error
    if not isinstance(payload, dict):
        raise ReconciliationError([f"{label} must contain an object"])
    return payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ReconciliationError(["architecture reconciliation marker must be a regular file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def request_digest(request: dict[str, Any]) -> str:
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def current_receipt(
    root: Path, receipt_path: Path, require_waiting: bool = True
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    state = read_object(root / STATE_PATH, "lifecycle state")
    if require_waiting and state.get("stage") != "architecture_reconciliation":
        raise ReconciliationError(["lifecycle is not waiting for architecture reconciliation"])
    recorded = state.get("receipt")
    if not isinstance(recorded, dict):
        raise ReconciliationError(["lifecycle does not contain an accepted engineering receipt"])
    try:
        resolved = receipt_path.resolve()
        relative = resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ReconciliationError(["engineering receipt must remain inside the repository"]) from error
    if str(relative) != recorded.get("path") or digest(resolved) != recorded.get("sha256"):
        raise ReconciliationError(["engineering receipt changed after lifecycle resume"])
    receipt = read_object(resolved, "engineering receipt")
    if receipt.get("architecture_changed") is not True:
        raise ReconciliationError(["receipt does not require architecture reconciliation"])
    manifest_relative = recorded.get("manifest_path")
    if not isinstance(manifest_relative, str):
        raise ReconciliationError(["accepted receipt is missing its manifest path"])
    manifest = root / manifest_relative
    if manifest.is_symlink() or not manifest.is_file():
        raise ReconciliationError(["accepted engineering manifest must be a regular repository file"])
    if digest(manifest) != recorded.get("manifest_sha256"):
        raise ReconciliationError(["accepted engineering manifest changed after lifecycle resume"])
    marker_path = root / MARKER_PATH
    current_marker_applies = False
    if marker_path.exists() and not marker_path.is_symlink():
        marker = read_object(marker_path, "architecture reconciliation marker")
        after = marker.get("after_sha256")
        current_marker_applies = (
            marker.get("receipt_sha256") == recorded.get("sha256")
            and isinstance(after, dict)
            and all(
                (root / relative).is_file() and digest(root / relative) == expected
                for relative, expected in after.items()
            )
        )
    if not current_marker_applies:
        before = recorded.get("architecture_before_sha256")
        if not isinstance(before, dict) or any(
            not (root / relative).is_file() or digest(root / relative) != expected
            for relative, expected in before.items()
        ):
            raise ReconciliationError(["architecture artifacts changed before reconciliation"])
    load_manifest(manifest)
    return state, receipt, manifest


def implementation_digests(root: Path, receipt: dict[str, Any]) -> dict[str, str]:
    issues: list[str] = []
    values: dict[str, str] = {}
    for relative in receipt["changed_files"]:
        path = root / relative
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            issues.append(f"implemented agent file leaves the repository: {relative}")
            continue
        if path.is_symlink() or not path.is_file():
            issues.append(f"implemented agent file is missing or not regular: {relative}")
        else:
            values[relative] = digest(path)
    if issues:
        raise ReconciliationError(issues)
    return values


def marker_result(marker: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "reconciled",
        "architecture": marker["reconciled_files"][0],
        "decisions": marker["reconciled_files"][1],
        "marker": str(MARKER_PATH),
    }


def marker_matches(
    root: Path,
    marker: dict[str, Any],
    receipt_sha256: str,
    request_sha256: str,
    implementation_sha256: dict[str, str],
) -> bool:
    if (
        marker.get("receipt_sha256") != receipt_sha256
        or marker.get("request_sha256") != request_sha256
        or marker.get("implementation_sha256") != implementation_sha256
    ):
        return False
    after = marker.get("after_sha256")
    return isinstance(after, dict) and all(
        (root / relative).is_file() and digest(root / relative) == expected
        for relative, expected in after.items()
    )


def reconcile_architecture(
    root: Path, receipt_path: Path, request: dict[str, Any]
) -> dict[str, Any]:
    state, receipt, manifest = current_receipt(root, receipt_path)
    if not isinstance(request, dict):
        raise ReconciliationError(["architecture reconciliation request must contain an object"])
    receipt_sha256 = digest(receipt_path.resolve())
    request_sha256 = request_digest(request)
    implementation_sha256 = implementation_digests(root, receipt)
    marker_path = root / MARKER_PATH
    if marker_path.exists() or marker_path.is_symlink():
        marker = read_object(marker_path, "architecture reconciliation marker")
        if marker_matches(
            root, marker, receipt_sha256, request_sha256, implementation_sha256
        ):
            return marker_result(marker)
        if marker.get("receipt_sha256") == receipt_sha256:
            raise ReconciliationError(
                ["existing reconciliation does not match the current implementation or request"]
            )
    before = {
        str(path): digest(root / path) for path in (ARCHITECTURE_PATH, DECISIONS_PATH)
    }
    try:
        create_architecture_artifacts(root, request)
    except ArchitecturePlanningError as error:
        raise ReconciliationError(error.issues) from error
    architecture_issues = validate_architecture_artifacts(root)
    if architecture_issues:
        raise ReconciliationError(architecture_issues)
    after = {
        str(path): digest(root / path) for path in (ARCHITECTURE_PATH, DECISIONS_PATH)
    }
    marker = {
        "version": 1,
        "status": "reconciled",
        "receipt_path": str(receipt_path.resolve().relative_to(root.resolve())),
        "receipt_sha256": receipt_sha256,
        "manifest_sha256": digest(manifest),
        "request_sha256": request_sha256,
        "implementation_sha256": implementation_sha256,
        "before_sha256": before,
        "after_sha256": after,
        "reconciled_files": [str(ARCHITECTURE_PATH), str(DECISIONS_PATH)],
    }
    atomic_json(marker_path, marker)
    fingerprints = state.get("artifact_fingerprints")
    architecture_fingerprints = fingerprints.get("architecture") if isinstance(fingerprints, dict) else None
    if isinstance(architecture_fingerprints, dict):
        architecture_fingerprints.update(after)
        atomic_json(root / STATE_PATH, state)
    return marker_result(marker)


def validate_reconciliation(root: Path) -> list[str]:
    try:
        state = read_object(root / STATE_PATH, "lifecycle state")
        recorded = state.get("receipt")
        if not isinstance(recorded, dict):
            return ["lifecycle does not contain an accepted engineering receipt"]
        receipt_path = root / recorded.get("path", "")
        _, receipt, manifest = current_receipt(root, receipt_path, require_waiting=False)
        marker = read_object(root / MARKER_PATH, "architecture reconciliation marker")
        implementation_sha256 = implementation_digests(root, receipt)
    except ReconciliationError as error:
        return error.issues
    issues: list[str] = []
    if set(marker) != MARKER_FIELDS or marker.get("version") != 1 or marker.get("status") != "reconciled":
        issues.append("architecture reconciliation marker schema is invalid")
    if marker.get("receipt_path") != recorded.get("path"):
        issues.append("architecture reconciliation references a different receipt")
    if marker.get("receipt_sha256") != recorded.get("sha256"):
        issues.append("architecture reconciliation references a stale receipt")
    if marker.get("manifest_sha256") != digest(manifest):
        issues.append("architecture reconciliation references a stale manifest")
    if marker.get("implementation_sha256") != implementation_sha256:
        issues.append("implemented agent files changed after reconciliation")
    expected_files = [str(ARCHITECTURE_PATH), str(DECISIONS_PATH)]
    if marker.get("reconciled_files") != expected_files:
        issues.append("reconciliation may update only the architecture picture and decisions")
    after = marker.get("after_sha256")
    if not isinstance(after, dict) or set(after) != set(expected_files):
        issues.append("reconciled architecture digests are invalid")
    else:
        for relative, expected in after.items():
            path = root / relative
            if path.is_symlink() or not path.is_file() or digest(path) != expected:
                issues.append(f"reconciled architecture artifact changed: {relative}")
    issues.extend(validate_architecture_artifacts(root))
    return list(dict.fromkeys(issues))
