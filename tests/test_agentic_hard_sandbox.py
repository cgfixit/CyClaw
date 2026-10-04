"""Fail-closed production sandbox selection and subprocess lifecycle contracts."""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from pathlib import Path

import pytest

from agentic.executor.hard_sandbox import (
    ArgvListSandbox,
    DarwinSeatbeltSandbox,
    HardSandboxUnavailable,
    LinuxNetnsSandbox,
    WindowsJobObjectSandbox,
    production_sandbox,
    seatbelt_profile,
)
from agentic.executor.runner import Check, run_verification
from utils.errors import AgenticError


def _py(code: str, timeout_sec: int = 10) -> Check:
    return Check("probe", (sys.executable, "-c", code), timeout_sec=timeout_sec)


def test_production_sandbox_win32_refuses_incomplete_isolation() -> None:
    if sys.platform != "win32":
        pytest.skip("Job Object is the Windows backend")
    with pytest.raises(HardSandboxUnavailable, match="filesystem"):
        production_sandbox()


def test_production_sandbox_is_fail_closed_off_windows() -> None:
    if sys.platform == "win32":
        with pytest.raises(HardSandboxUnavailable):
            production_sandbox()
        return
    try:
        backend = production_sandbox()
    except HardSandboxUnavailable as exc:
        assert exc.code == "HARD_SANDBOX_UNAVAILABLE"
        return
    if sys.platform == "darwin":
        assert isinstance(backend, DarwinSeatbeltSandbox)
    elif sys.platform.startswith("linux"):
        assert isinstance(backend, LinuxNetnsSandbox)
    else:
        pytest.fail(f"unexpected backend on {sys.platform!r}")


def test_run_verification_without_injected_sandbox_fails_closed_off_windows(tmp_path: Path) -> None:
    try:
        production_sandbox()
    except HardSandboxUnavailable:
        with pytest.raises(AgenticError, match="HARD_SANDBOX_UNAVAILABLE|fails closed|no hard-sandbox"):
            run_verification(tmp_path, [_py("import sys; sys.exit(0)")])
        return
    report = run_verification(tmp_path, [_py("import sys; sys.exit(0)")])
    assert report.ok is True


def test_empty_checks_do_not_require_a_backend(tmp_path: Path) -> None:
    report = run_verification(tmp_path, [])
    assert report.ok is True
    assert report.results == ()


def test_no_env_flag_selects_argv_list_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CYCLAW_SOFT_SANDBOX", "1")
    monkeypatch.setenv("CYCLAW_ALLOW_SOFT_SANDBOX", "1")
    try:
        production_sandbox()
    except HardSandboxUnavailable:
        with pytest.raises(HardSandboxUnavailable):
            run_verification(tmp_path, [_py("import sys; sys.exit(0)")])
        return
    report = run_verification(tmp_path, [_py("import sys; sys.exit(0)")])
    assert report.ok is True


def test_seatbelt_profile_contains_deny_network(tmp_path: Path) -> None:
    profile = seatbelt_profile(tmp_path)
    assert "deny network" in profile
    assert "file-write" in profile
    assert str(tmp_path.resolve()).replace("\\", "\\\\") in profile or str(tmp_path.resolve()) in profile


def test_seatbelt_profile_allows_a_writable_tmpdir(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    tmp = tmp_path / "tmp"
    cwd.mkdir()
    tmp.mkdir()
    profile = seatbelt_profile(cwd, tmp)
    assert "require-any" in profile
    assert str(tmp.resolve()).replace("\\", "\\\\") in profile or str(tmp.resolve()) in profile


def test_darwin_seatbelt_missing_binary_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_which = shutil.which

    def _which(cmd: str) -> str | None:
        if cmd == "sandbox-exec":
            return None
        return real_which(cmd)

    monkeypatch.setattr("agentic.executor.hard_sandbox.shutil.which", _which)
    with pytest.raises(HardSandboxUnavailable, match="sandbox-exec"):
        DarwinSeatbeltSandbox()


def test_linux_netns_missing_binary_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_which = shutil.which

    def _which(cmd: str) -> str | None:
        if cmd == "bwrap":
            return None
        return real_which(cmd)

    monkeypatch.setattr("agentic.executor.hard_sandbox.shutil.which", _which)
    with pytest.raises(HardSandboxUnavailable, match="bubblewrap"):
        LinuxNetnsSandbox()


def test_production_sandbox_never_returns_argv_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with soft-sandbox env flags, production_sandbox stays hard."""
    monkeypatch.setenv("CYCLAW_SOFT_SANDBOX", "1")
    if sys.platform == "win32":
        with pytest.raises(HardSandboxUnavailable):
            production_sandbox()
        return
    monkeypatch.setattr(
        "agentic.executor.hard_sandbox.shutil.which",
        lambda _cmd: None,
    )
    with pytest.raises(HardSandboxUnavailable):
        production_sandbox()


def test_legacy_job_object_backend_cannot_run_unconfined(tmp_path: Path) -> None:
    with pytest.raises(HardSandboxUnavailable, match="filesystem"):
        WindowsJobObjectSandbox().run([sys.executable, "-c", "pass"], cwd=tmp_path, env={}, timeout_sec=1)


def test_verification_outputs_do_not_modify_the_authoritative_source(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("trusted", encoding="utf-8")
    (tmp_path / "value").write_text("original", encoding="utf-8")
    report = run_verification(tmp_path, [_py(
        "from pathlib import Path; assert not Path('.git').exists(); Path('value').write_text('changed')"
    )], sandbox=ArgvListSandbox())
    assert report.ok
    assert (tmp_path / "value").read_text(encoding="utf-8") == "original"
    assert (tmp_path / ".git" / "config").read_text(encoding="utf-8") == "trusted"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_argv_list_reaps_a_descendant_left_running_after_a_normal_exit(tmp_path: Path) -> None:
    """#1527 review: a check that backgrounds a child and closes its pipes exits
    normally, but the child must not outlive it -- it could rewrite .git/config
    between repo_workspace's snapshot check and the git call that reads it."""
    import time

    pidfile = tmp_path / "child.pid"
    script = f"(exec >/dev/null 2>&1 </dev/null; sleep 60) & echo $! > {pidfile}"
    outcome = ArgvListSandbox().run(["/bin/sh", "-c", script], cwd=tmp_path, env=dict(os.environ), timeout_sec=30)
    assert outcome.exit_code == 0
    pid = int(pidfile.read_text(encoding="utf-8").strip())
    # SIGKILL is delivered before run() returns; the bounded wait only covers
    # init reaping the orphan so the pid stops existing.
    deadline = time.monotonic() + 5
    status = Path(f"/proc/{pid}/status")
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        # A killed orphan can linger as a zombie when PID 1 does not reap
        # (containers); a zombie runs nothing, so it counts as gone.
        state = ""
        # No /proc (macOS) or the pid vanished mid-read: fall through to the
        # os.kill probe on the next iteration.
        with contextlib.suppress(OSError, IndexError):
            state = status.read_text(encoding="utf-8").split("State:", 1)[1].split("\n", 1)[0]
        if "\tZ" in state:
            return
        time.sleep(0.05)
    os.kill(pid, 9)
    pytest.fail("a descendant of a finished check was still running")
