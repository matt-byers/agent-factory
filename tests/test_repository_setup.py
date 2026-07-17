from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run(*command: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def copy_repository(destination: Path) -> Path:
    ignored = shutil.ignore_patterns(".git", ".venv", ".env", "__pycache__", ".pytest_cache")
    shutil.copytree(REPOSITORY_ROOT, destination, symlinks=True, ignore=ignored)
    result = run("git", "init", "-q", cwd=destination)
    assert result.returncode == 0, result.stderr
    return destination


def write_claude_agent(root: Path, relative_id: str = "review/example") -> Path:
    path = root / ".claude" / "agents" / f"{relative_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            """\
            ---
            name: example
            description: "Review an example agent boundary."
            model: inherit
            ---

            Review the supplied change and return evidence.
            """
        ),
        encoding="utf-8",
    )
    return path


def test_clean_clone_setup_discovers_shared_manual_skills_and_agents(tmp_path: Path) -> None:
    clone = copy_repository(tmp_path / "clone")

    result = run("scripts/agent-setup", "--skip-dependencies", cwd=clone)

    assert result.returncode == 0, result.stderr
    assert (clone / "AGENTS.md").is_symlink()
    assert (clone / "AGENTS.md").readlink() == Path("CLAUDE.md")
    assert (clone / ".agents" / "skills").is_symlink()
    assert (clone / ".agents" / "skills").readlink() == Path("../.claude/skills")
    claude_skills = sorted(path.parent.name for path in (clone / ".claude" / "skills").glob("*/SKILL.md"))
    codex_skills = sorted(path.parent.name for path in (clone / ".agents" / "skills").glob("*/SKILL.md"))
    assert claude_skills == codex_skills
    assert sorted(path.stem for path in (clone / ".codex" / "agents").glob("*.toml"))
    assert (clone / ".env").read_text(encoding="utf-8") == (clone / ".env.example").read_text(encoding="utf-8")
    assert run("git", "config", "--local", "--get", "core.hooksPath", cwd=clone).stdout.strip() == ".githooks"
    verification = run(sys.executable, "scripts/agent-config/verify_agent_config.py", cwd=clone)
    assert verification.returncode == 0, verification.stderr
    assert "AGENT-CONFIG GREEN" in verification.stdout


def test_setup_is_idempotent_preserves_env_and_redacts_secret_values(tmp_path: Path) -> None:
    clone = copy_repository(tmp_path / "clone")
    secret = "unit-test-secret-that-must-not-leak"
    (clone / ".env").write_text(f"ANTHROPIC_API_KEY={secret}\n", encoding="utf-8")

    first = run("scripts/agent-setup", "--skip-dependencies", cwd=clone)
    second = run("scripts/agent-setup", "--skip-dependencies", cwd=clone)

    assert first.returncode == second.returncode == 0
    assert (clone / ".env").read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY={secret}\n"
    combined_output = first.stdout + first.stderr + second.stdout + second.stderr
    assert secret not in combined_output


def test_skill_symlink_is_write_through_and_verifier_rejects_breakage(tmp_path: Path) -> None:
    clone = copy_repository(tmp_path / "clone")
    setup = run("scripts/agent-setup", "--skip-dependencies", cwd=clone)
    assert setup.returncode == 0, setup.stderr
    fixture_skill = clone / ".claude" / "skills" / "fixture-skill" / "SKILL.md"
    fixture_skill.parent.mkdir(parents=True)
    fixture_skill.write_text(
        "---\nname: fixture-skill\ndescription: Exercise shared skill discovery.\n---\n\nUse the fixture.\n",
        encoding="utf-8",
    )
    skill = next((clone / ".claude" / "skills").glob("*/SKILL.md"))
    adapter_skill = clone / ".agents" / "skills" / skill.parent.name / "SKILL.md"

    marker = "\nShared adapter write-through marker.\n"
    adapter_skill.write_text(adapter_skill.read_text(encoding="utf-8") + marker, encoding="utf-8")
    assert skill.read_text(encoding="utf-8").endswith(marker)

    (clone / ".agents" / "skills").unlink()
    (clone / ".agents" / "skills").symlink_to("../missing-skills")
    verification = run(sys.executable, "scripts/agent-config/verify_agent_config.py", cwd=clone)
    assert verification.returncode != 0
    assert "skills symlink" in verification.stderr


def test_agent_sync_is_bidirectional_and_preserves_provider_metadata(tmp_path: Path) -> None:
    clone = copy_repository(tmp_path / "clone")
    claude_path = write_claude_agent(clone)

    from_claude = run(
        sys.executable,
        "scripts/agent-config/sync_agent.py",
        "--from",
        "claude",
        "review/example",
        cwd=clone,
    )

    assert from_claude.returncode == 0, from_claude.stderr
    codex_path = clone / ".codex" / "agents" / "example.toml"
    codex = codex_path.read_text(encoding="utf-8")
    assert 'name = "example"' in codex
    assert "Review the supplied change and return evidence." in codex
    codex_path.write_text(
        codex.replace(
            'description = "Review an example agent boundary."',
            'description = "Review an updated boundary."',
        ).replace(
            "Review the supplied change and return evidence.",
            "Review updated instructions and return evidence.",
        )
        + 'sandbox_mode = "read-only"\n',
        encoding="utf-8",
    )

    from_codex = run(
        sys.executable,
        "scripts/agent-config/sync_agent.py",
        "--from",
        "codex",
        "review/example",
        cwd=clone,
    )

    assert from_codex.returncode == 0, from_codex.stderr
    claude = claude_path.read_text(encoding="utf-8")
    assert 'description: "Review an updated boundary."' in claude
    assert "Review updated instructions and return evidence." in claude
    assert "model: inherit" in claude


def test_agent_sync_rejects_symlinked_provider_parent(tmp_path: Path) -> None:
    clone = copy_repository(tmp_path / "clone")
    write_claude_agent(clone)
    shutil.rmtree(clone / ".codex")
    outside = tmp_path / "outside-codex"
    (outside / "agents").mkdir(parents=True)
    (clone / ".codex").symlink_to(outside, target_is_directory=True)

    result = run(
        sys.executable,
        "scripts/agent-config/sync_agent.py",
        "--from",
        "claude",
        "review/example",
        cwd=clone,
    )

    assert result.returncode != 0
    assert "parent must not be a symlink" in result.stderr
    assert not (outside / "agents" / "example.toml").exists()


@pytest.mark.parametrize("mutation,diagnostic", [("missing", "missing Codex pair"), ("stale", "body mismatch")])
def test_verifier_rejects_missing_and_stale_agent_pairs(
    tmp_path: Path, mutation: str, diagnostic: str
) -> None:
    clone = copy_repository(tmp_path / "clone")
    setup = run("scripts/agent-setup", "--skip-dependencies", cwd=clone)
    assert setup.returncode == 0, setup.stderr
    codex_path = next((clone / ".codex" / "agents").glob("*.toml"))
    if mutation == "missing":
        codex_path.unlink()
    else:
        codex_path.write_text(
            codex_path.read_text(encoding="utf-8").replace(
                "Return", "Silently ignore", 1
            ),
            encoding="utf-8",
        )

    verification = run(sys.executable, "scripts/agent-config/verify_agent_config.py", cwd=clone)

    assert verification.returncode != 0
    assert diagnostic.lower() in verification.stderr.lower()


def test_precommit_rejects_staged_agent_drift_but_ignores_unrelated_files(tmp_path: Path) -> None:
    clone = copy_repository(tmp_path / "clone")
    setup = run("scripts/agent-setup", "--skip-dependencies", cwd=clone)
    assert setup.returncode == 0, setup.stderr
    unrelated = clone / "ordinary.txt"
    unrelated.write_text("ordinary\n", encoding="utf-8")
    assert run("git", "add", "ordinary.txt", cwd=clone).returncode == 0
    ordinary_hook = run(".githooks/pre-commit", cwd=clone)
    assert ordinary_hook.returncode == 0, ordinary_hook.stderr
    assert run("git", "reset", "-q", cwd=clone).returncode == 0

    codex_path = next((clone / ".codex" / "agents").glob("*.toml"))
    codex_path.write_text(
        codex_path.read_text(encoding="utf-8").replace("Return", "Silently ignore", 1),
        encoding="utf-8",
    )
    assert run("git", "add", str(codex_path.relative_to(clone)), cwd=clone).returncode == 0

    drift_hook = run(".githooks/pre-commit", cwd=clone)

    assert drift_hook.returncode != 0
    assert "mismatch" in drift_hook.stderr.lower()


def test_readme_contains_clone_setup_repository_shape_and_lifecycle() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "scripts/agent-setup" in readme
    assert "```text" in readme and "self-improving-agent-template/" in readme
    assert "```mermaid" in readme
    assert "First build" in readme
    assert "Continuous improvement" in readme
    assert "--from claude live-transcript-reviewer" in readme
    assert "behavior-review/live-transcript-reviewer" not in readme


def test_environment_contract_is_generic_and_ignored() -> None:
    example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    ignored = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    expected = {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "LANGSMITH_API_KEY",
        "LANGSMITH_ENDPOINT",
        "LANGSMITH_WORKSPACE_ID",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
    }
    names = {line.split("=", 1)[0] for line in example.splitlines() if "=" in line}
    assert names == expected
    assert ".env" in ignored
    assert ".env.example" not in ignored
    assert not ({"SUPABASE_URL", "JWT_SECRET", "REDIS_URL", "SENTRY_DSN"} & names)


def test_no_absolute_machine_paths_or_secret_values_are_committed() -> None:
    forbidden_values = {value for key, value in os.environ.items() if key.endswith(("_API_KEY", "_SECRET_KEY")) and value}
    scanned = [
        path
        for path in REPOSITORY_ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    ]

    for path in scanned:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert ("/" + "Users/") not in text, path
        assert not any(secret in text for secret in forbidden_values), path
