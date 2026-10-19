"""Unit tests for utils.child_environment public contracts.

The module owner is separate from this test file. These assert current main behavior: capability
allow-lists, explicit secret_names, telemetry scrubbing, and configured
path-variable retention. No app-code edits.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from utils.child_environment import (
    child_environment,
    configured_path_names,
    isolated_helper_environment,
)
from utils.telemetry_kill import SCRUBBED_ENV_KEYS, TELEMETRY_KILL


def test_helper_capability_copies_only_base_keys() -> None:
    source = {
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "HOME": "/home/op",
        "GH_TOKEN": "should-not-pass",
        "RCLONE_CONFIG_PASS": "should-not-pass",
        "CYCLAW_API_KEY": "should-not-pass",
        "DECOY": "drop-me",
    }
    env = child_environment("helper", source=source)
    assert env["PATH"] == "/usr/bin"
    assert env["LANG"] == "C.UTF-8"
    assert "HOME" not in env
    assert "GH_TOKEN" not in env
    assert "RCLONE_CONFIG_PASS" not in env
    assert "CYCLAW_API_KEY" not in env
    assert "DECOY" not in env


def test_sync_capability_includes_discovery_and_rclone() -> None:
    source = {
        "PATH": "/bin",
        "HOME": "/home/op",
        "RCLONE_CONFIG": "/cfg/rclone.conf",
        "RCLONE_CONFIG_PASS": "pass",
        "GH_TOKEN": "nope",
    }
    env = child_environment("sync", source=source)
    assert env["HOME"] == "/home/op"
    assert env["RCLONE_CONFIG"] == "/cfg/rclone.conf"
    assert env["RCLONE_CONFIG_PASS"] == "pass"
    assert "GH_TOKEN" not in env


@pytest.mark.parametrize("capability", ["filesystem", "helper"])
def test_filesystem_and_helper_capabilities(capability: str) -> None:
    source = {"PATH": "/bin", "HOME": "/home/op", "USERPROFILE": r"C:\Users\op", "SECRET": "x"}
    env = child_environment(capability, source=source)
    assert env["PATH"] == "/bin"
    if capability == "filesystem":
        assert env["HOME"] == "/home/op"
        assert env["USERPROFILE"] == r"C:\Users\op"
    else:
        assert "HOME" not in env
    assert "SECRET" not in env


def test_unknown_capability_raises_key_error() -> None:
    with pytest.raises(KeyError):
        child_environment("not-a-capability", source={"PATH": "/bin"})


def test_secret_names_are_copied_explicitly_only() -> None:
    source = {
        "PATH": "/bin",
        "DSN": "postgres://u:p@localhost/db",
        "OTHER_SECRET": "nope",
    }
    env = child_environment("filesystem", secret_names=("DSN",), source=source)
    assert env["DSN"] == "postgres://u:p@localhost/db"
    assert "OTHER_SECRET" not in env


def test_child_environment_overlays_telemetry_kill_and_scrubs() -> None:
    source = {
        "PATH": "/bin",
        "GH_TELEMETRY": "log",
        "OTEL_SDK_DISABLED": "false",
        "LANGSMITH_API_KEY": "leak-me",
        "OTEL_CONFIG_FILE": "/tmp/evil.yaml",
    }
    env = child_environment(source=source)
    assert env["GH_TELEMETRY"] == TELEMETRY_KILL["GH_TELEMETRY"]
    assert env["OTEL_SDK_DISABLED"] == TELEMETRY_KILL["OTEL_SDK_DISABLED"]
    for key in SCRUBBED_ENV_KEYS:
        assert key not in env


def test_child_environment_does_not_read_os_environ_when_source_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/should-not-appear")
    monkeypatch.setenv("HOME", "/should-not-appear")
    env = child_environment("filesystem", source={"PATH": "/only-this"})
    assert env["PATH"] == "/only-this"
    assert "HOME" not in env


def test_isolated_helper_environment_uses_disposable_home(tmp_path: Path) -> None:
    with isolated_helper_environment() as env:
        home = Path(env["HOME"])
        assert home.is_dir()
        assert env["USERPROFILE"] == env["HOME"]
        assert env["XDG_CONFIG_HOME"] == env["HOME"]
        assert env["TMPDIR"] == env["HOME"]
        assert "cyclaw-helper-" in home.name
        (home / "probe").write_text("ok", encoding="utf-8")
    assert not home.exists()


@pytest.mark.parametrize("template", ["${CYCLAW_FS_ROOT}/docs", "$CYCLAW_FS_ROOT/docs", "%CYCLAW_FS_ROOT%/docs"])
def test_configured_path_names_retains_absolute_directory_vars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, template: str
) -> None:
    root = tmp_path / "share"
    root.mkdir()
    monkeypatch.setenv("CYCLAW_FS_ROOT", str(root.resolve()))
    names = configured_path_names({"allowed_roots": [template]})
    assert names == ("CYCLAW_FS_ROOT",)


@pytest.mark.parametrize(
    "name",
    ["FAKEROOT", "TEMPPATH", "VAULTDIR", "CERTPATH", "MYFOLDER"],
)
def test_configured_path_names_rejects_suffix_decoys_under_allowlist(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # Explicit allow-list (CYCLAW_FS_ROOT only) rejects suffix decoys even with
    # absolute values — closes #1557 item 4 after commit cf09a0cd.
    monkeypatch.setenv(name, "/tmp/absolute-decoy")
    with pytest.raises(ValueError, match="not an allowed directory capability"):
        configured_path_names({"workdir": f"${{{name}}}"})


def test_configured_path_names_rejects_relative_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CYCLAW_FS_ROOT", "relative/path")
    with pytest.raises(ValueError, match="must contain an absolute path"):
        configured_path_names({"allowed_roots": ["$CYCLAW_FS_ROOT"]})


@pytest.mark.parametrize("template", ["$DATABASE_PASSWORD", "%DATABASE_PASSWORD%"])
def test_configured_path_names_rejects_secret_shaped_names(
    monkeypatch: pytest.MonkeyPatch, template: str,
) -> None:
    monkeypatch.setenv("DATABASE_PASSWORD", "/tmp/keys")
    with pytest.raises(ValueError, match="not an allowed directory capability"):
        configured_path_names({"workdir": template})


def test_configured_path_names_rejects_loader_and_git_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "/tmp/py")
    with pytest.raises(ValueError, match="not an allowed directory capability"):
        configured_path_names({"workdir": "$PYTHONPATH"})
    monkeypatch.setenv("GIT_PROXYDIR", "/tmp/git-proxy")
    with pytest.raises(ValueError, match="not an allowed directory capability"):
        configured_path_names({"workdir": "$GIT_PROXYDIR"})


def test_configured_path_names_empty_block_returns_empty() -> None:
    assert configured_path_names(None) == ()
    assert configured_path_names({}) == ()
    assert configured_path_names({"unrelated": "x"}) == ()


@pytest.mark.parametrize("name", ["PROJECT", "MYFOLDER", "PROJECT-NAME", "PROJECT NAME", "1"])
def test_percent_paths_reject_populated_unknown_variables(monkeypatch, name):
    monkeypatch.setenv(name, "customerA")
    with pytest.raises(ValueError, match="not an allowed directory capability"):
        configured_path_names({"log_dir": rf"C:\state\%{name}%\logs"})


def test_percent_literals_and_discovery_paths_keep_windows_expansion(monkeypatch):
    import ntpath

    monkeypatch.delenv("off", raising=False)
    monkeypatch.setenv("USERPROFILE", r"C:\SyntheticHome")
    monkeypatch.setenv("PROJECT", "customerA")
    paths = [r"D:\50%off%", r"%USERPROFILE%\logs", r"C:\state\%%PROJECT%%\logs"]
    if os.name == "nt":
        paths.append(r"%userprofile%\logs")
    for path in paths:
        names = configured_path_names({"log_dir": path})
        before = ntpath.expandvars(path)
        env = child_environment("sync", secret_names=names)
        with monkeypatch.context() as child:
            for name in tuple(os.environ):
                child.delenv(name)
            for name, value in env.items():
                child.setenv(name, value)
            assert ntpath.expandvars(path) == before
