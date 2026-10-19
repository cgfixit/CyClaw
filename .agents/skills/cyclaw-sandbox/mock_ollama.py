#!/usr/bin/env python3
"""Run the maintained socket mock through the Codex sandbox entry point."""

from pathlib import Path
from runpy import run_path

if __name__ == "__main__":
    script = Path(__file__).resolve().parents[3] / ".claude/skills/CyClaw-Sandbox/mock_ollama.py"
    run_path(str(script), run_name="__main__")
