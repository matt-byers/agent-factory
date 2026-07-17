from __future__ import annotations

from pathlib import Path
from typing import Any

from .engineering_handoff import (
    EngineeringHandoffError,
    digest,
    load_manifest,
    read_json,
    route_manifest,
    validate_receipt,
)


SETUP_PATH = Path("agent-lifecycle/setup.yaml")
STATE_PATH = Path("agent-lifecycle/state.yaml")
ENGINEERING_LOOPS = {"included", "external"}


class EngineeringContractError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def selected_engineering_loop(root: Path) -> str:
    selections: dict[str, str] = {}
    for path, label in ((root / SETUP_PATH, "lifecycle setup"), (root / STATE_PATH, "lifecycle state")):
        if not path.is_file():
            continue
        try:
            payload = read_json(path, label)
        except EngineeringHandoffError as error:
            raise EngineeringContractError(error.issues) from error
        selected = payload.get("engineering_loop")
        if selected is not None:
            if selected not in ENGINEERING_LOOPS:
                raise EngineeringContractError(["engineering loop must be included or external"])
            selections[label] = selected
    if not selections:
        raise EngineeringContractError(["engineering loop selection is missing from setup and lifecycle state"])
    if len(set(selections.values())) != 1:
        raise EngineeringContractError(["engineering loop selection differs between setup and lifecycle state"])
    return next(iter(selections.values()))


def artifact_reference(root: Path, path: Path) -> dict[str, str]:
    return {"path": str(path.relative_to(root)), "sha256": digest(path)}


def prepare_engineering_input(root: Path, kind: str) -> dict[str, Any]:
    if kind not in {"build", "improvement"}:
        raise EngineeringContractError(["engineering handoff kind must be build or improvement"])
    selected = selected_engineering_loop(root)
    try:
        manifest_path = route_manifest(root, kind)
        manifest = load_manifest(manifest_path)
    except EngineeringHandoffError as error:
        raise EngineeringContractError(error.issues) from error
    if manifest.get("kind") != kind:
        raise EngineeringContractError(["engineering handoff kind does not match the selected route"])
    handoff_directory = manifest_path.parent
    specification = handoff_directory / "implementation-spec.md"
    gates = handoff_directory / "acceptance-gates.json"
    template = handoff_directory / "receipt-template.json"
    return {
        "version": 1,
        "engineering_loop": selected,
        "kind": kind,
        "handoff_id": manifest["handoff_id"],
        "manifest": artifact_reference(root, manifest_path),
        "implementation_spec": artifact_reference(root, specification),
        "acceptance_gates": artifact_reference(root, gates),
        "receipt_template": artifact_reference(root, template),
        "editable_paths": manifest["editable_paths"],
    }


def assess_engineering_receipt(
    receipt: dict[str, Any], manifest_path: Path
) -> dict[str, Any]:
    issues = validate_receipt(receipt, manifest_path, require_completed=False)
    if issues:
        return {"accepted": False, "status": "invalid", "errors": issues}
    status = receipt["result_status"]
    return {"accepted": status == "completed", "status": status, "errors": []}
