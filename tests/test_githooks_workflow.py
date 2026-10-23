"""Exercise the repository hook callbacks against disposable Git indexes."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / ".githooks"
BASH = shutil.which("bash") or ""
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not BASH, reason="needs POSIX bash")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed commands with separate arguments
        args,
        cwd=root,
        env={
            **os.environ,
            "HOME": str(root),
            "XDG_CONFIG_HOME": str(root),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_EDITOR": "true",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.fixture(params=sorted({BASH, "/bin/bash"} - {""}))
def shell(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    assert _run(tmp_path, "git", "init", "-q").returncode == 0
    (tmp_path / ".githooks").mkdir()
    shutil.copyfile(HOOKS / "security.conf", tmp_path / ".githooks/security.conf")
    return str(request.param)


def _ruff_hook(shell: str, root: Path, path: str) -> subprocess.CompletedProcess[str]:
    return _run(
        root,
        shell,
        "-euo",
        "pipefail",
        "-c",
        '. "$1"; SEC_FILES="$2"; sec_repo_pre_commit',
        "hook-probe",
        str(HOOKS / "_security.sh"),
        path,
    )


@pytest.mark.skipif(not shutil.which("ruff"), reason="needs installed Ruff")
@pytest.mark.parametrize("path", ["probe.py", "directory with spaces/probe file.py"])
@pytest.mark.parametrize(
    "staged,working,expected",
    [
        ("print(undefined_name)\n", "print(1)\n", 1),
        ("print(1)\n", "print(undefined_name)\n", 0),
        ("print(1)\n", None, 0),
        ("print(undefined_name)\n", None, 1),
    ],
    ids=[
        "bad-index-clean-worktree",
        "clean-index-bad-worktree",
        "clean-index-missing-worktree",
        "bad-index-missing-worktree",
    ],
)
def test_ruff_checks_index_bytes(
    shell: str, tmp_path: Path, path: str, staged: str, working: str | None, expected: int
) -> None:
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(staged, encoding="utf-8")
    assert _run(tmp_path, "git", "add", "--", path).returncode == 0
    if working is None:
        target.unlink()
    else:
        target.write_text(working, encoding="utf-8")
    result = _ruff_hook(shell, tmp_path, path)
    assert result.returncode == expected, result.stdout + result.stderr
    assert ("F821" in result.stdout) == bool(expected)


@pytest.mark.skipif(not shutil.which("ruff"), reason="needs installed Ruff")
def test_ruff_preserves_force_exclude(shell: str, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nextend-exclude = ["excluded.py"]\n', encoding="utf-8")
    (tmp_path / "excluded.py").write_text("print(undefined_name)\n", encoding="utf-8")
    assert _run(tmp_path, "git", "add", "excluded.py").returncode == 0
    result = _ruff_hook(shell, tmp_path, "excluded.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_commit_msg_accepts_git_generated_amend(shell: str, tmp_path: Path) -> None:
    git = ("git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com")
    assert _run(tmp_path, *git, "commit", "--allow-empty", "-qm", "[fix] - original").returncode == 0
    (tmp_path / ".git/hooks/commit-msg").symlink_to(HOOKS / "commit-msg")
    result = _run(tmp_path, *git, "commit", "--fixup=amend:HEAD", "--no-edit")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _run(tmp_path, "git", "log", "-1", "--format=%s").stdout.strip() == "amend! [fix] - original"


def test_deleted_invariant_input_still_runs_repo_check(shell: str, tmp_path: Path) -> None:
    git = ("git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com")
    (tmp_path / "gate.py").write_text("print(1)\n", encoding="utf-8")
    guard = tmp_path / ".claude/skills/invariant-guard/check_invariants.py"
    guard.parent.mkdir(parents=True)
    guard.write_text('raise SystemExit("INVARIANT_PROBE_RAN")\n', encoding="utf-8")
    assert _run(tmp_path, "git", "add", "gate.py", str(guard.relative_to(tmp_path))).returncode == 0
    assert _run(tmp_path, *git, "commit", "-qm", "initial").returncode == 0
    base = _run(tmp_path, "git", "rev-parse", "HEAD").stdout.strip()
    assert _run(tmp_path, "git", "rm", "gate.py").returncode == 0
    assert _run(tmp_path, *git, "commit", "-qm", "remove core file").returncode == 0
    result = _run(
        tmp_path,
        shell,
        "-euo",
        "pipefail",
        "-c",
        '. "$1"; rc=0; '
        'sec_pre_push_ref origin refs/heads/codex/probe "$(git rev-parse HEAD)" refs/heads/codex/probe "$2" || rc=1; '
        'sec_pre_push_finish || rc=1; printf "files=[%s]\\n" "$SEC_FILES"; exit "$rc"',
        "hook-probe",
        str(HOOKS / "_security.sh"),
        base,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "files=[gate.py]" in result.stdout
    assert "INVARIANT_PROBE_RAN" in result.stderr
