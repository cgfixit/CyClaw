"""Unit tests for utils/external_pre_hook.py fail-closed branches.

No wall-clock sleeps: subprocess.run is monkeypatched.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from utils.external_pre_hook import (
    DEFAULT_TIMEOUT_SEC,
    MAX_TIMEOUT_SEC,
    MIN_TIMEOUT_SEC,
    REASON_CODES,
    _normalize_timeout,
    hook_readiness,
    last_verdict,
    run_pre_action_hook,
)
from utils.numbat_emitter import close_numbat_handles
from utils.numbat_gate import clear_readiness_cache

_TEST_QUERY_HASH = "a" * 64


@pytest.fixture(autouse=True)
def _release_numbat_handles():
    """Release cached file handles so tmp_path teardown succeeds on Windows."""
    clear_readiness_cache()
    yield
    clear_readiness_cache()
    close_numbat_handles()


def _hook_config(
    tmp_path: Path,
    *,
    enabled: bool = True,
    emit_verdict: bool = True,
    command: tuple[str, ...] = ("false",),
) -> dict:
    out = tmp_path / "numbat-events.ndjsonl"
    return {
        "numbat": {"enabled": True, "output_path": str(out)},
        "policy": {
            "fallback": {
                "pre_action_hook": {
                    "enabled": enabled,
                    "command": list(command),
                    "emit_verdict": emit_verdict,
                }
            }
        },
    }


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_invalid_command_type_denies():
    cfg = {"policy": {"fallback": {"pre_action_hook": {"enabled": True, "command": "not-a-list"}}}}
    result = run_pre_action_hook("grok", "grok-4.5", "abc", cfg)
    assert result["verdict"] == "deny"
    assert "invalid hook command" in result["reason"]


def test_list_with_non_string_element_denies():
    cfg = {"policy": {"fallback": {"pre_action_hook": {"enabled": True, "command": ["python", 123]}}}}
    result = run_pre_action_hook("grok", "grok-4.5", "abc", cfg)
    assert result["verdict"] == "deny"


def test_timeout_expired_denies(monkeypatch):
    cfg = {"policy": {"fallback": {"pre_action_hook": {"enabled": True, "command": ["sleep", "60"]}}}}

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 5))

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    result = run_pre_action_hook("grok", "grok-4.5", "abc", cfg)
    assert result["verdict"] == "deny"
    assert "timed out" in result["reason"]


def test_normalize_timeout_clamps_and_defaults():
    assert _normalize_timeout(None) == DEFAULT_TIMEOUT_SEC
    assert _normalize_timeout("not-an-int") == DEFAULT_TIMEOUT_SEC
    assert _normalize_timeout(0) == MIN_TIMEOUT_SEC
    assert _normalize_timeout(-5) == MIN_TIMEOUT_SEC
    assert _normalize_timeout(100) == MAX_TIMEOUT_SEC
    assert _normalize_timeout(7) == 7


def test_hook_disabled_returns_allow():
    cfg = {"policy": {"fallback": {"pre_action_hook": {"enabled": False, "command": ["true"]}}}}
    assert run_pre_action_hook("grok", "grok-4.5", "abc", cfg) == {"verdict": "allow"}


def test_missing_config_returns_allow():
    assert run_pre_action_hook("grok", "grok-4.5", "abc", None) == {"verdict": "allow"}


def test_emit_verdict_false_no_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path, emit_verdict=False)

    def _exit_2(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=2, stdout=b"", stderr=b"deny")

    monkeypatch.setattr(subprocess, "run", _exit_2)
    result = run_pre_action_hook("grok", "grok-4.5", "abc", cfg)
    assert result["verdict"] == "deny"
    assert _lines(Path(cfg["numbat"]["output_path"])) == []


def test_emit_verdict_true_exit_2_emits_permission_denied(tmp_path: Path):
    cfg = _hook_config(
        tmp_path,
        command=(
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('blocked'); sys.exit(2)",
        ),
    )
    result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert result["verdict"] == "deny"
    assert "blocked" in result["reason"]

    records = _lines(Path(cfg["numbat"]["output_path"]))
    assert len(records) == 1
    rec = records[0]
    assert rec["event_type"] == "permission.denied"
    assert rec["decision"] == "denied"
    assert rec["model"] == "grok-4.5"
    assert rec["model_provider"] == "xai"
    assert rec["tool_name"] == "external_llm_call"
    assert rec["approval_reason"] == "hook_denied"
    assert rec["entrypoint"] == "cyclaw"
    assert "cyclaw" in rec["tags"]
    # Schema 0.3.0 additionalProperties:false — the hash rides inside
    # content_preview, never as a top-level field.
    assert "query_hash" not in rec
    assert json.loads(rec["content_preview"]) == {"query_hash": _TEST_QUERY_HASH}
    assert "blocked" not in json.dumps(rec)


def test_emit_verdict_true_timeout_emits_network_indicator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path, command=("sleep", "60"))

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 5))

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    result = run_pre_action_hook("claude", "claude-sonnet-4", _TEST_QUERY_HASH, cfg)
    assert result["verdict"] == "deny"

    records = _lines(Path(cfg["numbat"]["output_path"]))
    assert len(records) == 1
    rec = records[0]
    assert rec["event_type"] == "network.indicator"
    assert rec["confidence"] == "low"
    assert rec["model_provider"] == "anthropic"
    assert "query_hash" not in rec
    assert json.loads(rec["content_preview"]) == {"query_hash": _TEST_QUERY_HASH}


def test_emit_verdict_true_other_exit_emits_network_indicator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)

    def _exit_7(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=7, stdout=b"boom", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _exit_7)
    result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert result["verdict"] == "deny"

    records = _lines(Path(cfg["numbat"]["output_path"]))
    assert len(records) == 1
    rec = records[0]
    assert rec["event_type"] == "network.indicator"
    assert rec["confidence"] == "low"
    assert "query_hash" not in rec
    assert json.loads(rec["content_preview"]) == {"query_hash": _TEST_QUERY_HASH}


def test_emit_verdict_invalid_query_hash_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)

    def _exit_7(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=7, stdout=b"boom", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _exit_7)
    result = run_pre_action_hook("grok", "grok-4.5", "abc", cfg)
    assert result["verdict"] == "deny"

    records = _lines(Path(cfg["numbat"]["output_path"]))
    assert len(records) == 1
    rec = records[0]
    # Non-64-hex query_hash is dropped: no top-level field, no content_preview.
    assert "query_hash" not in rec
    assert "query_hash" not in rec.get("content_preview", "")


def test_emit_verdict_query_hash_omitted_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """logging.audit_fields.include_query_hash: false must suppress content_preview.

    Regression for a Codex review finding on PR #1183: content_preview was
    gated only on hash format, not on the operator's opt-out -- silently
    reintroducing an unsalted, dictionary-guessable identifier into the
    Numbat stream even when include_query_hash is explicitly false.
    """
    cfg = _hook_config(tmp_path)
    cfg["logging"] = {"audit_fields": {"include_query_hash": False}}

    def _exit_2(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=2, stdout=b"", stderr=b"deny")

    monkeypatch.setattr(subprocess, "run", _exit_2)
    result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert result["verdict"] == "deny"

    records = _lines(Path(cfg["numbat"]["output_path"]))
    assert len(records) == 1
    rec = records[0]
    # A valid 64-hex hash is still dropped -- the opt-out wins even though
    # the format check alone would have allowed it through.
    assert "query_hash" not in rec
    assert "content_preview" not in rec


def test_payload_query_hash_present_regardless_of_audit_hash_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The hook's stdin payload always carries query_hash -- a documented,
    unconditional contract (config.yaml's pre_action_hook block, graph.py's pre_action_hook_node
    docstring, docs/plans/NUMBAT_AND_ALWAYS_ON_ROADMAP.md Step 2). Regression
    for a Codex review finding on PR #1187: an earlier revision of this test
    asserted the opposite (payload omits query_hash under
    logging.audit_fields.include_query_hash: false), which both broke that
    documented contract and could make a fail-closed hook deny every call.

    include_query_hash is not a "hide the hash everywhere" switch -- per
    utils/logger.py::audit_log, false means the RAW query text is left in the
    primary audit.jsonl record (see
    test_disabling_hashing_persists_raw_text__documented_leak), so a hook
    receiving a one-way hash of that same query on stdin discloses nothing
    the operator's own choice hasn't already exposed on the primary log.
    """
    captured: list[bytes] = []

    def _capture(*args, **kwargs):
        captured.append(kwargs["input"])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)

    cfg = _hook_config(tmp_path)
    assert run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)["verdict"] == "allow"
    assert json.loads(captured[-1])["query_hash"] == _TEST_QUERY_HASH

    cfg["logging"] = {"audit_fields": {"include_query_hash": False}}
    assert run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)["verdict"] == "allow"
    optout_payload = json.loads(captured[-1])
    assert optout_payload["query_hash"] == _TEST_QUERY_HASH
    assert optout_payload["provider"] == "grok"


