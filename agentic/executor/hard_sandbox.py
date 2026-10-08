"""Hard sandbox backends for agentic verification.

Production ``run_verification`` must not call unconstrained ``subprocess.run``.
Platform backends: Darwin ``sandbox-exec`` Seatbelt and Linux bubblewrap.
Windows fails closed until a filesystem and network boundary is implemented.
Missing binary or failed capability probe raises
``HardSandboxUnavailable`` -- fail closed, no software fallback.

``ArgvListSandbox`` is the old argv-list ``subprocess.run`` path, imported by
tests only. It is not selected by ``production_sandbox``.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess  # noqa: S404 -- argv-list only; no shell
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from utils.child_environment import child_environment
from utils.errors import AgenticError

MAX_OUTPUT_CHARS = 20_000


class HardSandboxUnavailable(AgenticError):
    """No supported hard-sandbox backend on this platform / host."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code="HARD_SANDBOX_UNAVAILABLE", details=details)


@dataclass(frozen=True)
class SandboxOutcome:
    """Backend result before the runner attaches the Check name."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class HardSandbox(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_sec: int,
    ) -> SandboxOutcome:
        """Run argv inside the sandbox. Never uses shell=True."""


def truncate_output(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [output truncated at {MAX_OUTPUT_CHARS} chars]"


def stream_to_str(stream: str | bytes | None) -> str:
    """TimeoutExpired.stdout is str on Windows text mode, bytes on POSIX."""
    if stream is None:
        return ""
    if isinstance(stream, str):
        return stream
    return stream.decode("utf-8", errors="replace")


class ArgvListSandbox:
    """Test double: the pre-Phase-4 argv-list subprocess.run path.

    Production ``production_sandbox()`` never returns this. Tests inject it so
    Linux CI can still exercise timeout/truncate/cwd plumbing without claiming
    a kernel sandbox.
    """

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_sec: int,
    ) -> SandboxOutcome:
        popen_kw: dict[str, object] = {
            "cwd": str(cwd),
            "env": dict(env),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if sys.platform != "win32":
            popen_kw["start_new_session"] = True
        try:
            proc = subprocess.Popen(list(argv), **popen_kw)  # noqa: S603 -- argv list, no shell
        except OSError as exc:
            return SandboxOutcome(
                exit_code=-2,
                stderr=f"could not execute {argv[0]!r}: {exc}",
            )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            _kill_sandbox_tree(proc)
            leftover_out, leftover_err = proc.communicate()
            return SandboxOutcome(
                exit_code=-1,
                stdout=truncate_output(stream_to_str(leftover_out)),
                stderr=f"timed out after {timeout_sec}s",
                timed_out=True,
            )
        # A check can leave a descendant running after it exits (it closes the
        # inherited pipes, so communicate() returns). Left alive, it could
        # rewrite the clone's .git/config between repo_workspace's snapshot
        # check and the git call that reads it (#1527 review). Reap the whole
        # process group on a normal exit too. A descendant that calls setsid()
        # leaves the group and is not caught here; that needs a PID namespace.
        _reap_process_group(proc)
        return SandboxOutcome(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=truncate_output(stdout or ""),
            stderr=truncate_output(stderr or ""),
        )


def _reap_process_group(proc: subprocess.Popen[str]) -> None:
    """SIGKILL anything still in the finished check's process group (POSIX only)."""
    if sys.platform == "win32":
        return
    with contextlib.suppress(OSError):
        os.killpg(proc.pid, signal.SIGKILL)


def _kill_sandbox_tree(proc: subprocess.Popen[str]) -> None:
    """Timeout must kill descendants, not only the wrapper (sandbox-exec/unshare)."""
    if sys.platform != "win32":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return
        except OSError:
            pass
    proc.kill()


def seatbelt_profile(cwd: Path, tmpdir: Path | None = None) -> str:
    """SBPL profile: deny network; deny file-write outside ``cwd`` (and TMPDIR)."""
    root = str(cwd.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    allowed = [root]
    if tmpdir is not None:
        allowed.append(str(tmpdir.resolve()).replace("\\", "\\\\").replace('"', '\\"'))
    except_clause = " ".join(f'(subpath "{p}")' for p in allowed)
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny network*)\n"
        f'(deny file-write* (subpath "{root}/.git"))\n'
        f"(deny file-write* (require-not (require-any {except_clause})))\n"
    )


