#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from agent_formats import (
    SHARED_CODEX_FIELDS,
    parse_claude,
    parse_codex,
    parse_frontmatter,
    render_claude,
    render_codex,
    safe_target,
    validate_relative_id,
)


def repository_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError("unable to resolve repository root")
    return Path(result.stdout.strip()).resolve()


def sync_from_claude(root: Path, relative_id: Path) -> None:
    claude_path = safe_target(root / ".claude" / "agents", relative_id.with_suffix(".md"))
    agent = parse_claude(claude_path)
    codex_path = safe_target(root / ".codex" / "agents", Path(f"{agent.name}.toml"))
    metadata = {"model": "gpt-5"}
    if codex_path.exists():
        metadata = {key: value for key, value in parse_codex(codex_path).metadata.items() if key not in SHARED_CODEX_FIELDS}
    metadata.update(name=agent.name, description=agent.description, developer_instructions=agent.body)
    codex_path.parent.mkdir(parents=True, exist_ok=True)
    codex_path.write_text(render_codex(metadata), encoding="utf-8")


def sync_from_codex(root: Path, relative_id: Path) -> None:
    name = relative_id.name
    codex_path = safe_target(root / ".codex" / "agents", Path(f"{name}.toml"))
    agent = parse_codex(codex_path)
    matches = list((root / ".claude" / "agents").rglob(f"{name}.md"))
    if len(matches) > 1:
        raise ValueError(f"multiple Claude agents match {name}; provide unique agent names")
    claude_relative = relative_id.with_suffix(".md") if not matches else matches[0].relative_to(root / ".claude" / "agents")
    claude_path = safe_target(root / ".claude" / "agents", claude_relative)
    existing = parse_frontmatter(claude_path)[0] if claude_path.exists() else None
    claude_path.parent.mkdir(parents=True, exist_ok=True)
    claude_path.write_text(render_claude(agent, existing), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    parser.add_argument("--from", dest="source", required=True)
    parser.add_argument("relative_id")
    arguments = parser.parse_args()
    try:
        root = repository_root(arguments.root)
        relative_id = validate_relative_id(arguments.relative_id)
        if arguments.source == "claude":
            sync_from_claude(root, relative_id)
        elif arguments.source == "codex":
            sync_from_codex(root, relative_id)
        else:
            raise ValueError("--from must be claude or codex")
    except (OSError, UnicodeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