def test_emit_failure_is_fail_soft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)

    def _exit_2(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=2, stdout=b"", stderr=b"deny")

    monkeypatch.setattr(subprocess, "run", _exit_2)

    def _boom(**kwargs):
        raise RuntimeError("emit failed")

    monkeypatch.setattr("utils.numbat_emitter.emit_numbat_event", _boom)
    result = run_pre_action_hook("grok", "grok-4.5", "abc", cfg)
    assert result["verdict"] == "deny"
    assert _lines(Path(cfg["numbat"]["output_path"])) == []


# ---------------------------------------------------------------------------
# Issue #1458 Phases 1-2: engines, reason codes, verdict events, diagnostics
# ---------------------------------------------------------------------------


def _allow_run(*args, **kwargs):
    return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=b"", stderr=b"")


def test_every_reason_code_is_in_the_vocabulary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)
    monkeypatch.setattr(subprocess, "run", _allow_run)
    assert run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)["reason_code"] in REASON_CODES


def test_enabled_with_empty_command_denies(tmp_path: Path):
    """Used to ALLOW every call: a control the operator switched on that did nothing."""
    cfg = _hook_config(tmp_path, command=())
    result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    rec = _lines(Path(cfg["numbat"]["output_path"]))[0]
    assert rec["event_type"] == "network.indicator"
    assert rec["decision"] == "denied"
    assert "hook_misconfigured" in rec["tags"]


