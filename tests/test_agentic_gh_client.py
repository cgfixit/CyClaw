"""Tests for agentic.gh_client -- argv building, version check, run_read.

No live gh binary required: subprocess and shutil.which are mocked.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from agentic import gh_client
from agentic.gh_client import build_read_argv, check_gh_version, run_read
from utils.errors import AgenticError, GhNotInstalledError, GhVersionError
from utils.logger import reset_config_cache


@pytest.fixture(autouse=True)
def _temp_audit(tmp_path: Path):
    """Prime the global config cache with a temp config so audit_log writes to tmp."""
    cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}},
           "policy": {"privacy": {}}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    reset_config_cache()
    from utils.logger import _get_config
    _get_config(str(path))  # prime cache
    yield
    reset_config_cache()


def _completed(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# --- argv building ---------------------------------------------------------

def test_build_pr_view_argv():
    argv = build_read_argv("pr_view", "owner/repo", number=42)
    assert isinstance(argv, list)
    assert argv[0] == "gh" and argv[1:3] == ["pr", "view"]
    assert "42" in argv and "owner/repo" in argv and "--json" in argv


def test_build_pr_diff_argv():
    argv = build_read_argv("pr_diff", "owner/repo", number=7)
    assert argv[1:3] == ["pr", "diff"] and "7" in argv and "--json" not in argv


def test_build_repo_view_argv():
    argv = build_read_argv("repo_view", "owner/repo")
    assert argv[1:3] == ["repo", "view"] and "owner/repo" in argv


def test_build_rejects_unknown_op():
    with pytest.raises(AgenticError):
        build_read_argv("pr_merge", "owner/repo", number=1)


def test_build_rejects_write_like_op():
    # A write-shaped op name must not be buildable here.
    with pytest.raises(AgenticError):
        build_read_argv("pr_comment", "owner/repo", number=1)


def test_build_requires_number_for_view():
    with pytest.raises(AgenticError):
        build_read_argv("pr_view", "owner/repo")


# --- version check ---------------------------------------------------------

def test_check_gh_version_parses():
    with patch.object(gh_client.shutil, "which", return_value="/usr/bin/gh"), \
         patch.object(gh_client.subprocess, "run",
                      return_value=_completed(stdout="gh version 2.55.0 (2024-08-21)\n")):
        assert check_gh_version() == (2, 55, 0)


def test_check_gh_version_missing_raises():
    with patch.object(gh_client.shutil, "which", return_value=None):
        with pytest.raises(GhNotInstalledError):
            check_gh_version()


def test_check_gh_version_too_old_raises():
    with patch.object(gh_client.shutil, "which", return_value="/usr/bin/gh"), \
         patch.object(gh_client.subprocess, "run",
                      return_value=_completed(stdout="gh version 2.10.0 (2022-01-01)\n")):
        with pytest.raises(GhVersionError):
            check_gh_version(min_version=(2, 40, 0))


def test_check_gh_version_unparseable_raises():
    with patch.object(gh_client.shutil, "which", return_value="/usr/bin/gh"), \
         patch.object(gh_client.subprocess, "run", return_value=_completed(stdout="garbage")):
        with pytest.raises(GhVersionError):
            check_gh_version()


# --- run_read --------------------------------------------------------------

def test_run_read_json_op(tmp_path: Path):
    with patch.object(gh_client, "check_gh_version", return_value=(2, 55, 0)), \
         patch.object(gh_client.shutil, "which", return_value="/usr/bin/gh"), \
         patch.object(gh_client.subprocess, "run",
                      return_value=_completed(stdout='{"number": 1, "title": "x"}')) as mrun:
        out = run_read("pr_view", "owner/repo", number=1)
    assert out["data"]["number"] == 1
    # Proves no shell: first positional arg is an argv LIST, and shell kwarg absent/false.
    called_argv = mrun.call_args.args[0]
    assert isinstance(called_argv, list)
    assert mrun.call_args.kwargs.get("shell", False) is False


def test_run_read_diff_op():
    with patch.object(gh_client, "check_gh_version", return_value=(2, 55, 0)), \
         patch.object(gh_client.shutil, "which", return_value="/usr/bin/gh"), \
         patch.object(gh_client.subprocess, "run",
                      return_value=_completed(stdout="diff --git a b\n")):
        out = run_read("pr_diff", "owner/repo", number=1)
    assert out["diff"].startswith("diff --git")


def test_run_read_nonzero_exit_raises():
    with patch.object(gh_client, "check_gh_version", return_value=(2, 55, 0)), \
         patch.object(gh_client.shutil, "which", return_value="/usr/bin/gh"), \
         patch.object(gh_client.subprocess, "run",
                      return_value=_completed(stderr="not found", returncode=1)):
        with pytest.raises(AgenticError):
            run_read("pr_view", "owner/repo", number=999)


def test_run_read_bad_json_raises():
    with patch.object(gh_client, "check_gh_version", return_value=(2, 55, 0)), \
         patch.object(gh_client.shutil, "which", return_value="/usr/bin/gh"), \
         patch.object(gh_client.subprocess, "run", return_value=_completed(stdout="not json")):
        with pytest.raises(AgenticError):
            run_read("pr_list", "owner/repo")
