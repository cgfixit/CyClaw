"""Tests for utils/numbat_cel.py — CEL monitor-only backend.

The default-off path must work without ``cel-python`` installed.  Tests that
need the evaluator skip when it is absent, except where CI sets
``CYCLAW_REQUIRE_CELPY=1`` (the CEL lane in ``.github/workflows/numbat-rules.yml``
and the CEL step on ``ci.yml``'s Linux leg), so a missing evaluator fails there
instead of passing as a skip.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from utils.numbat_cel import evaluate_cel_monitor, model_provider_for_role, monitor_request
from utils.numbat_emitter import _KNOWN_FIELDS, CONTENT_PREVIEW_MAX_CHARS, close_numbat_handles

_REPO = Path(__file__).resolve().parent.parent
_QUERY_HASH = "c" * 64

# The two sample rules config.yaml's numbat.cel comment documents. Kept
# verbatim here so test_sample_rules_are_the_documented_ones catches either
# side drifting.
SAMPLE_ESCALATION_ON_MISS = 'answer_model in ["grok", "claude"] && top_score < 0.05'
SAMPLE_CONTROL_REFUSED = 'answer_model == "hook-denied" || guardrail_blocked'


def _need_celpy():
    """importorskip, except where CI demands the evaluator actually run."""
    if os.environ.get("CYCLAW_REQUIRE_CELPY") == "1":
        import celpy  # noqa: F401 - an ImportError here fails the lane, by design

        return celpy
    return pytest.importorskip("celpy")


@pytest.fixture(autouse=True)
def _release_handles():
    """Release cached Numbat file handles so tmp_path teardown succeeds on Windows."""
    yield
    close_numbat_handles()


def _cel_cfg(tmp_path: Path, *, enabled: bool, rules: list, max_rule_ms: object = 20) -> dict:
    out = tmp_path / "numbat-events.ndjsonl"
    return {
        "numbat": {
            "enabled": True,
            "output_path": str(out),
            "cel": {"enabled": enabled, "rules": rules, "max_rule_ms": max_rule_ms},
        }
    }


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_disabled_returns_empty_and_does_not_import_celpy(tmp_path: Path):
    """When cel.enabled is false, cel-python must not enter sys.modules."""
    cfg = _cel_cfg(tmp_path, enabled=False, rules=['query_hash == "abc"'])
    assert evaluate_cel_monitor(query_hash="abc", cfg=cfg) == []

    script = (
        "import sys\n"
        "from utils.numbat_cel import evaluate_cel_monitor\n"
        "cfg = {'numbat': {'cel': {'enabled': False, 'rules': []}}}\n"
        "evaluate_cel_monitor(query_hash='abc', cfg=cfg)\n"
        "sys.exit(0 if 'celpy' not in sys.modules else 1)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=_REPO,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("enabled", ["true", 1, None, "yes"])
def test_only_literal_true_enables(tmp_path: Path, enabled):
    cfg = _cel_cfg(tmp_path, enabled=enabled, rules=['query_hash == "abc"'])
    assert evaluate_cel_monitor(query_hash="abc", cfg=cfg) == []


def test_enabled_rule_match_emits_allowed_tool_result(tmp_path: Path):
    _need_celpy()
    cfg = _cel_cfg(
        tmp_path,
        enabled=True,
        rules=['query_hash == "abc"', 'top_score > 0.1'],
    )
    monitor_request(
        query_hash="abc",
        top_score=0.05,
        answer_model="local",
        guardrail_blocked=False,
        guardrail_rails=[],
        model_provider="ollama",
        source_hashes=["h1"],
        llm_model="qwen3.8:27b-mlx",
        cfg=cfg,
    )
    out = Path(cfg["numbat"]["output_path"])
    records = _lines(out)
    assert len(records) == 1
    rec = records[0]
    # Monitor-only: the request was allowed, so the record must not claim a
    # denial (it used to be permission.denied / decision "denied").
    assert rec["event_type"] == "tool.result"
    assert rec["decision"] == "allowed"
    assert rec["confidence"] == "low"
    assert rec["tool_name"] == "cel_monitor"
    assert rec["tags"] == ["cyclaw", "cel_monitor", "monitor_only", "rules:0"]
    assert rec["model"] == "qwen3.8:27b-mlx"
    assert rec["model_provider"] == "ollama"
    assert rec["evidence"]["artifact_type"] == "cel_monitor"
    for denial_field in ("approval_reason", "approval_decision", "approval_required"):
        assert denial_field not in rec
    # "abc" is not a SHA-256 digest, so it never reaches the stream.
    assert json.loads(rec["content_preview"]) == {"cel_rules_matched": [0]}
    assert "query" not in json.dumps(rec)
    assert "abc" not in json.dumps(rec)
    assert set(rec) <= _KNOWN_FIELDS


def test_match_preview_carries_the_query_hash_join_key(tmp_path: Path):
    _need_celpy()
    cfg = _cel_cfg(tmp_path, enabled=True, rules=[f'query_hash == "{_QUERY_HASH}"'])
    monitor_request(query_hash=_QUERY_HASH, answer_model="local", cfg=cfg)
    rec = _lines(Path(cfg["numbat"]["output_path"]))[0]
    assert json.loads(rec["content_preview"]) == {"query_hash": _QUERY_HASH, "cel_rules_matched": [0]}
    # A preview that fits is complete, so it carries no truncation flag.
    assert "content_preview_truncated" not in rec


def test_query_hash_opt_out_keeps_it_out_of_the_stream(tmp_path: Path):
    _need_celpy()
    cfg = _cel_cfg(tmp_path, enabled=True, rules=[f'query_hash == "{_QUERY_HASH}"'])
    cfg["logging"] = {"audit_fields": {"include_query_hash": False}}
    monitor_request(query_hash=_QUERY_HASH, answer_model="local", cfg=cfg)
    rec = _lines(Path(cfg["numbat"]["output_path"]))[0]
    # The rule still sees the hash; only the emitted record drops it.
    assert json.loads(rec["content_preview"]) == {"cel_rules_matched": [0]}
    assert _QUERY_HASH not in json.dumps(rec)


def test_role_is_never_written_as_the_model(tmp_path: Path):
    _need_celpy()
    cfg = _cel_cfg(tmp_path, enabled=True, rules=['answer_model == "hook-denied"'])
    monitor_request(answer_model="hook-denied", model_provider="", cfg=cfg)
    rec = _lines(Path(cfg["numbat"]["output_path"]))[0]
    # No model ran and no provider served it: both fields are omitted rather
    # than filled with the role or a guessed provider.
    assert "model" not in rec
    assert "model_provider" not in rec


def test_long_match_list_stays_within_the_schema_cap(tmp_path: Path):
    _need_celpy()
    rules = ["true"] * 60
    cfg = _cel_cfg(tmp_path, enabled=True, rules=rules)
    monitor_request(query_hash=_QUERY_HASH, answer_model="local", cfg=cfg)
    rec = _lines(Path(cfg["numbat"]["output_path"]))[0]
    assert len(rec["content_preview"]) <= CONTENT_PREVIEW_MAX_CHARS
    # Still parseable JSON: the indices are dropped from the preview whole
    # (the tags keep them), never cut mid-string, and the drop is flagged so
    # the shortened preview never reads as complete.
    assert json.loads(rec["content_preview"]) == {"query_hash": _QUERY_HASH}
    assert f"rules:{','.join(str(i) for i in range(60))}" in rec["tags"]
    assert rec["content_preview_truncated"] is True


def test_enabled_no_match_does_not_emit(tmp_path: Path):
    _need_celpy()
    cfg = _cel_cfg(tmp_path, enabled=True, rules=['query_hash == "xyz"'])
    monitor_request(query_hash="abc", cfg=cfg)
    out = Path(cfg["numbat"]["output_path"])
    assert _lines(out) == []


def test_malformed_rule_is_fail_open(tmp_path: Path):
    _need_celpy()
    cfg = _cel_cfg(tmp_path, enabled=True, rules=['this is not valid CEL'])
    # Must not raise, and must not emit because the rule cannot compile.
    monitor_request(query_hash="abc", cfg=cfg)
    out = Path(cfg["numbat"]["output_path"])
    assert _lines(out) == []


def test_bad_rule_type_is_skipped(tmp_path: Path):
    _need_celpy()
    cfg = _cel_cfg(tmp_path, enabled=True, rules=[123, 'query_hash == "abc"'])
    matches = evaluate_cel_monitor(query_hash="abc", cfg=cfg)
    assert matches == [1]


def test_rule_that_errors_at_evaluation_is_fail_open(tmp_path: Path):
    _need_celpy()
    # Compiles, but indexes past the end of an empty list at evaluation time.
    cfg = _cel_cfg(tmp_path, enabled=True, rules=['source_hashes[3] == "x"', 'query_hash == "abc"'])
    assert evaluate_cel_monitor(query_hash="abc", source_hashes=[], cfg=cfg) == [1]


@pytest.mark.parametrize("max_rule_ms", ["20", None, -5, 0, True, [20]])
def test_malformed_budget_never_raises(tmp_path: Path, max_rule_ms):
    """A non-numeric max_rule_ms used to raise TypeError out of the compare
    that sits outside the per-rule guard, silently disabling every rule."""
    _need_celpy()
    cfg = _cel_cfg(tmp_path, enabled=True, rules=['query_hash == "abc"'], max_rule_ms=max_rule_ms)
    assert evaluate_cel_monitor(query_hash="abc", cfg=cfg) == [0]


def test_sample_rules_are_the_documented_ones():
    text = (_REPO / "config.yaml").read_text(encoding="utf-8")
    block = text[text.index("\n  cel:\n") - 2500:text.index("\n  cel:\n")]
    documented = re.findall(r"^\s*#\s+- '(.+)'$", block, flags=re.MULTILINE)
    assert documented == [SAMPLE_ESCALATION_ON_MISS, SAMPLE_CONTROL_REFUSED]


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"answer_model": "grok", "top_score": 0.01}, [0]),
        ({"answer_model": "claude", "top_score": 0.049}, [0]),
        ({"answer_model": "grok", "top_score": 0.5}, []),
        ({"answer_model": "local", "top_score": 0.01}, []),
        ({"answer_model": "hook-denied", "top_score": 0.01}, [1]),
        ({"answer_model": "local", "top_score": 0.9, "guardrail_blocked": True}, [1]),
        ({"answer_model": "offline-best-effort", "top_score": 0.02}, []),
    ],
)
def test_sample_rules_match_what_they_claim(tmp_path: Path, fields, expected):
    _need_celpy()
    cfg = _cel_cfg(tmp_path, enabled=True, rules=[SAMPLE_ESCALATION_ON_MISS, SAMPLE_CONTROL_REFUSED])
    assert evaluate_cel_monitor(cfg=cfg, **fields) == expected


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("grok", "xai"),
        ("claude", "anthropic"),
        ("local", "ollama"),
        ("offline-best-effort", "ollama"),
        ("hook-denied", ""),
        ("guardrail-blocked", ""),
        ("external-unavailable", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_model_provider_for_role(role, expected):
    assert model_provider_for_role(role, {}) == expected


def test_model_provider_for_role_uses_the_configured_local_provider():
    cfg = {"models": {"local_llm": {"provider": "lmstudio"}}}
    assert model_provider_for_role("local", cfg) == "lmstudio"
    assert model_provider_for_role("offline-best-effort", cfg) == "lmstudio"


@pytest.mark.parametrize("cfg", [None, {"models": None}, {"models": []}, {"models": {"local_llm": "x"}},
                                 {"models": {"local_llm": {"provider": ""}}}])
def test_model_provider_for_role_survives_malformed_config(cfg):
    assert model_provider_for_role("local", cfg) == "ollama"
