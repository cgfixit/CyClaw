"""Repo-tree hygiene guards that no other checker owns.

Lives in tests/ rather than a skill or a workflow step on purpose: the three
`test` legs are release gates, while `lint.yml` is advisory end-to-end
(continue-on-error on both linters AND the job) and the `verify-skills` matrix
is continue-on-error too. A guard that must actually block a merge has to run
here.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Built at runtime instead of written literally so this file does not match its
# own guard. Only the angle-bracket markers are searched: the third marker git
# writes is a bare row of seven '=', which is also how Markdown underlines a
# setext H1 -- matching it would fail on ordinary prose. A conflict cannot be
# committed without the angle-bracket pair, so these two are sufficient.
_OPEN_MARKER = "<" * 7 + " "
_CLOSE_MARKER = ">" * 7 + " "

# Reading every tracked blob is wasteful; a conflict marker only survives in
# something a human edits as text. Anything else is skipped by extension.
_TEXT_SUFFIXES = frozenset(
    {
        ".cfg", ".css", ".env", ".html", ".ini", ".js", ".json", ".jsonl",
        ".md", ".ndjson", ".ps1", ".py", ".rst", ".sh", ".toml", ".txt",
        ".yaml", ".yml",
    }
)


def _tracked_text_files() -> list[Path]:
    """Tracked files with a text suffix, via git so ignored/untracked junk is excluded."""
    git_exe = shutil.which("git")
    if git_exe is None:
        pytest.skip("git executable not found on PATH")
    try:
        out = subprocess.run(  # noqa: S603
            [git_exe, "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git unavailable or this is not a git checkout")
        raise
    return [
        REPO_ROOT / rel
        for rel in out.split("\0")
        if rel and Path(rel).suffix.lower() in _TEXT_SUFFIXES
    ]


def test_no_unresolved_conflict_markers_in_tracked_text_files() -> None:
    """A committed merge conflict must fail CI rather than ship.

    Regression: setup-guide.md reached main carrying a raw conflict block --
    the shipped setup guide rendered literal markers to readers -- and every
    gate stayed green because nothing looked for them.
    """
    offenders: list[str] = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.startswith(_OPEN_MARKER) or line.startswith(_CLOSE_MARKER):
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}: {line[:60]}")

    assert not offenders, "unresolved merge conflict markers found:\n" + "\n".join(offenders)


# Characters Windows forbids in a path component, plus the reserved device
# names. A tracked path containing any of these cannot be checked out on a
# Windows runner at all: `git checkout` aborts with "error: invalid path" and
# exit 128, so all three Windows legs die before a single test body runs.
_WINDOWS_FORBIDDEN_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)


def _tracked_paths() -> list[str]:
    git_exe = shutil.which("git")
    if git_exe is None:
        pytest.skip("git executable not found on PATH")
    out = subprocess.run(  # noqa: S603
        [git_exe, "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [rel for rel in out.split("\0") if rel]


def test_no_tracked_path_is_uncheckoutable_on_windows() -> None:
    """A path Windows cannot create must never reach a tracked tree.

    Regression: a test fixture passed sqlite's ":memory:" sentinel as a
    db_path, but memory.store.connect treats db_path as a filesystem path and
    creates it -- so a zero-byte file literally named ":memory:" appeared in the
    repo root and a `git add -A` committed it. Linux and macOS did not care;
    all three Windows jobs failed identically in `git checkout` with
    "error: invalid path ':memory:'", ten seconds in, before any test ran.

    Nothing caught it locally, because the whole suite is green on a machine
    whose filesystem accepts the name. This guard is the missing check: it runs
    on every platform and fails on the tracked path list alone.
    """
    offenders: list[str] = []
    for rel in _tracked_paths():
        for component in rel.split("/"):
            bad = sorted(_WINDOWS_FORBIDDEN_CHARS & set(component))
            if bad:
                offenders.append(f"{rel}  (forbidden on Windows: {''.join(bad)})")
                break
            # "NUL", "nul.txt" and "NUL.tar.gz" are all reserved; the check is
            # on the first dot-separated segment, case-insensitively.
            if component.split(".")[0].lower() in _WINDOWS_RESERVED_STEMS:
                offenders.append(f"{rel}  (reserved Windows device name)")
                break

    assert not offenders, (
        "tracked paths that Windows cannot check out:\n" + "\n".join(offenders)
    )


_README_TEST_COUNT = re.compile(r"\((\d+)\s+`test_\*\.py` files")


def test_tests_readme_test_file_count_matches_tree() -> None:
    """tests/README.md suite-count integer must match find tests -name 'test_*.py'.

    Regression: the lede was bumped 181→183, then 194→209 on #1214, then left
    stale again after later test files (including tests/nemo_runtime/) landed.
    `ls tests/test_*.py` misses nested files that pytest testpaths=["tests"]
    still collects. Count recursively; put new guards in this file so the
    integer does not move just because the pin exists.
    """
    readme = (REPO_ROOT / "tests" / "README.md").read_text(encoding="utf-8")
    match = _README_TEST_COUNT.search(readme)
    assert match, (
        "tests/README.md must state '(N `test_*.py` files' in the lede so the "
        "count can be pinned"
    )
    claimed = int(match.group(1))
    actual = sum(
        1
        for path in (REPO_ROOT / "tests").rglob("test_*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )
    assert claimed == actual, (
        f"tests/README.md claims {claimed} test_*.py files; "
        f"find tests -name 'test_*.py' is {actual}. "
        f"Count recursively (including tests/nemo_runtime/), not ls tests/test_*.py."
    )


# ---------------------------------------------------------------------------
# The SessionStart hook leaves Claude Code's commit identity to the runtime.
#
# .claude/hooks/session-start-sync-check.sh used to pin every session to
# CyClaw Agent <cyclaw-agent@users.noreply.github.com>. On the cloud runtime
# that overrode Claude <noreply@anthropic.com>, the identity the runtime signs
# commits for, so every commit showed as Unverified on GitHub. The hook now
# removes only its own old pin, keeps an identity someone set on purpose, and
# pins nothing, CYCLAW_AGENT_COMMIT_* included (those set CyClaw's own
# agentic-loop identity). These run the real script in a throwaway repo with no
# remote, so the fetch step reports "offline" and nothing leaves the machine.
# ---------------------------------------------------------------------------

_SYNC_HOOK = REPO_ROOT / ".claude" / "hooks" / "session-start-sync-check.sh"
_LEGACY_EMAIL = "cyclaw-agent@users.noreply.github.com"
_LEGACY_NAME = "CyClaw Agent"
# Absolute paths, resolved once: the argv below is fixed and pytest-owned.
_BASH = shutil.which("bash") or ""
_GIT = shutil.which("git") or ""
_needs_posix_bash_and_git = pytest.mark.skipif(
    os.name == "nt" or not _BASH or not _GIT,
    reason="the hook is a bash script run by Claude Code on POSIX hosts",
)


def _hook_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CYCLAW_AGENT_COMMIT_"))}
    # Keep the developer's own global/system git config out of the test.
    empty = tmp_path / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    env.update(GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM="1", **extra)
    return env


def _hook_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([_GIT, "init", "-q", str(repo)], check=True, env=_hook_env(tmp_path))  # noqa: S603 - fixed argv
    return repo


def _local_git_config(repo: Path, tmp_path: Path, key: str) -> str | None:
    out = subprocess.run([_GIT, "-C", str(repo), "config", "--local", "--get", key],  # noqa: S603 - fixed argv
                         capture_output=True, text=True, env=_hook_env(tmp_path), check=False)
    return out.stdout.strip() if out.returncode == 0 else None


def _set_local_git_config(repo: Path, tmp_path: Path, key: str, value: str) -> None:
    subprocess.run([_GIT, "-C", str(repo), "config", "--local", key, value],  # noqa: S603 - fixed argv
                   check=True, env=_hook_env(tmp_path))


def _run_sync_hook(repo: Path, tmp_path: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_BASH, str(_SYNC_HOOK)], cwd=repo, capture_output=True, text=True,  # noqa: S603 - fixed argv
                          env=_hook_env(tmp_path, **extra), check=False, timeout=60)


@_needs_posix_bash_and_git
def test_session_hook_removes_the_old_cyclaw_agent_pin(tmp_path: Path) -> None:
    repo = _hook_repo(tmp_path)
    _set_local_git_config(repo, tmp_path, "user.email", _LEGACY_EMAIL)
    _set_local_git_config(repo, tmp_path, "user.name", _LEGACY_NAME)
    result = _run_sync_hook(repo, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _local_git_config(repo, tmp_path, "user.email") is None
    assert _local_git_config(repo, tmp_path, "user.name") is None


@_needs_posix_bash_and_git
def test_session_hook_pins_no_identity_by_default(tmp_path: Path) -> None:
    repo = _hook_repo(tmp_path)
    result = _run_sync_hook(repo, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _local_git_config(repo, tmp_path, "user.email") is None
    assert _local_git_config(repo, tmp_path, "user.name") is None


@_needs_posix_bash_and_git
def test_session_hook_leaves_an_identity_set_on_purpose(tmp_path: Path) -> None:
    repo = _hook_repo(tmp_path)
    _set_local_git_config(repo, tmp_path, "user.email", "someone@example.com")
    _set_local_git_config(repo, tmp_path, "user.name", "Someone")
    assert _run_sync_hook(repo, tmp_path).returncode == 0
    assert _local_git_config(repo, tmp_path, "user.email") == "someone@example.com"
    assert _local_git_config(repo, tmp_path, "user.name") == "Someone"


@_needs_posix_bash_and_git
def test_session_hook_removes_only_the_old_default_name(tmp_path: Path) -> None:
    repo = _hook_repo(tmp_path)
    _set_local_git_config(repo, tmp_path, "user.email", _LEGACY_EMAIL)
    _set_local_git_config(repo, tmp_path, "user.name", "Someone")
    assert _run_sync_hook(repo, tmp_path).returncode == 0
    assert _local_git_config(repo, tmp_path, "user.email") is None
    assert _local_git_config(repo, tmp_path, "user.name") == "Someone"


@pytest.mark.parametrize("overrides", [
    {"CYCLAW_AGENT_COMMIT_EMAIL": "bot@example.com", "CYCLAW_AGENT_COMMIT_NAME": "Bot"},
    {"CYCLAW_AGENT_COMMIT_EMAIL": "bot@example.com"},
    {"CYCLAW_AGENT_COMMIT_NAME": "Bot"},
])
@_needs_posix_bash_and_git
def test_session_hook_does_not_pin_the_agentic_loop_overrides(tmp_path: Path, overrides: dict[str, str]) -> None:
    # Pinned into repo-local config, an override reached every session and
    # worktree sharing the repository, outlived its own session, and still
    # lost to a GIT_COMMITTER_* the runtime exported. They set CyClaw's own
    # agentic-loop identity (utils/agent_identity.py) and nothing else.
    repo = _hook_repo(tmp_path)
    assert _run_sync_hook(repo, tmp_path, **overrides).returncode == 0
    assert _local_git_config(repo, tmp_path, "user.email") is None
    assert _local_git_config(repo, tmp_path, "user.name") is None


@_needs_posix_bash_and_git
def test_session_hook_removes_the_old_pin_whatever_overrides_are_set(tmp_path: Path) -> None:
    # A name-only override once skipped this cleanup, which left the old email:
    # the half that decides whether the runtime can sign the commit.
    repo = _hook_repo(tmp_path)
    _set_local_git_config(repo, tmp_path, "user.email", _LEGACY_EMAIL)
    _set_local_git_config(repo, tmp_path, "user.name", _LEGACY_NAME)
    assert _run_sync_hook(repo, tmp_path, CYCLAW_AGENT_COMMIT_NAME="Chosen Name").returncode == 0
    assert _local_git_config(repo, tmp_path, "user.email") is None
    assert _local_git_config(repo, tmp_path, "user.name") is None


@_needs_posix_bash_and_git
def test_session_hook_reports_the_identity_and_never_blocks_offline(tmp_path: Path) -> None:
    repo = _hook_repo(tmp_path)
    _set_local_git_config(repo, tmp_path, "user.email", "someone@example.com")
    _set_local_git_config(repo, tmp_path, "user.name", "Someone")
    result = _run_sync_hook(repo, tmp_path)
    assert result.returncode == 0
    assert "Commits will be made as: Someone <someone@example.com>" in result.stdout
    assert "Could not fetch" in result.stdout


@_needs_posix_bash_and_git
def test_session_hook_keeps_the_old_name_beside_a_deliberate_email(tmp_path: Path) -> None:
    # Only the old pin is removed. An email someone chose is not the old pin,
    # so the name beside it stays even when it matches the old default.
    repo = _hook_repo(tmp_path)
    _set_local_git_config(repo, tmp_path, "user.email", "someone@example.com")
    _set_local_git_config(repo, tmp_path, "user.name", _LEGACY_NAME)
    assert _run_sync_hook(repo, tmp_path).returncode == 0
    assert _local_git_config(repo, tmp_path, "user.email") == "someone@example.com"
    assert _local_git_config(repo, tmp_path, "user.name") == _LEGACY_NAME


@_needs_posix_bash_and_git
def test_session_hook_reports_the_committer_git_will_use(tmp_path: Path) -> None:
    # GIT_COMMITTER_* outranks user.name/user.email, so a report read from the
    # config keys would name an identity the next commit does not carry.
    repo = _hook_repo(tmp_path)
    _set_local_git_config(repo, tmp_path, "user.email", "someone@example.com")
    _set_local_git_config(repo, tmp_path, "user.name", "Someone")
    result = _run_sync_hook(repo, tmp_path, GIT_COMMITTER_NAME="Runtime",
                            GIT_COMMITTER_EMAIL="runtime@example.com")
    assert result.returncode == 0
    assert ("Commits will be made as: author Someone <someone@example.com>, "
            "committer Runtime <runtime@example.com>") in result.stdout


_OPTIMIZE_BOOTSTRAP = REPO_ROOT / ".claude" / "skills" / "CyClaw-Optimize" / "bootstrap.sh"


@_needs_posix_bash_and_git
def test_optimize_bootstrap_reports_the_committer_git_will_use(tmp_path: Path) -> None:
    # The identity line is printed before any step that needs a remote, so
    # the script's exit code in a remote-less repo does not matter here.
    repo = _hook_repo(tmp_path)
    _set_local_git_config(repo, tmp_path, "user.email", "someone@example.com")
    _set_local_git_config(repo, tmp_path, "user.name", "Someone")
    result = subprocess.run([_BASH, str(_OPTIMIZE_BOOTSTRAP)], cwd=repo, capture_output=True,  # noqa: S603 - fixed argv
                            text=True, check=False, timeout=60,
                            env=_hook_env(tmp_path, GIT_COMMITTER_NAME="Runtime",
                                          GIT_COMMITTER_EMAIL="runtime@example.com"))
    assert ("git identity: author Someone <someone@example.com>, "
            "committer Runtime <runtime@example.com>") in result.stdout

