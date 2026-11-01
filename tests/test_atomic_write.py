"""Generated scheduler artifacts survive failed and overlapping replacements."""

import os
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from sync.scheduler import _write_posix_launcher, _write_windows_launcher
from utils import atomic_write, launchd_plist, win_schtasks


def test_write_atomic_replaces_bytes_and_sets_mode(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "launcher.sh"
    atomic_write.write_atomic(path, b"#!/bin/sh\nexit 0\n", mode=0o700)
    assert path.read_bytes() == b"#!/bin/sh\nexit 0\n"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o700
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("operation", ["chmod", "fdopen", "fsync", "replace"])
def test_write_atomic_preserves_target_and_cleans_up_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    path = tmp_path / "job"
    path.write_bytes(b"old")
    descriptors: list[int] = []
    real_mkstemp = atomic_write.tempfile.mkstemp

    def tracked_mkstemp(**kwargs):
        fd, name = real_mkstemp(**kwargs)
        descriptors.append(fd)
        return fd, name

    def fail(*args, **kwargs):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(atomic_write.tempfile, "mkstemp", tracked_mkstemp)
    monkeypatch.setattr(atomic_write.os, operation, fail)
    with pytest.raises(OSError, match="synthetic write failure"):
        atomic_write.write_atomic(path, b"new", mode=0o600)
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_overlapping_writers_use_different_temporary_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "job"
    real_replace = os.replace
    temporary_paths: list[Path] = []

    def overlapping_replace(source, target):
        temporary_paths.append(Path(source))
        if len(temporary_paths) == 1:
            atomic_write.write_atomic(path, b"inner", mode=0o600)
            assert path.read_bytes() == b"inner"
        real_replace(source, target)

    monkeypatch.setattr(atomic_write.os, "replace", overlapping_replace)
    atomic_write.write_atomic(path, b"outer", mode=0o600)
    assert path.read_bytes() == b"outer"
    assert len(set(temporary_paths)) == 2
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("kind", ["plist", "cmd", "xml", "posix", "windows"])
def test_scheduler_writers_preserve_live_artifact_on_failed_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    cfg = SimpleNamespace(log_dir=str(tmp_path), _repo_root=str(tmp_path), _config_path=None)
    path = tmp_path / {"posix": "cyclaw_sync.sh", "windows": "cyclaw_sync.bat"}.get(kind, f"job.{kind}")
    path.write_bytes(b"previous complete artifact")
    monkeypatch.setattr("sync.scheduler._repo_root", lambda _: str(tmp_path))

    def fail(*args, **kwargs):
        raise PermissionError("synthetic replace failure")

    monkeypatch.setattr(atomic_write.os, "replace", fail)
    with pytest.raises(PermissionError):
        if kind == "plist":
            launchd_plist.write_plist({"Label": "test"}, path)
        elif kind == "cmd":
            win_schtasks.write_cmd_launcher(path, ["python", "-m", "sync.scheduled", "sync"])
        elif kind == "xml":
            win_schtasks.write_task_xml(path, "<Task />")
        elif kind == "posix":
            _write_posix_launcher(cfg)
        else:
            _write_windows_launcher(cfg)
    assert path.read_bytes() == b"previous complete artifact"
    assert list(tmp_path.iterdir()) == [path]


def test_invalid_plist_never_creates_a_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "job.plist"
    launchd_plist.write_plist({"Label": "old"}, path)
    with pytest.raises(TypeError):
        launchd_plist.write_plist({"Label": None}, path)
    assert plistlib.loads(path.read_bytes()) == {"Label": "old"}
    assert list(tmp_path.iterdir()) == [path]
