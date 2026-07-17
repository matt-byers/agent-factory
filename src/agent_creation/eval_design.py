from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any


SUITE_PATH = Path("agent-lifecycle/evals/suite.yaml")
HELD_OUT_DIRECTORY = Path("agent-lifecycle/evals/held-out")
REQUIRED_COVERAGE = {
    "smoke",
    "capability",
    "regression",
    "edge",
    "positive",
    "negative",
    "representative",
    "adversarial",
}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
METRIC_KINDS = {"deterministic", "qualitative", "operational"}
AGGREGATIONS = {"pass_rate", "mean", "max", "min", "p50", "p95"}


class EvalDesignError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def string_list(value: Any, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(non_empty(item) for item in value)
    )


def valid_threshold(value: Any, bounded: bool = True) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return 0 <= value <= 1 if bounded else value >= 0


def validate_private_truth(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        return [f"{label}.simulated_user.private_truth must contain at least one fact"]
    issues: list[str] = []
    identifiers: set[str] = set()
    for index, fact in enumerate(value):
        fact_label = f"{label}.private_truth[{index}]"
        if not isinstance(fact, dict):
            issues.append(f"{fact_label} must be an object")
            continue
        identifier = fact.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            issues.append(f"{fact_label}.id must use lowercase hyphen-case")
        elif identifier in identifiers:
            issues.append(f"{fact_label}.id is duplicated")
        else:
            identifiers.add(identifier)
        if not non_empty(fact.get("value")):
            issues.append(f"{fact_label}.value is required")
        if not string_list(fact.get("reveal_on")):
            issues.append(f"{fact_label}.reveal_on must contain trigger phrases")
    return issues


def validate_simulated_user(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label}.simulated_user is required"]
    issues: list[str] = []
    if not non_empty(value.get("persona")):
        issues.append(f"{label}.simulated_user.persona is required")
    issues.extend(validate_private_truth(value.get("private_truth"), label))
    policy = value.get("disclosure_policy")
    if not isinstance(policy, dict):
        issues.append(f"{label}.simulated_user.disclosure_policy is required")
    else:
        if policy.get("mode") != "progressive":
            issues.append(f"{label}.disclosure_policy.mode must be progressive")
        maximum = policy.get("max_facts_per_turn")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
            issues.append(f"{label}.disclosure_policy.max_facts_per_turn must be positive")
        if policy.get("fallback") not in {"next_unrevealed", "end"}:
            issues.append(f"{label}.disclosure_policy.fallback is invalid")
    termination = value.get("termination")
    if not isinstance(termination, dict):
        issues.append(f"{label}.simulated_user.termination is required")
    else:
        if not non_empty(termination.get("success_condition")):
            issues.append(f"{label}.termination.success_condition is required")
        for field in ("max_turns", "stall_turns"):
            number = termination.get(field)
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                issues.append(f"{label}.termination.{field} must be a positive integer")
    return issues


def validate_expected(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label}.expected is required"]
    issues: list[str] = []
    if not non_empty(value.get("outcome")):
        issues.append(f"{label}.expected.outcome is required")
    trajectory = value.get("trajectory")
    if not isinstance(trajectory, dict):
        issues.append(f"{label}.expected.trajectory is required")
    else:
        for field in ("required_tools", "forbidden_tools", "ordered_tools"):
            if not string_list(trajectory.get(field), allow_empty=True):
                issues.append(f"{label}.trajectory.{field} must be a string list")
    return issues


def validate_graders(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label}.graders is required"]
    issues: list[str] = []
    deterministic = value.get("deterministic")
    if not isinstance(deterministic, list) or not deterministic:
        issues.append(f"{label} requires at least one deterministic grader")
    else:
        for index, grader in enumerate(deterministic):
            grader_label = f"{label}.deterministic[{index}]"
            if not isinstance(grader, dict):
                issues.append(f"{grader_label} must be an object")
                continue
            if not non_empty(grader.get("id")) or not non_empty(grader.get("check")):
                issues.append(f"{grader_label} requires id and check")
            if not isinstance(grader.get("arguments"), dict):
                issues.append(f"{grader_label}.arguments must be an object")
    rubrics = value.get("rubrics")
    if not isinstance(rubrics, list) or not rubrics:
        issues.append(f"{label} requires at least one narrow qualitative rubric")
    else:
        for index, rubric in enumerate(rubrics):
            rubric_label = f"{label}.rubrics[{index}]"
            if not isinstance(rubric, dict):
                issues.append(f"{rubric_label} must be an object")
                continue
            for field in ("id", "criterion", "evidence"):
                if not non_empty(rubric.get(field)):
                    issues.append(f"{rubric_label}.{field} is required")
            if not valid_threshold(rubric.get("threshold")):
                issues.append(f"{rubric_label}.threshold must be between 0 and 1")
    return issues


def validate_case(value: Any, index: int) -> list[str]:
    label = f"case[{index}]"
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    issues: list[str] = []
    identifier = value.get("id")
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        issues.append(f"{label}.id must use lowercase hyphen-case")
    split = value.get("split")
    if split not in {"held_in", "held_out"}:
        issues.append(f"{label}.split must be held_in or held_out")
    if not string_list(value.get("tags")):
        issues.append(f"{label}.tags must not be empty")
    if split == "held_out" and "held-out" not in value.get("tags", []):
        issues.append(f"{label} held-out split requires held-out tag")
    if "sealed_ref" in value:
        for field in ("sealed_ref", "sha256"):
            if not non_empty(value.get(field)):
                issues.append(f"{label}.{field} is required")
        return issues
    trials = value.get("trials")
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        issues.append(f"{label}.trials must be a positive integer")
    seeds = value.get("seeds")
    if not isinstance(seeds, list) or not all(isinstance(seed, int) and not isinstance(seed, bool) for seed in seeds):
        issues.append(f"{label}.seeds must contain integers")
    elif not isinstance(trials, int) or len(seeds) != trials:
        issues.append(f"{label} requires one seed per trial")
    elif len(set(seeds)) != len(seeds):
        issues.append(f"{label}.seeds must be unique")
    initial_input = value.get("input")
    if not isinstance(initial_input, dict) or not non_empty(initial_input.get("initial_user_message")):
        issues.append(f"{label}.input.initial_user_message is required")
    issues.extend(validate_simulated_user(value.get("simulated_user"), label))
    issues.extend(validate_expected(value.get("expected"), label))
    issues.extend(validate_graders(value.get("graders"), label))
    return issues


def validate_metrics(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        return ["suite.metrics must not be empty"]
    issues: list[str] = []
    kinds: set[str] = set()
    identifiers: set[str] = set()
    for index, metric in enumerate(value):
        label = f"metric[{index}]"
        if not isinstance(metric, dict):
            issues.append(f"{label} must be an object")
            continue
        identifier = metric.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            issues.append(f"{label}.id must use lowercase hyphen-case")
        elif identifier in identifiers:
            issues.append(f"{label}.id is duplicated")
        else:
            identifiers.add(identifier)
        if not non_empty(metric.get("name")):
            issues.append(f"{label}.name is required")
        kind = metric.get("kind")
        if kind not in METRIC_KINDS:
            issues.append(f"{label}.kind is invalid")
        else:
            kinds.add(kind)
        if metric.get("aggregation") not in AGGREGATIONS:
            issues.append(f"{label}.aggregation is invalid")
        if not valid_threshold(metric.get("threshold"), bounded=kind != "operational"):
            issues.append(f"{label}.threshold is invalid")
    for kind in sorted(METRIC_KINDS - kinds):
        issues.append(f"metric kind is required: {kind}")
    return issues


def validate_suite(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["suite must be an object"]
    issues: list[str] = []
    if value.get("version") != 1:
        issues.append("suite.version must be 1")
    if value.get("status") != "complete":
        issues.append("suite.status must be complete")
    if not non_empty(value.get("name")):
        issues.append("suite.name is required")
    issues.extend(validate_metrics(value.get("metrics")))
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        return issues + ["suite.cases must not be empty"]
    identifiers: set[str] = set()
    tags: set[str] = set()
    held_out = 0
    for index, item in enumerate(cases):
        issues.extend(validate_case(item, index))
        if isinstance(item, dict):
            identifier = item.get("id")
            if isinstance(identifier, str):
                if identifier in identifiers:
                    issues.append(f"duplicate case id: {identifier}")
                identifiers.add(identifier)
            if isinstance(item.get("tags"), list):
                tags.update(tag for tag in item["tags"] if isinstance(tag, str))
            if item.get("split") == "held_out":
                held_out += 1
    for tag in sorted(REQUIRED_COVERAGE - tags):
        issues.append(f"coverage tag is required: {tag}")
    if held_out == 0:
        issues.append("at least one held-out case is required")
    return issues


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def create_suite_artifacts(suite: dict[str, Any], root: Path) -> dict[str, Path]:
    issues = validate_suite(suite)
    if issues:
        raise EvalDesignError(issues)
    public_suite = {key: value for key, value in suite.items() if key != "cases"}
    public_cases: list[dict[str, Any]] = []
    held_out_directory = root / HELD_OUT_DIRECTORY
    for item in suite["cases"]:
        if item["split"] != "held_out":
            public_cases.append(item)
            continue
        content = json.dumps(item, indent=2, sort_keys=True) + "\n"
        sealed_path = held_out_directory / f"{item['id']}.sealed.json"
        atomic_write(sealed_path, content)
        sealed_path.chmod(0o600)
        public_cases.append(
            {
                "id": item["id"],
                "split": item["split"],
                "tags": item["tags"],
                "sealed_ref": str(sealed_path.relative_to(root)),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
    public_suite["cases"] = public_cases
    suite_path = root / SUITE_PATH
    atomic_write(suite_path, json.dumps(public_suite, indent=2, sort_keys=True) + "\n")
    return {"suite": suite_path, "held_out": held_out_directory}


def load_held_out_case(root: Path, manifest: dict[str, Any], release: bool) -> dict[str, Any]:
    if not release:
        raise EvalDesignError(["held-out payload is unavailable before the held-out gate"])
    held_out_directory = (root / HELD_OUT_DIRECTORY).resolve()
    path = (root / manifest["sealed_ref"]).resolve()
    if not path.is_relative_to(held_out_directory):
        raise EvalDesignError(["held-out payload must remain inside the sealed held-out directory"])
    try:
        content = path.read_bytes()
    except OSError as error:
        raise EvalDesignError([f"held-out payload cannot be read: {error}"]) from error
    if hashlib.sha256(content).hexdigest() != manifest.get("sha256"):
        raise EvalDesignError(["held-out payload digest does not match its manifest"])
    payload = json.loads(content)
    issues = validate_case(payload, 0)
    if issues or payload.get("split") != "held_out":
        raise EvalDesignError(issues or ["sealed payload is not held-out"])
    return payload


def target_example(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "inputs": {
            "messages": [
                {"role": "user", "content": case["input"]["initial_user_message"]}
            ]
        },
        "metadata": {
            "case_id": case["id"],
            "split": case["split"],
            "tags": list(case["tags"]),
            "trials": case["trials"],
            "seeds": list(case["seeds"]),
        },
    }


def read_suite(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvalDesignError([f"suite is missing or invalid: {error}"]) from error
    if not isinstance(payload, dict):
        raise EvalDesignError(["suite must be an object"])
    return payload
