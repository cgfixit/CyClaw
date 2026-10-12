"""Unit tests for utils.child_environment public contracts.

The module owner is separate from this test file. These assert current main behavior: capability
allow-lists, explicit secret_names, telemetry scrubbing, and configured
path-variable retention. No app-code edits.
"""

from __future__ import annotations

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


def test_github_capability_includes_gh_tokens() -> None:
    source = {
        "PATH": "/bin",
        "HOME": "/home/op",
        "GH_TOKEN": "ghp_x",
        "GITHUB_TOKEN": "ghs_y",
        "GH_HOST": "github.com",
        "RCLONE_CONFIG_PASS": "nope",
    }
    env = child_environment("github", source=source)
    assert env["GH_TOKEN"] == "ghp_x"
    assert env["GITHUB_TOKEN"] == "ghs_y"
    assert env["GH_HOST"] == "github.com"
    assert "RCLONE_CONFIG_PASS" not in env


@pytest.mark.parametrize("capability", ["filesystem", "sql", "verification"])
def test_filesystem_sql_verification_capabilities(capability: str) -> None:
    source = {"PATH": "/bin", "HOME": "/home/op", "USERPROFILE": r"C:\Users\op", "SECRET": "x"}
    env = child_environment(capability, source=source)
    assert env["PATH"] == "/bin"
    if capability in {"filesystem", "sql"}:
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
    env = child_environment("sql", secret_names=("DSN",), source=source)
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


def test_configured_path_names_retains_absolute_directory_vars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "share"
    root.mkdir()
    monkeypatch.setenv("CYCLAW_FS_ROOT", str(root.resolve()))
    names = configured_path_names({"allowed_roots": ["${CYCLAW_FS_ROOT}/docs"]})
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


def test_configured_path_names_rejects_secret_shaped_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PASSWORD", "/tmp/keys")
    with pytest.raises(ValueError, match="not an allowed directory capability"):
        configured_path_names({"workdir": "$DATABASE_PASSWORD"})


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
