from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts/agent-config"))

from agent_formats import claude_agents, codex_agents


def test_conversation_runner_is_root_level_and_all_existing_pairs_remain_aligned() -> None:
    claude = claude_agents(REPOSITORY_ROOT)
    codex = codex_agents(REPOSITORY_ROOT)

    assert set(claude) == set(codex)
    assert len(claude) == 4
    assert claude["testagent-conversation-runner"].path == (
        REPOSITORY_ROOT / ".claude/agents/testagent-conversation-runner.md"
    )
    assert codex["testagent-conversation-runner"].path == (
        REPOSITORY_ROOT / ".codex/agents/testagent-conversation-runner.toml"
    )
    assert "hidden truth" in claude["testagent-conversation-runner"].body
    assert "exploratory" in claude["testagent-conversation-runner"].body


def test_verifier_discovers_agent_pairs_dynamically(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    shutil.copytree(
        REPOSITORY_ROOT,
        clone,
        symlinks=True,
        ignore=shutil.ignore_patterns(".git", ".venv", ".env", "__pycache__", ".pytest_cache"),
    )
    claude_source = clone / ".claude/agents/dynamic-fixture.md"
    claude_source.write_text(
        "---\nname: dynamic-fixture\ndescription: Dynamic fixture.\nmodel: inherit\n---\n\nRun the fixture.\n",
        encoding="utf-8",
    )
    sync = subprocess.run(
        [
            sys.executable,
            "scripts/agent-config/sync_agent.py",
            "--root",
            str(clone),
            "--from",
            "claude",
            "dynamic-fixture",
        ],
        cwd=clone,
        text=True,
        capture_output=True,
        check=False,
    )
    verification = subprocess.run(
        [sys.executable, "scripts/agent-config/verify_agent_config.py", "--root", str(clone)],
        cwd=clone,
        text=True,
        capture_output=True,
        check=False,
    )

    assert sync.returncode == 0, sync.stderr
    assert verification.returncode == 0, verification.stderr
    assert set(claude_agents(clone)) == set(codex_agents(clone))
    assert "dynamic-fixture" in claude_agents(clone)
