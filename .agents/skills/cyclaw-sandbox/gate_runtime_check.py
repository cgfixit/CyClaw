#!/usr/bin/env python3
"""Delegate to the maintained Sandbox gate_runtime_check.py implementation."""

from pathlib import Path
from runpy import run_path

if __name__ == "__main__":
    script = Path(__file__).resolve().parents[3] / ".claude/skills/CyClaw-Sandbox/gate_runtime_check.py"
    run_path(str(script), run_name="__main__")
