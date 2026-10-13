"""Credential bootstrap failure paths without reading the operator's keystore."""

import os
import subprocess
from unittest.mock import patch

import pytest

from sync import scheduled


@pytest.mark.parametrize("password", [None, "synthetic-password"])
def test_sync_environment_has_only_sync_credential(password):
    with patch.dict(os.environ, {"PATH": os.defpath, "GH_TOKEN": "synthetic-unrelated"}, clear=True), \
            patch.object(scheduled, "_password", return_value=password):
        env = scheduled.prepare_environment()
    assert "GH_TOKEN" not in env
    assert env["RCLONE_ASK_PASSWORD"] == "false"
    assert env.get("RCLONE_CONFIG_PASS") == password


@pytest.mark.parametrize("password", ["", "bad\x00value"])
def test_empty_or_invalid_keystore_secret_refuses(password):
    with patch.dict(os.environ, {}, clear=True), patch.object(scheduled, "_password", return_value=password):
        with pytest.raises(OSError):
            scheduled.prepare_environment()


def test_explicit_sync_credential_does_not_query_keystore():
    with patch.dict(os.environ, {"RCLONE_CONFIG_PASS": "injected"}, clear=True), \
            patch.object(scheduled, "_password", side_effect=AssertionError("must not read keystore")):
        assert scheduled.prepare_environment()["RCLONE_CONFIG_PASS"] == "injected"


@pytest.mark.parametrize("error", [OSError("secret bytes"), subprocess.TimeoutExpired("secret command", 10)])
def test_failures_do_not_echo_os_diagnostics(error, capsys):
    with patch.object(scheduled, "prepare_environment", side_effect=error):
        assert scheduled.main(["--check-credentials"]) == 3
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
    assert "credential setup failed" in output.err


def test_check_credentials_is_read_only_and_suppresses_remote_names(capsys):
    with patch.object(scheduled, "prepare_environment", return_value={"RCLONE_ASK_PASSWORD": "false"}), \
            patch.object(scheduled.shutil, "which", return_value="rclone"), \
            patch.object(scheduled.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"private:\ndropbox_cyclaw:\n")) as run:
        assert scheduled.main(["--check-credentials"]) == 0
    assert run.call_args.args[0] == ["rclone", "listremotes"]
    assert run.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert "private" not in capsys.readouterr().out


def test_configured_directory_capability_survives_bootstrap(tmp_path):
    from utils.child_environment import configured_path_names

    with patch.dict(os.environ, {"CYCLAW_FS_ROOT": str(tmp_path), "RCLONE_CONFIG_PASS": "injected"}, clear=True):
        names = configured_path_names({"local_path": "$CYCLAW_FS_ROOT"})
        env = scheduled.prepare_environment(names)
    assert env["CYCLAW_FS_ROOT"] == str(tmp_path)


@pytest.mark.parametrize("document", ["- invalid-root\n", "sync: [unterminated\n"])
def test_malformed_config_returns_environment_error(tmp_path, document, capsys):
    from utils.logger import reset_config_cache

    config = tmp_path / "config.yaml"
    config.write_text(document)
    reset_config_cache()
    try:
        assert scheduled.main(["--config", str(config), "sync"]) == 3
        assert "credential setup failed" in capsys.readouterr().err
    finally:
        reset_config_cache()


@pytest.mark.skipif(os.name != "nt", reason="native Windows Credential Manager acceptance")
def test_windows_reads_only_unique_disposable_credential():
    import ctypes
    import uuid
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("BlobSize", wintypes.DWORD),
                    ("Blob", ctypes.c_void_p), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    target = "CyClaw-fixture-" + uuid.uuid4().hex
    blob = "synthetic-config-password".encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob)
    item = Credential(Type=1, TargetName=target, BlobSize=len(blob),
                      Blob=ctypes.cast(buffer, ctypes.c_void_p), Persist=1)
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    assert scheduled._windows_password(target) is None
    assert api.CredWriteW(ctypes.byref(item), 0), ctypes.get_last_error()
    try:
        assert scheduled._windows_password(target) == blob.decode("utf-16-le")
    finally:
        assert api.CredDeleteW(target, 1, 0), ctypes.get_last_error()
    assert scheduled._windows_password(target) is None


