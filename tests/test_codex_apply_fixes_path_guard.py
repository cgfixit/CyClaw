"""Regression contract for codex-apply-fixes.yml's patch path guard (#1709 item 6A).

The publish job applies a bot-generated patch and, before committing it, runs an
embedded Python check over the changed paths and their index modes. These tests
extract that exact script from the workflow and run it against synthetic path
lists, so a protected path that slips out of the deny list fails here.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "codex-apply-fixes.yml"


def _guard_script() -> str:
    steps = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["publish"]["steps"]
    run = next(step for step in steps if step.get("id") == "prepare")["run"]
    body = run.split("<<'PYCODE'\n", 1)[1].split("\nPYCODE", 1)[0]
    return textwrap.dedent(body)


def _run_guard(tmp_path: Path, paths: list[str], mode: str = "100644") -> subprocess.CompletedProcess[str]:
    changed = tmp_path / "changed-paths"
    modes = tmp_path / "index-modes"
    changed.write_bytes(b"".join(p.encode() + b"\0" for p in paths))
    modes.write_bytes(b"".join(f"{mode} {'0' * 40} 0\t{p}".encode() + b"\0" for p in paths))
    script = tmp_path / "guard.py"
    script.write_text(_guard_script(), encoding="utf-8")
    return subprocess.run(  # noqa: S603 -- the workflow's own embedded script on synthetic input
        [sys.executable, "-I", str(script), str(changed), str(modes)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    "path",
    [
        "gate.py",
        "utils/health.py",
        "tests/test_health.py",
        "docs/README.md",
        ".claude/skills/doc-sync/SKILL.md",
        "github/notes.md",
        "constraints.txt",
    ],
)
def test_ordinary_paths_pass(tmp_path: Path, path: str) -> None:
    result = _run_guard(tmp_path, [path])
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/dependabot.yml",
        ".githooks/pre-push",
        ".codex/prompts/pr-apply-fixes.md",
        ".claude/hooks/session-start-sync-check.sh",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".mcp.json",
        "locks/requirements-lock-linux.txt",
        "data/personality/soul.md",
        "utils/sanitizer.py",
        "gate_auth.py",
        ".gitleaksignore",
        ".trivyignore.yaml",
        ".osv-scanner.toml",
        ".claude/skills/dotenv-guard/baseline.txt",
    ],
)
def test_protected_paths_are_refused(tmp_path: Path, path: str) -> None:
    result = _run_guard(tmp_path, ["gate.py", path])
    assert result.returncode != 0
    assert f"Refusing protected patch path: {path}" in result.stderr


@pytest.mark.parametrize("path", [".env", "config/.env.local", "certs/server.pem", ".git/config"])
def test_existing_secret_like_refusals_still_hold(tmp_path: Path, path: str) -> None:
    result = _run_guard(tmp_path, [path])
    assert result.returncode != 0
    assert "Refusing secret-like or Git metadata patch path" in result.stderr


def test_symlink_mode_is_still_refused(tmp_path: Path) -> None:
    result = _run_guard(tmp_path, ["docs/link.md"], mode="120000")
    assert result.returncode != 0
    assert "Refusing symlink/submodule patch" in result.stderr
