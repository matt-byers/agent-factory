from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.onboarding import (
    OnboardingError,
    environment_status,
    set_environment_value,
)


def test_environment_values_are_set_one_at_a_time_without_losing_existing_content(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=old\nCUSTOM_VALUE=preserved\n", encoding="utf-8")

    set_environment_value(env_file, "ANTHROPIC_API_KEY", "new-secret")
    set_environment_value(env_file, "LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

    assert env_file.read_text(encoding="utf-8") == (
        "ANTHROPIC_API_KEY=new-secret\n"
        "CUSTOM_VALUE=preserved\n"
        "LANGFUSE_BASE_URL=https://cloud.langfuse.com\n"
    )
    assert env_file.stat().st_mode & 0o777 == 0o600


def test_environment_status_reports_presence_without_returning_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    secret = "secret-that-must-not-be-returned"
    env_file.write_text(
        f"ANTHROPIC_API_KEY={secret}\nOPENAI_API_KEY=\n",
        encoding="utf-8",
    )

    status = environment_status(env_file)

    assert status["ANTHROPIC_API_KEY"] is True
    assert status["OPENAI_API_KEY"] is False
    assert secret not in repr(status)


def test_environment_writer_rejects_unknown_names_and_multiline_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    with pytest.raises(OnboardingError, match="unsupported environment variable"):
        set_environment_value(env_file, "UNRELATED_SECRET", "value")
    with pytest.raises(OnboardingError, match="single-line"):
        set_environment_value(env_file, "OPENAI_API_KEY", "first\nsecond")


def test_onboard_skill_guides_credentials_flows_and_handoff() -> None:
    skill = (REPOSITORY_ROOT / ".claude/skills/onboard/SKILL.md").read_text(encoding="utf-8")

    assert "one at a time" in skill
    assert "Never ask the user to paste" in skill
    assert "https://platform.claude.com/settings/keys" in skill
    assert "https://platform.openai.com/api-keys" in skill
    assert "https://aistudio.google.com/app/apikey" in skill
    assert "https://langfuse.com/docs/observability/get-started" in skill
    assert "Initial agent setup" in skill
    assert "Evals-led self-improvement" in skill
    assert "invoke `/agent-lifecycle-orchestrator`" in skill
    assert "Do not build or modify the target agent" in skill


def test_onboard_status_command_never_prints_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    secret = "command-secret-that-must-not-leak"
    env_file.write_text(f"ANTHROPIC_API_KEY={secret}\n", encoding="utf-8")

    result = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/agent-onboard"),
            "--env-file",
            str(env_file),
            "status",
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"ANTHROPIC_API_KEY": true' in result.stdout
    assert secret not in result.stdout + result.stderr


def test_readme_routes_new_clones_through_onboard() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Invoke `/onboard`" in readme
    assert "onboard/" in readme