def test_disabled_sync_skips_the_keystore(tmp_path, capsys):
    from utils.logger import reset_config_cache

    config = tmp_path / "config.yaml"
    config.write_text(
        'sync:\n  enabled: false\n  local_path: "data/corpus"\n'
        '  remote_name: "dropbox_cyclaw"\n  remote_path: "CyClaw/corpus"\n'
    )
    reset_config_cache()
    try:
        with patch.object(scheduled, "prepare_environment", side_effect=AssertionError("must not read keystore")):
            assert scheduled.main(["--config", str(config), "sync"]) == 0
        assert "nothing to do" in capsys.readouterr().out
    finally:
        reset_config_cache()



@pytest.mark.parametrize("listing", [b"", b"other_remote:\n"])
def test_check_credentials_requires_the_configured_remote(listing, capsys):
    with patch.object(scheduled, "prepare_environment", return_value={"RCLONE_ASK_PASSWORD": "false"}), \
            patch.object(scheduled.shutil, "which", return_value="rclone"), \
            patch.object(scheduled.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, listing)):
        assert scheduled.main(["--check-credentials"]) == 3
    assert "other_remote" not in capsys.readouterr().out


@pytest.mark.parametrize("template", ["$HOME/logs", "${XDG_CONFIG_HOME}/cyclaw"])
def test_retained_discovery_variables_are_not_capability_selections(monkeypatch, template):
    from utils.child_environment import configured_path_names

    monkeypatch.setenv("HOME", "/home/op")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/op/.config")
    assert configured_path_names({"log_dir": template}) == ()


def test_check_credentials_uses_the_selected_config(tmp_path, capsys):
    from utils.logger import reset_config_cache

    config = tmp_path / "config.yaml"
    config.write_text(
        'sync:\n  enabled: true\n  local_path: "data/corpus"\n'
        '  remote_name: "custom_remote"\n  remote_path: "CyClaw/corpus"\n'
    )
    reset_config_cache()
    try:
        with patch.object(scheduled, "prepare_environment", return_value={"RCLONE_ASK_PASSWORD": "false"}), \
                patch.object(scheduled.shutil, "which", return_value="rclone"), \
                patch.object(scheduled.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"custom_remote:\n")):
            assert scheduled.main(["--config", str(config), "--check-credentials"]) == 0
        assert "custom_remote" not in capsys.readouterr().out
    finally:
        reset_config_cache()


@pytest.mark.parametrize("document", [None, "sync: [unterminated\n"])
def test_check_credentials_fails_when_the_selected_config_cannot_load(tmp_path, document):
    from utils.logger import reset_config_cache

    config = tmp_path / "config.yaml"
    if document is not None:
        config.write_text(document)
    reset_config_cache()
    try:
        with patch.object(scheduled, "prepare_environment", return_value={"RCLONE_ASK_PASSWORD": "false"}), \
                patch.object(scheduled.shutil, "which", return_value="rclone"), \
                patch.object(scheduled.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"other:\n")):
            assert scheduled.main(["--config", str(config), "--check-credentials"]) == 3
    finally:
        reset_config_cache()


def test_service_comes_from_the_shipped_secret_policy():
    """The keystore service name is the shared policy's RCLONE_CONFIG_PASS row, not a literal."""
    assert scheduled._service() == "com.cgfixit.cyclaw.rclone-config-pass"


def test_policy_without_the_rclone_mapping_refuses(tmp_path):
    """A policy file missing the RCLONE_CONFIG_PASS row raises instead of guessing a service."""
    policy = scheduled.POLICY_PATH.read_text(encoding="ascii")
    stripped = tmp_path / "secret-policy.tsv"
    stripped.write_text(
        "".join(line for line in policy.splitlines(keepends=True) if "RCLONE_CONFIG_PASS" not in line),
        encoding="ascii",
    )
    with patch.object(scheduled, "POLICY_PATH", stripped), pytest.raises(OSError, match="missing rclone"):
        scheduled._service()


