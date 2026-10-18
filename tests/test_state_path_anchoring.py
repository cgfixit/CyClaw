"""Relative state paths resolve against the repo root, never the process CWD.

The soul, auth, audit, spend and numbat paths were already anchored; these
pin the stragglers (memory DB, fsconnect rate DB and default staging dir) so a
process launched from another directory still finds the same state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic.fsconnect import indexer as fs_indexer
from agentic.fsconnect.config import FsConnectConfig
from memory.store import _db_path

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def foreign_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_memory_db_path_ignores_cwd(foreign_cwd: Path) -> None:
    path = _db_path({"memory": {"db_path": "data/memory/cyclaw_memory.db"}})
    assert path == _REPO_ROOT / "data" / "memory" / "cyclaw_memory.db"
    assert foreign_cwd not in path.parents


def test_memory_db_path_keeps_absolute_value(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.db"
    assert _db_path({"memory": {"db_path": str(target)}}) == target


def test_fsconnect_rate_db_path_ignores_cwd(foreign_cwd: Path) -> None:
    settings = FsConnectConfig(write_rate_limit={"db_path": "data/fsconnect_rate.db"}).rate_limit_settings
    assert Path(settings["db_path"]) == _REPO_ROOT / "data" / "fsconnect_rate.db"
    assert FsConnectConfig().rate_limit_settings["db_path"] == settings["db_path"]


def test_fsconnect_null_rate_db_path_stays_in_memory() -> None:
    # None means RateLimiter's in-memory backend; anchoring must not turn it
    # into a file path.
    assert FsConnectConfig(write_rate_limit={"db_path": None}).rate_limit_settings["db_path"] is None


def test_fsconnect_default_staging_is_repo_anchored() -> None:
    assert fs_indexer._DEFAULT_STAGING == _REPO_ROOT / "data" / "corpus" / "fsconnect"
