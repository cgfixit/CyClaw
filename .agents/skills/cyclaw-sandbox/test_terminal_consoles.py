#!/usr/bin/env python3
"""Delegate to the maintained Sandbox test_terminal_consoles.py implementation."""

from pathlib import Path
from runpy import run_path

if __name__ == "__main__":
    script = Path(__file__).resolve().parents[3] / ".claude/skills/CyClaw-Sandbox/test_terminal_consoles.py"
    run_path(str(script), run_name="__main__")