def test_linux_has_no_automatic_keystore(monkeypatch):
    """Linux returns None so an encrypted rclone config fails noninteractively in rclone."""
    monkeypatch.setattr(scheduled.sys, "platform", "linux")
    with patch.object(scheduled.subprocess, "run", side_effect=AssertionError("must not spawn a keystore tool")):
        assert scheduled._password() is None


@pytest.mark.skipif(os.name == "nt", reason="the macOS branch imports pwd")
@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (44, "", None),
        (0, "synthetic\n", "synthetic"),
        (0, "ends-in-newline\n\n", "ends-in-newline\n"),
    ],
)
def test_macos_keychain_exit_codes(monkeypatch, returncode, stdout, expected):
    """Exit 44 means no item (optional); success strips exactly the one newline security(1) appends."""
    monkeypatch.setattr(scheduled.sys, "platform", "darwin")
    done = subprocess.CompletedProcess([], returncode, stdout, "")
    with patch.object(scheduled.subprocess, "run", return_value=done) as run:
        assert scheduled._password() == expected
    argv = run.call_args.args[0]
    assert argv[:2] == ["/usr/bin/security", "find-generic-password"]
    assert argv[-3:] == ["-s", "com.cgfixit.cyclaw.rclone-config-pass", "-w"]


@pytest.mark.skipif(os.name == "nt", reason="the macOS branch imports pwd")
def test_macos_keychain_failure_is_an_error_not_absence(monkeypatch):
    """Any nonzero exit other than 44 (locked, denied) raises rather than running without a credential."""
    monkeypatch.setattr(scheduled.sys, "platform", "darwin")
    done = subprocess.CompletedProcess([], 51, "", "secret diagnostic")
    with patch.object(scheduled.subprocess, "run", return_value=done), pytest.raises(OSError, match="Keychain read failed"):
        scheduled._password()


def test_check_credentials_rejects_unknown_arguments(capsys):
    """Anything besides an optional --config PATH is a usage error (exit 2), before any keystore read."""
    with patch.object(scheduled, "prepare_environment", side_effect=AssertionError("must not read keystore")):
        assert scheduled.main(["--check-credentials", "--bogus"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_check_credentials_without_rclone_is_an_environment_error(capsys):
    """A missing rclone binary exits 3 with the generic message."""
    with patch.object(scheduled, "prepare_environment", return_value={"RCLONE_ASK_PASSWORD": "false"}), \
            patch.object(scheduled.shutil, "which", return_value=None):
        assert scheduled.main(["--check-credentials"]) == 3
    assert "credential setup failed" in capsys.readouterr().err


def test_enabled_run_replaces_process_environment_before_sync(tmp_path):
    """The sync CLI runs with only the prepared environment; unrelated credentials are gone."""
    from utils.logger import reset_config_cache

    config = tmp_path / "config.yaml"
    config.write_text(
        'sync:\n  enabled: true\n  local_path: "data/corpus"\n'
        '  remote_name: "dropbox_cyclaw"\n  remote_path: "CyClaw/corpus"\n'
    )
    seen: dict = {}

    def fake_sync_main(args):
        seen["args"] = args
        seen["env"] = dict(os.environ)
        return 0

    prepared = {"PATH": os.defpath, "RCLONE_CONFIG_PASS": "synthetic"}
    reset_config_cache()
    try:
        # No clear=True: Windows resolves Path.home() from USERPROFILE while the config loads.
        with patch.dict(os.environ, {"GH_TOKEN": "synthetic-unrelated"}), \
                patch.object(scheduled, "prepare_environment", return_value=prepared), \
                patch("sync.cli.main", side_effect=fake_sync_main):
            assert scheduled.main(["--config", str(config), "status"]) == 0
    finally:
        reset_config_cache()
    assert seen["args"] == ["--config", str(config), "status"]
    assert seen["env"] == prepared
