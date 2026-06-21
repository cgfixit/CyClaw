"""Tests for agentic.selftest -- pre-flight smoke (tolerates missing gh)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentic.selftest import run_self_test
from utils.logger import reset_config_cache


@pytest.fixture(autouse=True)
def _reset():
    reset_config_cache()
    yield
    reset_config_cache()


def _config(tmp_path: Path) -> str:
    cfg = {
        "logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}},
        "policy": {"prompt_filter": {"banned_patterns": ["ignore previous instructions"]},
                   "privacy": {}},
        "agentic": {
            "enabled": True,
            "repo": "CGFixIT/CyClaw",
            "mode": "read",
            "writes_enabled": False,
            "gh_min_version": "2.40.0",
            "registry_path": "data/agentic/skills_registry.json",
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def test_selftest_all_pass_without_gh(tmp_path):
    # Even with gh absent (SKIP counts as pass), the suite should fully pass.
    passed, total, lines = run_self_test(_config(tmp_path))
    assert passed == total
    assert total >= 5
    joined = "\n".join(lines)
    assert "Write gate refuses" in joined
    assert "injection payload" in joined


def test_selftest_bad_config_skips_rest(tmp_path):
    cfg = {"logging": {"audit_file": str(tmp_path / "a.jsonl")}}  # no agentic block
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    passed, total, lines = run_self_test(str(path))
    # A missing agentic block is a real failure to surface: check 01 fails, the
    # rest are skipped (skips count as pass), so exactly one check fails.
    assert total == 5
    assert passed == total - 1
    assert "no config" in "\n".join(lines).lower()
