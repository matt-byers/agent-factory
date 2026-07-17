from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import Any


NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
SHARED_CODEX_FIELDS = {"name", "description", "developer_instructions"}
ALLOWED_CODEX_FIELDS = SHARED_CODEX_FIELDS | {
    "nickname_candidates",
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
    "mcp_servers",
    "skills",
}


@dataclass(frozen=True)
class Agent:
    name: str
    description: str
    body: str
    metadata: dict[str, Any]
    path: Path


def normalize(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError(f"missing or unterminated frontmatter: {path}")
    end = lines.index("---", 1)
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line[:1].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        token = value.strip()
        if token.startswith('"') and token.endswith('"'):
            token = json.loads(token)
        metadata[key] = token
    return metadata, "\n".join(lines[end + 1 :]).strip()


def parse_claude(path: Path) -> Agent:
    metadata, body = parse_frontmatter(path)
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(f"invalid Claude agent name in {path}: {name!r}")
    if not description:
        raise ValueError(f"missing Claude agent description: {path}")
    if not body:
        raise ValueError(f"missing Claude agent instructions: {path}")
    return Agent(name, description, body, metadata, path)


def parse_codex(path: Path) -> Agent:
    metadata = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = set(metadata) - ALLOWED_CODEX_FIELDS
    if unknown:
        raise ValueError(f"unsupported Codex metadata in {path}: {sorted(unknown)}")
    name = metadata.get("name")
    description = metadata.get("description")
    body = metadata.get("developer_instructions")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ValueError(f"invalid Codex agent name in {path}: {name!r}")
    if not isinstance(description, str) or not description:
        raise ValueError(f"missing Codex agent description: {path}")
    if not isinstance(body, str) or not body:
        raise ValueError(f"missing Codex agent instructions: {path}")
    return Agent(name, description, body, metadata, path)


def claude_agents(root: Path) -> dict[str, Agent]:
    agents: dict[str, Agent] = {}
    for path in sorted((root / ".claude" / "agents").rglob("*.md")):
        agent = parse_claude(path)
        if agent.name in agents:
            raise ValueError(f"duplicate Claude agent name: {agent.name}")
        agents[agent.name] = agent
    return agents


def codex_agents(root: Path) -> dict[str, Agent]:
    agents: dict[str, Agent] = {}
    for path in sorted((root / ".codex" / "agents").glob("*.toml")):
        agent = parse_codex(path)
        if path.stem != agent.name:
            raise ValueError(f"Codex filename must match agent name: {path}")
        if agent.name in agents:
            raise ValueError(f"duplicate Codex agent name: {agent.name}")
        agents[agent.name] = agent
    return agents


def validate_relative_id(relative_id: str) -> Path:
    path = Path(relative_id)
    if path.is_absolute() or ".." in path.parts or path.suffix or not path.parts:
        raise ValueError("relative agent id must stay inside the agent root and omit the extension")
    return path


def safe_target(root: Path, relative: Path) -> Path:
    if root.is_symlink():
        raise ValueError(f"agent root must not be a symlink: {root}")
    if root.parent.is_symlink():
        raise ValueError(f"agent root parent must not be a symlink: {root.parent}")
    target = root / relative
    if target.is_symlink():
        raise ValueError(f"agent path must not be a symlink: {target}")
    resolved_root = root.resolve()
    resolved_parent = target.parent.resolve()
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"agent path escapes agent root: {target}") from error
    return target


def toml_value(value: Any) -> str:
    if isinstance(value, str):
        if "\n" in value and "'''" not in value:
            return f"'''\n{value}\n'''"
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list) and all(not isinstance(item, dict) for item in value):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    raise ValueError(f"unsupported Codex metadata value: {value!r}")


def render_codex(metadata: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in ("name", "description", "developer_instructions"):
        lines.append(f"{key} = {toml_value(metadata[key])}")
    for key, value in metadata.items():
        if key not in SHARED_CODEX_FIELDS:
            lines.append(f"{key} = {toml_value(value)}")
    return "\n".join(lines) + "\n"


def render_claude(agent: Agent, existing_metadata: dict[str, str] | None = None) -> str:
    metadata = dict(existing_metadata or {})
    metadata["name"] = agent.name
    metadata["description"] = agent.description
    metadata.setdefault("model", "inherit")
    ordered = ["name", "description", *[key for key in metadata if key not in {"name", "description"}]]
    lines = ["---"]
    for key in ordered:
        value = metadata[key]
        rendered = json.dumps(value) if key == "description" else value
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", "", normalize(agent.body), ""])
    return "\n".join(lines)
