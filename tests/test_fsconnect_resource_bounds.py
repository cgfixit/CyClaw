"""Execute the enumeration and subprocess limits without allocating large inputs."""

import subprocess
import sys

import pytest
import yaml

from agentic.fsconnect.client import FsClient
from agentic.fsconnect.config import load_fsconnect_config
from agentic.fsconnect.pathsafe import EntryBudget, ScopedRoots
from utils import ops_runner
from utils.errors import FsConnectError
from utils.logger import _get_config, reset_config_cache


def test_raw_entry_budget_counts_hidden_names_and_preserves_maintenance(tmp_path):
    for name in (".env", ".DS_Store", "ordinary.txt"):
        (tmp_path / name).touch()
    with ScopedRoots([str(tmp_path)]) as roots:
        with pytest.raises(FsConnectError, match="entry budget") as error:
            roots.list_dir("", skip_macos_metadata=True, budget=EntryBudget(2))
        assert error.value.code == "FSCONNECT_LIMIT"
        assert any(entry["name"] == "ordinary.txt" for entry in roots.list_dir(""))


def test_glob_shares_budget_across_nonmatching_directories(tmp_path, monkeypatch):
    from agentic.fsconnect import client

    monkeypatch.setattr(client, "_MAX_ENUMERATED_ENTRIES", 4)
    share = tmp_path / "share"
    for name in ("a", "b"):
        (share / name).mkdir(parents=True)
        (share / name / "note.txt").touch()
        (share / name / "other.txt").touch()
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}},
        "policy": {"privacy": {}},
        "fsconnect": {"enabled": True, "allowed_roots": [str(share)], "scan_content": False},
    }), encoding="utf-8")
    reset_config_cache()
    try:
        with FsClient(_get_config(str(config)), load_fsconnect_config(str(config)), str(config)) as fs:
            with pytest.raises(FsConnectError, match="entry budget"):
                fs.fs_glob(pattern="*.no-match")
            assert fs.fs_list("a")["count"] == 2
    finally:
        reset_config_cache()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_real_child_output_is_bounded(monkeypatch, stream):
    monkeypatch.setattr(ops_runner, "_MAX_OPS_OUTPUT_BYTES", 1024)
    with pytest.raises(ops_runner.OpsOutputLimitError):
        ops_runner._run([sys.executable, "-c", f"import sys; sys.{stream}.write('x' * 65536)"])


def test_real_child_control_and_timeout():
    result = ops_runner._run([sys.executable, "-c", "import sys; sys.stdout.write('caf\\xe9\\r\\n')"])
    assert result.returncode == 0
    assert result.stdout == "caf\u00e9\n"
    with pytest.raises(subprocess.TimeoutExpired):
        ops_runner._run([sys.executable, "-c", "import time; time.sleep(10)"], timeout_sec=1)
