"""Run the sourced Linux credential helper on POSIX; no live keyring is touched."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

_HELPER = Path(__file__).resolve().parents[1] / "macos/cyclaw-linux-key.sh"
_BASH = shutil.which("bash")
_KEY = "a1" * 20
pytestmark = pytest.mark.skipif(os.name == "nt" or not _BASH, reason="requires POSIX Bash")


def _env(tmp_path: Path) -> dict[str, str]:
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "CYCLAW_SECRET_TOOL": "none",
        "HELPER": str(_HELPER),
    }
    env.pop("CYCLAW_API_KEY", None)
    return env


def _run(tmp_path: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_BASH, "-c", 'source "$HELPER"; ' + command],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize(
    "suffix,valid", [("", True), ("\n", True), ("\nextra", False), ("\n\n", False), ("\0extra", False), ("\r\n", False)]
)
def test_load_entire_key_file(tmp_path: Path, suffix: str, valid: bool) -> None:
    key_file = tmp_path / "config/cyclaw/api-key"
    key_file.parent.mkdir(parents=True, mode=0o700)
    content = (_KEY + suffix).encode()
    key_file.write_bytes(content)
    key_file.chmod(0o600)
    result = _run(
        tmp_path, 'cyclaw_linux_load_api_key; rc=$?; [ -z "${CYCLAW_API_KEY:-}" ] || echo KEY_EXPORTED; exit "$rc"'
    )
    assert result.returncode == (0 if valid else 2), result.stderr
    assert ("KEY_EXPORTED" in result.stdout) == valid
    assert _KEY not in result.stdout + result.stderr
    assert key_file.read_bytes() == content


def _wait_file(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        assert time.monotonic() < deadline, f"timed out waiting for {path.name}"
        time.sleep(0.02)


@pytest.mark.parametrize("keyring", [False, True], ids=["file", "libsecret-stub"])
def test_concurrent_first_launchers_share_persisted_key(tmp_path: Path, keyring: bool) -> None:
    env = _env(tmp_path)
    if keyring:
        tool = tmp_path / "secret-tool"
        tool.write_text("""#!/bin/bash
case "$1" in
  lookup) cat "$HOME/keyring" 2>/dev/null ;;
  store) cat > "$HOME/keyring" ;;
  *) exit 1 ;;
esac
""")
        tool.chmod(0o700)
        env["CYCLAW_SECRET_TOOL"] = str(tool)
    command = """source "$HELPER"
# Hold the first creator while a second process enters ensure().
_cyclaw_linux_generate_key() {
  if [ "$RUNNER" = first ]; then
    touch "$HOME/generating"
    while [ ! -e "$HOME/release" ]; do sleep 0.02; done
    printf 'a1%.0s' {1..20}
  else
    printf 'b2%.0s' {1..20}
  fi
}
touch "$HOME/$RUNNER-started"
cyclaw_linux_ensure_api_key || exit $?
printf '%s' "$CYCLAW_API_KEY" > "$HOME/$RUNNER-result"
"""
    # Each subprocess runs the real load/store/lock path. Only random generation
    # is controlled so a lost update produces observably different keys.
    first = subprocess.Popen(
        [_BASH, "-c", command],
        env={**env, "RUNNER": "first"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    second = None
    try:
        _wait_file(tmp_path / "generating")
        second = subprocess.Popen(
            [_BASH, "-c", command],
            env={**env, "RUNNER": "second"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_file(tmp_path / "second-started")
        time.sleep(0.2)
        (tmp_path / "release").touch()
        outputs = [first.communicate(timeout=15), second.communicate(timeout=15)]
        assert first.returncode == second.returncode == 0, outputs
        persisted = tmp_path / ("keyring" if keyring else "config/cyclaw/api-key")
        assert (tmp_path / "first-result").read_text() == persisted.read_text().strip()
        assert (tmp_path / "second-result").read_text() == persisted.read_text().strip()
        assert _KEY not in str(outputs)
        assert not (tmp_path / "config/cyclaw/.api-key.lock").exists()
    finally:
        (tmp_path / "release").touch()
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()


def test_purge_refuses_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "unrelated-key"
    target.write_text(_KEY)
    key_file = tmp_path / "config/cyclaw/api-key"
    key_file.parent.mkdir(parents=True, mode=0o700)
    key_file.symlink_to(target)
    result = _run(tmp_path, "cyclaw_linux_remove_api_key")
    assert result.returncode == 2
    assert key_file.is_symlink()
    assert target.read_text() == _KEY
    assert not (key_file.parent / ".api-key.lock").exists()


def test_failed_generation_releases_lock_for_retry(tmp_path: Path) -> None:
    failed = _run(tmp_path, "_cyclaw_linux_generate_key() { return 1; }; cyclaw_linux_ensure_api_key")
    assert failed.returncode == 1
    assert not (tmp_path / "config/cyclaw/.api-key.lock").exists()
    retry = _run(tmp_path, "cyclaw_linux_ensure_api_key")
    assert retry.returncode == 0, retry.stderr
    assert len((tmp_path / "config/cyclaw/api-key").read_text().strip()) == 40
