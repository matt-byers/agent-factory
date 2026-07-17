#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

cd "$ROOT"
"$PYTHON" scripts/agent-config/verify_agent_config.py
"$PYTHON" -m pytest -q tests/test_repository_setup.py
printf 'TEST-AGENT-CONFIG GREEN\n'
