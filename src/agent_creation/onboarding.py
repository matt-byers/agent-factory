from __future__ import annotations

import os
from pathlib import Path
import tempfile


ENVIRONMENT_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


class OnboardingError(ValueError):
    pass


def environment_status(path: Path) -> dict[str, bool]:
    values = _read_values(path)
    return {name: bool(values.get(name, "").strip()) for name in ENVIRONMENT_NAMES}


def set_environment_value(path: Path, name: str, value: str) -> None:
    if name not in ENVIRONMENT_NAMES:
        raise OnboardingError(f"unsupported environment variable: {name}")
    if "\n" in value or "\r" in value:
        raise OnboardingError("environment values must be single-line")
    if not value:
        raise OnboardingError("environment value must not be empty")

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{name}={value}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{name}="):
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        updated.append(replacement)

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(updated) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        temporary_path.replace(path)
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        values[name] = value
    return values
