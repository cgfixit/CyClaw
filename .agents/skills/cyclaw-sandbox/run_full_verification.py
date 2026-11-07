#!/usr/bin/env python3
"""Delegate to the maintained Sandbox run_full_verification.py implementation."""

from pathlib import Path
from runpy import run_path

if __name__ == "__main__":
    script = Path(__file__).resolve().parents[3] / ".claude/skills/CyClaw-Sandbox/run_full_verification.py"
    run_path(str(script), run_name="__main__")
