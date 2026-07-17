#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

from agent_formats import claude_agents, codex_agents, normalize


ABSOLUTE_MACHINE_PATH = re.compile(r"/(?:Users|home)/[^/\s]+/")


def repository_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError("unable to resolve repository root")
    return Path(result.stdout.strip()).resolve()


def verify(root: Path) -> list[str]:
    errors: list[str] = []
    manual = root / "AGENTS.md"
    skills = root / ".agents" / "skills"
    if not manual.is_symlink() or manual.readlink() != Path("CLAUDE.md"):
        errors.append("manual symlink AGENTS.md must target CLAUDE.md")
    if not skills.is_symlink() or skills.readlink() != Path("../.claude/skills") or not skills.exists():
        errors.append("skills symlink .agents/skills must target ../.claude/skills")

    seen_skills: set[str] = set()
    for path in sorted((root / ".claude" / "skills").glob("*/SKILL.md")):
        try:
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            if not lines or lines[0] != "---" or "---" not in lines[1:]:
                raise ValueError("invalid frontmatter")
            end = lines.index("---", 1)
            match = re.search(r"(?m)^name:\s*([^\n]+)$", "\n".join(lines[1:end]))
            description = re.search(r"(?m)^description:\s*(\S.*)$", "\n".join(lines[1:end]))
            if match is None or match.group(1).strip(' "\'') != path.parent.name:
                raise ValueError("skill name must match its directory")
            name = match.group(1).strip(' "\'')
            if name in seen_skills:
                raise ValueError("duplicate skill name")
            seen_skills.add(name)
            if description is None:
                raise ValueError("missing skill description")
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"skill invalid: {path.relative_to(root)}: {error}")

    try:
        claude = claude_agents(root)
        codex = codex_agents(root)
        for name in sorted(set(claude) - set(codex)):
            errors.append(f"missing Codex pair for agent:{name}")
        for name in sorted(set(codex) - set(claude)):
            errors.append(f"missing Claude pair for agent:{name}")
        for name in sorted(set(claude) & set(codex)):
            left = claude[name]
            right = codex[name]
            if normalize(left.description) != normalize(right.description):
                errors.append(f"description mismatch for agent:{name}")
            if normalize(left.body) != normalize(right.body):
                errors.append(f"body mismatch for agent:{name}")
    except (OSError, UnicodeError, ValueError) as error:
        errors.append(str(error))

    scan_roots = [root / "CLAUDE.md", root / ".claude", root / ".codex", root / "scripts"]
    for scan_root in scan_roots:
        paths = [scan_root] if scan_root.is_file() else scan_root.rglob("*") if scan_root.exists() else []
        for path in paths:
            if path.is_file() and path.suffix in {".md", ".py", ".toml", ".sh", ""}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if ABSOLUTE_MACHINE_PATH.search(text):
                    errors.append(f"absolute machine path in {path.relative_to(root)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    arguments = parser.parse_args()
    try:
        root = repository_root(arguments.root)
        errors = verify(root)
    except (OSError, UnicodeError, ValueError) as error:
        errors = [str(error)]
    if errors:
        for error in errors:
            print(f"RED: {error}", file=sys.stderr)
        return 1
    print("AGENT-CONFIG GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
