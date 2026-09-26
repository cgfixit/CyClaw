"""The SessionStart hook leaves Claude Code's commit identity to the runtime.

``.claude/hooks/session-start-sync-check.sh`` used to pin every session to
``CyClaw Agent <cyclaw-agent@users.noreply.github.com>``. On the cloud runtime
that overrode ``Claude <noreply@anthropic.com>``, the identity the runtime
signs commits for, so every commit showed as Unverified on GitHub. The hook
now removes only its own old pin, keeps an identity someone set on purpose,
and still pins one when the ``CYCLAW_AGENT_COMMIT_*`` overrides are set.

Runs the real script in a throwaway repository with no remote, so the fetch
step reports "offline" and nothing leaves the machine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "session-start-sync-check.sh"
_LEGACY_EMAIL = "cyclaw-agent@users.noreply.github.com"
_LEGACY_NAME = "CyClaw Agent"
# Absolute paths, resolved once: the argv below is fixed and pytest-owned.
_BASH = shutil.which("bash") or ""
_GIT = shutil.which("git") or ""

pytestmark = pytest.mark.skipif(
    os.name == "nt" or not _BASH or not _GIT,
    reason="the hook is a bash script run by Claude Code on POSIX hosts",
)


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CYCLAW_AGENT_COMMIT_"))}
    # Keep the developer's own global/system git config out of the test.
    empty = tmp_path / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    env.update(GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM="1", **extra)
    return env


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([_GIT, "init", "-q", str(repo)], check=True, env=_env(tmp_path))  # noqa: S603 - fixed argv
    return repo


def _local(repo: Path, tmp_path: Path, key: str) -> str | None:
    out = subprocess.run([_GIT, "-C", str(repo), "config", "--local", "--get", key],  # noqa: S603 - fixed argv
                         capture_output=True, text=True, env=_env(tmp_path), check=False)
    return out.stdout.strip() if out.returncode == 0 else None


def _set(repo: Path, tmp_path: Path, key: str, value: str) -> None:
    subprocess.run([_GIT, "-C", str(repo), "config", "--local", key, value],  # noqa: S603 - fixed argv
                   check=True, env=_env(tmp_path))


def _run_hook(repo: Path, tmp_path: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_BASH, str(_HOOK)], cwd=repo, capture_output=True, text=True,  # noqa: S603 - fixed argv
                          env=_env(tmp_path, **extra), check=False, timeout=60)


def test_the_old_cyclaw_agent_pin_is_removed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _set(repo, tmp_path, "user.email", _LEGACY_EMAIL)
    _set(repo, tmp_path, "user.name", _LEGACY_NAME)
    result = _run_hook(repo, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _local(repo, tmp_path, "user.email") is None
    assert _local(repo, tmp_path, "user.name") is None


def test_no_identity_is_pinned_by_default(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = _run_hook(repo, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _local(repo, tmp_path, "user.email") is None
    assert _local(repo, tmp_path, "user.name") is None


def test_an_identity_set_on_purpose_is_left_alone(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _set(repo, tmp_path, "user.email", "someone@example.com")
    _set(repo, tmp_path, "user.name", "Someone")
    assert _run_hook(repo, tmp_path).returncode == 0
    assert _local(repo, tmp_path, "user.email") == "someone@example.com"
    assert _local(repo, tmp_path, "user.name") == "Someone"


def test_only_the_old_default_name_is_removed_with_the_old_email(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _set(repo, tmp_path, "user.email", _LEGACY_EMAIL)
    _set(repo, tmp_path, "user.name", "Someone")
    assert _run_hook(repo, tmp_path).returncode == 0
    assert _local(repo, tmp_path, "user.email") is None
    assert _local(repo, tmp_path, "user.name") == "Someone"


def test_explicit_overrides_still_pin(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = _run_hook(repo, tmp_path, CYCLAW_AGENT_COMMIT_EMAIL="bot@example.com",
                       CYCLAW_AGENT_COMMIT_NAME="Bot")
    assert result.returncode == 0, result.stderr
    assert _local(repo, tmp_path, "user.email") == "bot@example.com"
    assert _local(repo, tmp_path, "user.name") == "Bot"


def test_the_hook_reports_the_identity_and_never_blocks_offline(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = _run_hook(repo, tmp_path, CYCLAW_AGENT_COMMIT_EMAIL="bot@example.com",
                       CYCLAW_AGENT_COMMIT_NAME="Bot")
    assert result.returncode == 0
    assert "Commits will be authored as: Bot <bot@example.com>" in result.stdout
    assert "Could not fetch" in result.stdout