def test_enabled_with_missing_command_key_denies():
    cfg = {"policy": {"fallback": {"pre_action_hook": {"enabled": True}}}}
    assert run_pre_action_hook("grok", "grok-4.5", "abc", cfg)["verdict"] == "deny"


def test_unknown_engine_denies(tmp_path: Path):
    cfg = _hook_config(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"]["engine"] = "opa"
    result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert "engine:unknown" in _lines(Path(cfg["numbat"]["output_path"]))[0]["tags"]


def test_allow_verdict_is_emitted_as_the_egress_about_to_happen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)
    cfg["models"] = {"grok": {"base_url": "https://api.x.ai/v1"}}
    monkeypatch.setattr(subprocess, "run", _allow_run)
    result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert (result["verdict"], result["reason_code"]) == ("allow", "hook_allowed")
    records = _lines(Path(cfg["numbat"]["output_path"]))
    assert len(records) == 1
    rec = records[0]
    assert rec["event_type"] == "network.indicator"
    assert rec["decision"] == "allowed"
    assert rec["url"] == "https://api.x.ai"
    assert rec["confidence"] == "high"
    assert rec["tags"] == ["cyclaw", "pre_action_hook", "hook_allowed", "engine:command"]
    assert rec["evidence"]["artifact_type"] == "pre_action_hook"
    assert json.loads(rec["content_preview"]) == {"query_hash": _TEST_QUERY_HASH}


def test_verdict_url_carries_no_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """utils/endpoint_trust.py pins only the hostname, so a base_url with
    userinfo, a path segment or a key in its query passes it; the persistent
    stream keeps only the origin."""
    cfg = _hook_config(tmp_path)
    cfg["models"] = {"grok": {"base_url": "https://ops:s3cr3t-tok@api.x.ai/p4th-tok/v1?api_key=k3y-val#frag"}}
    monkeypatch.setattr(subprocess, "run", _allow_run)
    run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    raw = Path(cfg["numbat"]["output_path"]).read_text(encoding="utf-8")
    assert json.loads(raw.splitlines()[0])["url"] == "https://api.x.ai"
    assert "s3cr3t-tok" not in raw
    assert "p4th-tok" not in raw
    assert "k3y-val" not in raw


