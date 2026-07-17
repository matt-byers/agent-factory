#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CURRENT="$(git -C "$ROOT" config --local --get core.hooksPath || true)"

if [[ -n "$CURRENT" && "$CURRENT" != ".githooks" && "$CURRENT" != "$ROOT/.githooks" ]]; then
  printf 'refusing to replace existing core.hooksPath: %s\n' "$CURRENT" >&2
  exit 1
fi

git -C "$ROOT" config --local core.hooksPath .githooks
printf 'installed repository pre-commit gate\n'
