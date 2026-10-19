#!/usr/bin/env python3
"""Reuse the maintained terminal probe and preserve its importable main."""

from pathlib import Path
from runpy import run_path

script = Path(__file__).resolve().parents[3] / ".claude/skills/CyClaw-Sandbox/terminal_emulation.py"
main = run_path(str(script))["main"]

if __name__ == "__main__":
    raise SystemExit(main())