def test_broken_hook_verdicts_say_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Timeouts/crashes used to carry no decision at all; they are denials."""
    cfg = _hook_config(tmp_path)

    def _exit_7(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=7, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _exit_7)
    run_pre_action_hook("claude", "claude-sonnet-5", _TEST_QUERY_HASH, cfg)
    rec = _lines(Path(cfg["numbat"]["output_path"]))[0]
    assert (rec["event_type"], rec["decision"], rec["confidence"]) == ("network.indicator", "denied", "low")
    assert "hook_failure" in rec["tags"]


def test_emit_verdict_absent_means_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """config.yaml ships emit_verdict: true; a config that omits the key keeps the old default."""
    cfg = _hook_config(tmp_path)
    del cfg["policy"]["fallback"]["pre_action_hook"]["emit_verdict"]
    monkeypatch.setattr(subprocess, "run", _allow_run)
    assert run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)["verdict"] == "allow"
    assert _lines(Path(cfg["numbat"]["output_path"])) == []


@pytest.mark.parametrize("emit_value", ["true", 1, "yes"])
def test_only_a_literal_true_emit_verdict_emits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, emit_value):
    cfg = _hook_config(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"]["emit_verdict"] = emit_value
    monkeypatch.setattr(subprocess, "run", _allow_run)
    run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert _lines(Path(cfg["numbat"]["output_path"])) == []


def test_numbat_engine_is_dispatched_and_its_verdict_emitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"]["engine"] = "numbat"
    seen: dict = {}

    def _evaluate(provider, model, query_hash, cfg_arg, *, timeout):
        seen.update(provider=provider, model=model, query_hash=query_hash, timeout=timeout)
        return {"verdict": "allow", "reason_code": "hook_allowed", "reason": "r",
                "monitor_matches": ["acme.watch"]}

    monkeypatch.setattr("utils.numbat_gate.evaluate", _evaluate)
    result = run_pre_action_hook("claude", "claude-sonnet-5", _TEST_QUERY_HASH, cfg)
    assert result["verdict"] == "allow"
    assert seen == {"provider": "claude", "model": "claude-sonnet-5", "query_hash": _TEST_QUERY_HASH, "timeout": 5}
    rec = _lines(Path(cfg["numbat"]["output_path"]))[0]
    assert "engine:numbat" in rec["tags"]
    assert "monitor_match:acme.watch" in rec["tags"]


def test_numbat_engine_deny_is_a_policy_denial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"]["engine"] = "numbat"
    monkeypatch.setattr(
        "utils.numbat_gate.evaluate",
        lambda *a, **k: {"verdict": "deny", "reason_code": "hook_denied", "reason": "denied by Numbat rule(s): x"},
    )
    result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_denied")
    rec = _lines(Path(cfg["numbat"]["output_path"]))[0]
    assert rec["event_type"] == "permission.denied"
    assert rec["approval_reason"] == "hook_denied"
    # The rule-naming reason text stays out of the derived stream.
    assert "denied by Numbat rule" not in json.dumps(rec)


def test_numbat_engine_that_cannot_load_denies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import builtins

    cfg = _hook_config(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"]["engine"] = "numbat"
    real_import = builtins.__import__

    def _no_gate(name, *args, **kwargs):
        if name == "utils.numbat_gate":
            raise ImportError("gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_gate)
    result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_error")


@pytest.mark.parametrize(
    ("block", "warns"),
    [
        ({"verdict_mode": "enforce"}, False),
        ({"fail_mode": "enforce"}, False),
        ({}, False),
        ({"verdict_mode": "monitor"}, True),
        ({"fail_mode": "monitor"}, True),
        # verdict_mode wins over its old name.
        ({"verdict_mode": "enforce", "fail_mode": "monitor"}, False),
    ],
)
def test_verdict_mode_is_always_enforce(tmp_path, monkeypatch, caplog, block, warns):
    cfg = _hook_config(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"].update(block)

    def _exit_2(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=2, stdout=b"", stderr=b"no")

    monkeypatch.setattr(subprocess, "run", _exit_2)
    with caplog.at_level(logging.WARNING, logger="cyclaw.external_pre_hook"):
        result = run_pre_action_hook("grok", "grok-4.5", _TEST_QUERY_HASH, cfg)
    # A deny always blocks: no setting turns a deny into an allow.
    assert result["verdict"] == "deny"
    assert any("verdict_mode" in r.getMessage() for r in caplog.records) is warns


def test_last_verdict_records_codes_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)

    def _exit_2(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=2, stdout=b"", stderr=b"secret stderr text")

    monkeypatch.setattr(subprocess, "run", _exit_2)
    run_pre_action_hook("claude", "claude-sonnet-5", _TEST_QUERY_HASH, cfg)
    last = last_verdict()
    assert last is not None
    assert {k: last[k] for k in ("verdict", "reason_code", "provider", "engine")} == {
        "verdict": "deny", "reason_code": "hook_denied", "provider": "claude", "engine": "command",
    }
    assert "secret stderr text" not in json.dumps(last)


def test_readiness_is_none_when_the_hook_is_off():
    assert hook_readiness({"policy": {"fallback": {"pre_action_hook": {"enabled": False}}}}) is None
    assert hook_readiness(None) is None


def test_readiness_of_a_resolvable_command(tmp_path: Path):
    cfg = _hook_config(tmp_path, command=(sys.executable, "-c", "pass"))
    assert hook_readiness(cfg) == (True, None)


@pytest.mark.parametrize("command", [(), ("",), ("definitely-not-a-binary-cyclaw-1458",)])
def test_readiness_flags_a_command_that_cannot_run(tmp_path: Path, command):
    ready, problem = hook_readiness(_hook_config(tmp_path, command=command))
    assert ready is False
    assert "denied" in problem
    # Fixed phrases: the argv itself never reaches the unauthenticated /health.
    assert "definitely-not-a-binary" not in problem


def test_readiness_flags_an_unknown_engine(tmp_path: Path):
    cfg = _hook_config(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"]["engine"] = "opa"
    assert hook_readiness(cfg)[0] is False


def test_readiness_delegates_to_the_numbat_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _hook_config(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"]["engine"] = "numbat"
    seen: list[float] = []

    def _readiness(cfg_arg, *, timeout):
        seen.append(timeout)
        return False, "numbat binary not found"

    cfg["policy"]["fallback"]["pre_action_hook"]["timeout_sec"] = 2
    monkeypatch.setattr("utils.numbat_gate.readiness", _readiness)
    assert hook_readiness(cfg) == (False, "numbat binary not found")
    assert seen == [2]  # the probe decision gets the call's own timeout_sec


def test_command_readiness_is_bounded_and_runs_once_at_a_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # /health is unauthenticated: a PATH lookup stuck on a stalled mount must
    # neither hold the caller past timeout_sec nor start one lookup per call.
    cfg = _hook_config(tmp_path, command=("cyclaw-hook-1458",))
    cfg["policy"]["fallback"]["pre_action_hook"]["timeout_sec"] = 1
    started, release = threading.Event(), threading.Event()
    lookups: list[str] = []

    def _which(name):
        lookups.append(name)
        started.set()
        release.wait(30)
        return None

    monkeypatch.setattr("utils.external_pre_hook.shutil.which", _which)
    first: list[tuple[bool, str | None] | None] = []
    worker = threading.Thread(target=lambda: first.append(hook_readiness(cfg)))
    clock = time.monotonic()
    worker.start()
    try:
        assert started.wait(30)
        ready, problem = hook_readiness(cfg)
        assert (ready, "still running" in problem) == (False, True)
        worker.join(10)
        elapsed = time.monotonic() - clock
    finally:
        release.set()
        worker.join(30)
        for thread in threading.enumerate():
            if thread.name == "numbat-gate":
                thread.join(30)
    assert elapsed < 10
    assert first and first[0][0] is False and "did not finish" in first[0][1]
    assert lookups == ["cyclaw-hook-1458"]
