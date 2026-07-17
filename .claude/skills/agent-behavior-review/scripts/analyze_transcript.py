#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from agent_creation.behavior_improvement import (
    analyze_testagent_transcript,
    render_transcript_analysis,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    arguments = parser.parse_args()
    try:
        print(render_transcript_analysis(analyze_testagent_transcript(arguments.transcript)), end="")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"analyze-transcript: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
