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
            patch.object(scheduled.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"private:")) as run:
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