def production_sandbox() -> HardSandbox:
    """Return the host backend, or raise. Never falls back to ArgvListSandbox."""
    if sys.platform == "win32":
        raise HardSandboxUnavailable(
            "Windows verification requires filesystem/network isolation; Job Objects alone are insufficient"
        )
    if sys.platform == "darwin":
        return DarwinSeatbeltSandbox()
    if sys.platform.startswith("linux"):
        return LinuxNetnsSandbox()
    raise HardSandboxUnavailable(
        f"no hard-sandbox backend for platform {sys.platform!r}; "
        "agentic verification fails closed (issue #1134 Phase 4).",
        details={"platform": sys.platform},
    )


class DarwinSeatbeltSandbox:
    """macOS Seatbelt via ``sandbox-exec -p PROFILE -- argv``.

    Missing ``sandbox-exec`` raises ``HardSandboxUnavailable`` (fail closed).
    Profile denies network and file-write outside the pinned cwd.
    """

    def __init__(self) -> None:
        path = shutil.which("sandbox-exec")
        if not path:
            raise HardSandboxUnavailable(
                "sandbox-exec not found; Darwin Seatbelt fails closed "
                "(issue #1134 Phase 4).",
                details={"platform": sys.platform},
            )
        self._sandbox_exec = path

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_sec: int,
    ) -> SandboxOutcome:
        with tempfile.TemporaryDirectory(prefix="cyclaw-seatbelt-") as tmp:
            tmp_path = Path(tmp)
            env_with_tmp = dict(env)
            env_with_tmp["HOME"] = str(tmp_path)
            env_with_tmp["USERPROFILE"] = str(tmp_path)
            env_with_tmp["TMPDIR"] = str(tmp_path)
            env_with_tmp["TMP"] = str(tmp_path)
            env_with_tmp["TEMP"] = str(tmp_path)
            wrapped = [
                self._sandbox_exec,
                "-p",
                seatbelt_profile(cwd, tmp_path),
                "--",
                *list(argv),
            ]
            return ArgvListSandbox().run(
                wrapped, cwd=cwd, env=env_with_tmp, timeout_sec=timeout_sec
            )


class LinuxNetnsSandbox:
    """Bubblewrap filesystem, PID, user, IPC and network namespaces; fail closed.

    Host files are read-only. Only the unique candidate and scratch directories
    are writable. PID namespace teardown also kills detached descendants.
    """

    def __init__(self) -> None:
        path = shutil.which("bwrap")
        if not path:
            raise HardSandboxUnavailable("bubblewrap is required for Linux verification filesystem/PID/network isolation")
        self._bwrap = path
        try:
            probe = subprocess.run(  # noqa: S603 -- fixed argv, no shell
                self._prefix() + ["/bin/true"], env=child_environment(),
                capture_output=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HardSandboxUnavailable("bubblewrap capability probe failed") from exc
        if probe.returncode != 0:
            raise HardSandboxUnavailable("bubblewrap namespaces unavailable; verification refused")

    def _prefix(self) -> list[str]:
        return [self._bwrap, "--die-with-parent", "--new-session", "--unshare-all",
                "--cap-drop", "ALL", "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev"]

    def run(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_sec: int) -> SandboxOutcome:
        with tempfile.TemporaryDirectory(prefix="cyclaw-bwrap-") as scratch:
            root = str(cwd.resolve())
            child_env = dict(env, HOME=scratch, USERPROFILE=scratch, TMPDIR=scratch, TMP=scratch, TEMP=scratch)
            wrapped = self._prefix() + ["--bind", root, root, "--bind", scratch, scratch,
                                       "--chdir", root, "--", *argv]
            return ArgvListSandbox().run(wrapped, cwd=cwd, env=child_env, timeout_sec=timeout_sec)
