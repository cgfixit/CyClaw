"""Tests for utils/numbat_gate.py, the pre-action hook's Numbat engine (#1458 Phase 1).

Two halves:

* Unit tests replace ``subprocess.run`` inside the engine, so every verdict
  branch is exercised deterministically on every OS with no binary.
* ``TestAgainstThePinnedCli`` runs the real Numbat 0.2.0 binary (``NUMBAT`` or
  ``numbat`` on PATH) against ``tests/fixtures/numbat/gate-rules``. It skips
  without the binary, except in numbat-rules.yml's lane, where
  ``CYCLAW_REQUIRE_NUMBAT=1`` turns a missing binary into a failure.

Conftest-free on purpose: that lane runs this module with ``--noconftest``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, NoReturn

import pytest

from utils import numbat_gate
from utils.numbat_emitter import CONTENT_PREVIEW_MAX_CHARS, close_numbat_handles

_REPO = Path(__file__).resolve().parent.parent
GATE_RULES = _REPO / "tests" / "fixtures" / "numbat" / "gate-rules"
_HASH = "d" * 64


@pytest.fixture(autouse=True)
def _fresh_state():
    numbat_gate.clear_readiness_cache()
    yield
    numbat_gate.clear_readiness_cache()
    close_numbat_handles()


def _cfg(tmp_path: Path, *, dirs: list[str] | None = None, binary: str | None = None, **extra: Any) -> dict:
    cfg: dict[str, Any] = {
        "numbat": {"enabled": True, "output_path": str(tmp_path / "numbat-events.ndjsonl")},
        "models": {
            "grok": {"base_url": "https://api.x.ai/v1", "model": "grok-4.5"},
            "claude": {"base_url": "https://api.anthropic.com/v1", "model": "claude-sonnet-5"},
        },
        "policy": {"fallback": {"pre_action_hook": {"numbat": {
            "binary": binary if binary is not None else sys.executable,
            "rules_dirs": dirs if dirs is not None else [str(tmp_path / "rules")],
        }}}},
    }
    cfg.update(extra)
    return cfg


def _rules_dir(tmp_path: Path, *rules: tuple[str, bool]) -> Path:
    """Write minimal rule files: (id, enforce) pairs."""
    root = tmp_path / "rules"
    root.mkdir(exist_ok=True)
    for rule_id, enforce in rules:
        lines = [f"id: {rule_id}", 'version: "1"', "title: t", "severity: high",
                 'expr: event.event_type == "network.indicator"']
        if enforce:
            lines.append("enforce: true")
        (root / f"{rule_id.replace('.', '_')}.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


class _FakeCli:
    """Stands in for the numbat binary: answers from what the test sets.

    ``version`` answers the engine's pinned-release check (the pinned line by
    default), and ``rules check`` (/health) passes. A ``rules test`` call reports the engine's canary rule -- the
    evidence that the call was evaluated -- then ``matches``, unless
    ``canary`` is False or ``stdout`` replaces the output wholesale.
    ``raises`` applies to the rules test, ``version_raises`` to the version
    check; ``on_rules_test`` sees the argv before the fake answers.
    """

    def __init__(self, *, matches: list[str] | None = None, returncode: int = 0, stdout: str | None = None,
                 stderr: str = "", raises: BaseException | None = None,
                 version: str = numbat_gate.PINNED_VERSION_LINE, version_raises: BaseException | None = None,
                 canary: bool = True, on_rules_test: Any = None) -> None:
        self.matches = matches or []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raises = raises
        self.version = version
        self.version_raises = version_raises
        self.canary = canary
        self.on_rules_test = on_rules_test
        self.calls: list[list[str]] = []
        self.version_calls: list[list[str]] = []
        self.check_calls: list[list[str]] = []
        self.fixture_events: list[dict] = []

    def __call__(self, argv, **kwargs):
        if list(argv[1:]) == ["version"]:
            self.version_calls.append(list(argv))
            if self.version_raises is not None:
                raise self.version_raises
            return subprocess.CompletedProcess(argv, 0, stdout=f"{self.version}\n", stderr="")
        if list(argv[1:3]) == ["rules", "check"]:
            self.check_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        self.calls.append(list(argv))
        if self.on_rules_test is not None:
            self.on_rules_test(argv)
        if self.raises is not None:
            raise self.raises
        fixture = Path(argv[argv.index("--fixture") + 1])
        event = json.loads(fixture.read_text(encoding="utf-8"))
        self.fixture_events.append(event)
        rules = ([numbat_gate.CANARY_RULE_ID] if self.canary else []) + self.matches
        out = self.stdout if self.stdout is not None else "".join(
            f"{rule}\t{event['event_id']}\n" for rule in rules
        )
        return subprocess.CompletedProcess(argv, self.returncode, stdout=out, stderr=self.stderr)


def _fake(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> _FakeCli:
    fake = _FakeCli(**kwargs)
    monkeypatch.setattr(numbat_gate, "_run_cli", fake)
    return fake


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

def test_enforce_rule_match_denies(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, matches=["acme.deny"])
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert result["verdict"] == "deny"
    assert result["reason_code"] == "hook_denied"
    assert "acme.deny" in result["reason"]


def test_no_match_allows(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, matches=[])
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert result == {"verdict": "allow", "reason_code": "hook_allowed", "reason": "no enforce rule matched"}


def test_monitor_rule_match_allows_and_reports(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True), ("acme.watch", False))
    _fake(monkeypatch, matches=["acme.watch"])
    result = numbat_gate.evaluate("claude", "claude-sonnet-5", _HASH, _cfg(tmp_path), timeout=5)
    assert result["verdict"] == "allow"
    assert result["monitor_matches"] == ["acme.watch"]


def test_disabled_enforce_rule_cannot_deny(tmp_path, monkeypatch):
    root = _rules_dir(tmp_path)
    (root / "off.yaml").write_text(
        'id: acme.off\nversion: "1"\ntitle: t\nseverity: high\nenabled: false\nenforce: true\n'
        'expr: event.event_type == "network.indicator"\n', encoding="utf-8")
    # Numbat never reports a disabled rule; if a future CLI did, the rule is
    # still classified as unable to deny, and an unknown/mislabelled match
    # below is what fails closed.
    known, enforcing = numbat_gate.classify_rules([root])
    assert known == {"acme.off"} and enforcing == set()


def _flagged_rule(tmp_path: Path, flags: str, name: str = "r.yaml") -> Path:
    """One rule, acme.r, with ``flags`` (raw YAML lines) written verbatim."""
    root = _rules_dir(tmp_path)
    (root / name).write_text(
        f'id: acme.r\nversion: "1"\ntitle: t\nseverity: high\n{flags}'
        'expr: event.event_type == "network.indicator"\n', encoding="utf-8")
    return root


# Numbat decodes enforce with Go's yaml.v3 into a bool, which accepts YAML 1.1's
# short forms, quoted or not; the pinned binary's own exit-2 hook denies on
# `enforce: y` and `enforce: "yes"` (TestAgainstThePinnedCli pins that). PyYAML
# reads `y` and every quoted form as a string, and the engine used to label
# those rules monitor-only, allowing the calls Numbat denies.
@pytest.mark.parametrize(("raw", "can_deny"), [
    ("true", True), ("True", True), ("yes", True), ("on", True), ("y", True), ("Y", True),
    ('"yes"', True), ("'y'", True), ('"ON"', True),
    ("false", False), ("no", False), ("off", False), ("n", False), ('"no"', False), ("'Off'", False), ("", False),
])
def test_enforce_is_read_the_way_numbat_reads_it(tmp_path, raw, can_deny):
    root = _flagged_rule(tmp_path, f"enforce: {raw}\n")
    assert numbat_gate.classify_rules([root]) == ({"acme.r"}, {"acme.r"} if can_deny else set())


@pytest.mark.parametrize("raw", ['"true"', "1", "maybe"])
def test_an_enforce_value_numbat_refuses_reads_as_able_to_deny(tmp_path, raw):
    # The pinned binary refuses these files ("cannot unmarshal !!str `true`
    # into bool"), so its run fails and the call is denied anyway. Reading
    # them as able to deny keeps that so if a later release accepts them.
    root = _flagged_rule(tmp_path, f"enforce: {raw}\n")
    assert numbat_gate.classify_rules([root]) == ({"acme.r"}, {"acme.r"})


@pytest.mark.parametrize("raw", ["n", "N", '"no"', "'off'", "false"])
def test_a_rule_disabled_the_way_numbat_reads_it_leaves_nothing_enabled(tmp_path, monkeypatch, raw):
    # `enabled: n` is a disabled rule to Numbat, and a string to PyYAML: read
    # as enabled, it passed the "no enabled rule" check, and the canary alone
    # then allowed every call.
    _flagged_rule(tmp_path, f"enabled: {raw}\nenforce: true\n")
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert fake.calls == []


@pytest.mark.parametrize("raw", ["y", '"yes"', "on", "~"])
def test_a_rule_enabled_the_way_numbat_reads_it_is_enabled(tmp_path, monkeypatch, raw):
    _flagged_rule(tmp_path, f"enabled: {raw}\nenforce: true\n")
    _fake(monkeypatch, matches=["acme.r"])
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_denied")


def test_an_enabled_value_numbat_refuses_does_not_count_as_enabled(tmp_path, monkeypatch):
    _flagged_rule(tmp_path, 'enabled: "maybe"\nenforce: true\n')
    _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")


@pytest.mark.parametrize("name", ["deny.YAML", "deny.Yml", ".yaml", "deny.yml"])
def test_rule_files_are_found_by_numbats_extension_rule(tmp_path, monkeypatch, name):
    # Numbat loads any-case .yaml/.yml names, a file named just `.yaml`
    # included. Path.suffix missed both, so the snapshot Numbat evaluates
    # lacked the rule and an enforce match in it never reached the decision.
    root = _flagged_rule(tmp_path, "enforce: true\n", name=name)
    assert numbat_gate.classify_rules([root]) == ({"acme.r"}, {"acme.r"})
    seen: list[set[str]] = []

    def _snapshot_names(argv):
        dirs = [Path(argv[i + 1]) for i, arg in enumerate(argv) if arg == "--rules-dir"]
        seen.append({path.name for d in dirs for path in d.rglob("*") if path.is_file()})

    _fake(monkeypatch, matches=["acme.r"], on_rules_test=_snapshot_names)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_denied")
    assert name in seen[0]


def test_non_rule_files_stay_out_of_the_snapshot(tmp_path):
    root = _flagged_rule(tmp_path, "enforce: true\n")
    (root / "notes.json").write_text('{"id": "acme.json"}', encoding="utf-8")
    (root / "old.yaml.bak").write_text('id: acme.bak\n', encoding="utf-8")
    assert numbat_gate.classify_rules([root]) == ({"acme.r"}, {"acme.r"})


def test_companion_tests_files_are_not_rules(tmp_path):
    root = _rules_dir(tmp_path, ("acme.deny", True))
    (root / "acme_deny_tests.yaml").write_text("rule_id: acme.deny\ncases: []\n", encoding="utf-8")
    assert numbat_gate.classify_rules([root]) == ({"acme.deny"}, {"acme.deny"})


# ---------------------------------------------------------------------------
# Every failure fails closed
# ---------------------------------------------------------------------------

def test_unclassifiable_match_denies(tmp_path, monkeypatch):
    """A rule Numbat loaded but this engine's walk did not see must not allow."""
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, matches=["acme.somewhere_else"])
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_failure")


@pytest.mark.parametrize("stdout", ["garbage\n", "acme.deny\n", "acme.deny\tsome-other-event\n", "\tabc\n"])
def test_unparseable_output_denies(tmp_path, monkeypatch, stdout):
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, stdout=stdout)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_failure")


def test_nonzero_exit_denies_with_the_first_stderr_line(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, returncode=1, stderr='\nrule "acme.deny": compile expr: ERROR\nmore\n')
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_failure")
    assert result["reason"] == 'numbat rules test exited 1: rule "acme.deny": compile expr: ERROR'


def test_timeout_denies(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, raises=subprocess.TimeoutExpired(cmd="numbat", timeout=5))
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_timeout")


def test_spawn_error_denies(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, raises=PermissionError("denied"))
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_error")


def test_missing_binary_denies_without_spawning(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path, binary=str(tmp_path / "no-numbat")), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_error")
    assert fake.calls == [] and fake.version_calls == []


@pytest.mark.parametrize("dirs", [[], None, "rules", [""], [3]])
def test_missing_or_malformed_rules_dirs_deny(tmp_path, monkeypatch, dirs):
    fake = _fake(monkeypatch)
    cfg = _cfg(tmp_path)
    cfg["policy"]["fallback"]["pre_action_hook"]["numbat"]["rules_dirs"] = dirs
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, cfg, timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert fake.calls == []


def test_nonexistent_rules_dir_denies(tmp_path, monkeypatch):
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path, dirs=[str(tmp_path / "nope")]), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert fake.calls == []


def test_any_unexpected_exception_denies(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))

    def _boom(*_a, **_k):
        raise RuntimeError("builder exploded")

    _fake(monkeypatch)  # a verified binary, so the failure is the builder's
    monkeypatch.setattr(numbat_gate, "build_gate_event", _boom)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_error")


# ---------------------------------------------------------------------------
# What the rules see, and what the CLI is asked
# ---------------------------------------------------------------------------

def test_cli_evaluates_a_snapshot_of_the_operator_rules_plus_the_canary(tmp_path, monkeypatch):
    live = _rules_dir(tmp_path, ("acme.deny", True))
    second = tmp_path / "more"
    (second / "nested").mkdir(parents=True)
    (second / "nested" / "w.yaml").write_text('id: acme.w\nversion: "1"\ntitle: t\nseverity: low\nexpr: "true"\n',
                                              encoding="utf-8")
    seen: dict[str, Any] = {}

    def _look(argv):
        dirs = [Path(argv[i + 1]) for i, arg in enumerate(argv) if arg == "--rules-dir"]
        seen["dirs"] = dirs
        seen["files"] = [sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) for d in dirs]
        seen["copy"] = (dirs[0] / "acme_deny.yaml").read_bytes()

    fake = _fake(monkeypatch, on_rules_test=_look)
    numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path, dirs=[str(live), str(second)]), timeout=7)
    argv = fake.calls[0]
    assert argv[1:4] == ["rules", "test", "--fixture"]
    assert "--no-builtin-rules" in argv
    assert fake.version_calls, "the pinned-release check runs on every decision"
    # Numbat reads byte copies taken for this call, never the live dirs, and
    # the engine's canary directory comes last.
    assert not any(d.is_relative_to(tmp_path) for d in seen["dirs"])
    assert seen["files"] == [["acme_deny.yaml"], ["nested/w.yaml"], ["cyclaw_gate_canary.yaml"]]
    assert seen["copy"] == (live / "acme_deny.yaml").read_bytes()
    # The per-call workdir (fixture, snapshot, canary) is gone once the verdict is in.
    assert not Path(argv[4]).exists()
    assert not seen["dirs"][0].exists()


def test_gate_event_is_a_schema_legal_egress_event(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    event = fake.fixture_events[0]
    assert event["event_type"] == "network.indicator"
    assert event["decision"] == "asked"
    assert event["tool_name"] == "external_llm_call"
    assert event["model"] == "grok-4.5"
    assert event["model_provider"] == "xai"
    assert event["url"] == "https://api.x.ai"
    assert event["tags"] == ["cyclaw", "pre_action_hook", "grok"]
    assert event["evidence"]["artifact_type"] == "pre_action_hook"
    assert json.loads(event["content_preview"]) == {"query_hash": _HASH}
    assert len(event["content_preview"]) <= CONTENT_PREVIEW_MAX_CHARS


def test_gate_event_honors_the_query_hash_opt_out(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    cfg = _cfg(tmp_path, logging={"audit_fields": {"include_query_hash": False}})
    numbat_gate.evaluate("claude", "claude-sonnet-5", _HASH, cfg, timeout=5)
    event = fake.fixture_events[0]
    assert "content_preview" not in event
    assert _HASH not in json.dumps(event)
    assert event["url"] == "https://api.anthropic.com"


def test_gate_event_url_carries_no_credentials(tmp_path, monkeypatch):
    """endpoint_trust pins only the hostname, so userinfo, a path segment or a
    key in the query string could ride a configured base_url; rules see the
    origin only."""
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    cfg = _cfg(tmp_path)
    cfg["models"]["grok"]["base_url"] = "https://ops:s3cr3t-tok@api.x.ai/p4th-tok/v1?api_key=k3y-val#frag"
    numbat_gate.evaluate("grok", "grok-4.5", _HASH, cfg, timeout=5)
    event = fake.fixture_events[0]
    assert event["url"] == "https://api.x.ai"
    assert "s3cr3t-tok" not in json.dumps(event)
    assert "p4th-tok" not in json.dumps(event)
    assert "k3y-val" not in json.dumps(event)


@pytest.mark.parametrize("logging_block", ["oops", None, {"audit_fields": "x"}])
def test_malformed_logging_block_does_not_break_the_gate(tmp_path, monkeypatch, logging_block):
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path, logging=logging_block), timeout=5)
    assert result["verdict"] == "allow"


# ---------------------------------------------------------------------------
# An allow needs evidence the call was evaluated (#1467 review)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["", "numbat 0.3.0 (schema 0.4.0)", "Python 3.12.3"])
def test_a_binary_that_is_not_the_pinned_numbat_denies(tmp_path, monkeypatch, version):
    """/bin/true, another release, or any other program. Exit 0 with nothing
    printed used to read as "no enforce rule matched", which allowed."""
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch, version=version)
    result = numbat_gate.evaluate("grok", "grok-5-preview", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert fake.calls == [], "an unverified binary is never asked to evaluate"


@pytest.mark.parametrize(("raised", "reason_code"), [
    (subprocess.TimeoutExpired(cmd="numbat", timeout=5), "hook_timeout"),
    (PermissionError("denied"), "hook_error"),
])
def test_a_failed_version_check_denies(tmp_path, monkeypatch, raised, reason_code):
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch, version_raises=raised)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", reason_code)
    assert fake.calls == []


def test_a_run_that_does_not_report_the_canary_denies(tmp_path, monkeypatch):
    """Exit 0 with no output is also what a CLI that skipped the event prints."""
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, canary=False)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_failure")
    assert "canary" in result["reason"]


def test_the_canary_is_not_reported_as_a_monitor_match(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True), ("acme.watch", False))
    _fake(monkeypatch, matches=["acme.watch"])
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert result["monitor_matches"] == ["acme.watch"]


def test_an_operator_rule_cannot_take_the_canary_id(tmp_path, monkeypatch):
    _rules_dir(tmp_path, (numbat_gate.CANARY_RULE_ID, False))
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert fake.calls == []


def _disabled_rule(root: Path, rule_id: str = "acme.off") -> None:
    root.mkdir(exist_ok=True)
    (root / f"{rule_id.replace('.', '_')}.yaml").write_text(
        f'id: {rule_id}\nversion: "1"\ntitle: t\nseverity: high\nenabled: false\nenforce: true\n'
        'expr: event.event_type == "network.indicator"\n', encoding="utf-8")


def test_a_rule_set_with_nothing_enabled_denies(tmp_path, monkeypatch):
    # The canary alone lets `rules test` run and report a match, so without this
    # check an all-disabled rule set read as "no enforce rule matched" and allowed.
    root = tmp_path / "rules"
    _disabled_rule(root)
    (root / "acme_off_tests.yaml").write_text("rule_id: acme.off\ntests: []\n", encoding="utf-8")
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert fake.calls == []


def test_an_empty_rules_dir_denies(tmp_path, monkeypatch):
    (tmp_path / "rules").mkdir()
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert fake.calls == []


def test_an_enabled_monitor_only_rule_set_still_allows(tmp_path, monkeypatch):
    # An enabled rule without enforce: true is still a rule to decide with; it
    # just cannot deny, which is what an observe-only trial needs.
    _rules_dir(tmp_path, ("acme.watch", False))
    _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("allow", "hook_allowed")


def test_only_rule_files_are_snapshotted(tmp_path, monkeypatch):
    root = _rules_dir(tmp_path, ("acme.deny", True))
    (root / "README.md").write_text("notes\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"\0" * 4096)
    seen: list[str] = []

    def _look(argv):
        snapshot = Path(argv[argv.index("--rules-dir") + 1])
        seen.extend(sorted(p.name for p in snapshot.rglob("*") if p.is_file()))

    _fake(monkeypatch, on_rules_test=_look)
    numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert seen == ["acme_deny.yaml"]


@pytest.mark.parametrize(("limit", "value"), [
    ("_MAX_RULE_FILES", 1), ("_MAX_RULE_BYTES", 10), ("_MAX_RULE_WALK_ENTRIES", 1),
])
def test_a_rules_dir_past_the_walk_limits_denies(tmp_path, monkeypatch, limit, value):
    _rules_dir(tmp_path, ("acme.deny", True), ("acme.watch", False))
    monkeypatch.setattr(numbat_gate, limit, value)
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert "too large" in result["reason"]
    assert fake.calls == []


@pytest.mark.parametrize(("limit", "value"), [("_MAX_RULE_FILES", 2), ("_MAX_RULE_WALK_ENTRIES", 2)])
def test_the_walk_limits_count_every_rules_dir_together(tmp_path, monkeypatch, limit, value):
    # Two directories of two rules each: under each cap one directory at a
    # time, past it together. Per-directory caps would scale with the list.
    first = _rules_dir(tmp_path, ("acme.deny", True), ("acme.watch", False))
    second = tmp_path / "more"
    second.mkdir()
    for name in ("acme_deny.yaml", "acme_watch.yaml"):
        (second / name.replace("acme", "other")).write_bytes((first / name).read_bytes().replace(b"acme.", b"other."))
    monkeypatch.setattr(numbat_gate, limit, value)
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path, dirs=[str(first), str(second)]), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    assert fake.calls == []


def test_reading_rules_past_the_deadline_denies(tmp_path, monkeypatch):
    # A slow mount or an over-broad tree must not hold the request past
    # timeout_sec: here the clock is already past the deadline while the rules
    # are read, and the gate denies without running the CLI.
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    # This checks the rules read's own deadline, so run the decision on this
    # thread rather than under evaluate()'s outer bound, which reads the clock too.
    monkeypatch.setattr(numbat_gate, "_within", lambda timeout, work: work())
    ticks = iter([0.0])
    monkeypatch.setattr(numbat_gate, "time", types.SimpleNamespace(monotonic=lambda: next(ticks, 1_000.0)))
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_timeout")
    # The read itself stopped, rather than finishing the walk and denying later
    # at the budget check before the first CLI call.
    assert "reading rules_dirs" in result["reason"]
    assert fake.calls == []


def _stall_reads_of(monkeypatch: pytest.MonkeyPatch, name: str) -> tuple[threading.Event, list[str]]:
    """Make reading the file ``name`` block until the returned event is set,
    as a read on a stalled network mount blocks in the kernel."""
    release = threading.Event()
    attempts: list[str] = []
    real_read_bytes = Path.read_bytes

    def _read_bytes(self):
        if self.name == name:
            attempts.append(self.name)
            release.wait(30)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)
    return release, attempts


def _join_rule_readers() -> None:
    for thread in threading.enumerate():
        if thread.name in ("numbat-rules-read", "numbat-gate"):
            thread.join(30)


def test_a_stalled_check_before_the_rules_read_still_denies_on_time(tmp_path, monkeypatch):
    # Checking that rules_dirs exists, finding the binary and exec'ing it can
    # all block on a stalled mount too; the whole decision is bounded, not
    # just the read.
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    release = threading.Event()
    real_is_dir = Path.is_dir

    def _is_dir(self):
        if self.name == "rules":
            release.wait(30)
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", _is_dir)
    started = time.monotonic()
    try:
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=0.2)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        _join_rule_readers()
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_timeout")
    assert elapsed < 10  # the stalled check alone would have held it for 30 s
    assert fake.calls == []


def test_a_stalled_readiness_check_reports_in_time(tmp_path, monkeypatch):
    release = threading.Event()

    def _stuck(cfg, timeout):
        release.wait(30)
        return True, None

    monkeypatch.setattr(numbat_gate, "_readiness", _stuck)
    monkeypatch.setattr(numbat_gate, "_READINESS_BUDGET_SEC", 0.2)
    started = time.monotonic()
    try:
        ready, problem = numbat_gate.readiness(_cfg(tmp_path), timeout=0.1)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        _join_rule_readers()
    assert ready is False and "did not finish" in problem
    assert elapsed < 10


# The SystemExit ending the worker thread is the scenario under test, and
# pytest reports any exception that ends a thread.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_decision_that_exits_its_worker_denies_and_frees_the_slot(tmp_path, monkeypatch):
    # The worker hands back only Exception; a SystemExit ends the thread with
    # no outcome, which must still deny rather than allow or hang.
    def _exits(*args, **kwargs):
        raise SystemExit(0)

    monkeypatch.setattr(numbat_gate, "_evaluate", _exits)
    started = time.monotonic()
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_timeout")
    assert time.monotonic() - started < 5
    slots = numbat_gate._GATE_WORKER_SLOTS
    taken = [slots.acquire(timeout=1) for _ in range(numbat_gate._MAX_GATE_WORKERS)]
    for ok in taken:
        if ok:
            slots.release()
    assert all(taken)


def test_a_rules_read_stuck_past_the_deadline_still_denies_on_time(tmp_path, monkeypatch):
    # No deadline check between filesystem calls helps when one call never
    # returns: the read runs on a worker thread that the call abandons.
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    release, attempts = _stall_reads_of(monkeypatch, "acme_deny.yaml")
    started = time.monotonic()
    try:
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=0.5)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        _join_rule_readers()
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_timeout")
    assert attempts == ["acme_deny.yaml"]
    assert elapsed < 10  # the stuck read alone would have held it for 30 s
    assert fake.calls == []


def test_stuck_rule_readers_are_capped(tmp_path, monkeypatch):
    # While every reader slot is held by a stuck read, a call waits for a slot
    # until its deadline and denies, instead of stacking another stuck thread.
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch)
    monkeypatch.setattr(numbat_gate, "_RULE_READERS", threading.BoundedSemaphore(1))
    release, attempts = _stall_reads_of(monkeypatch, "acme_deny.yaml")
    try:
        first = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=0.3)
        second = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=0.3)
    finally:
        release.set()
        _join_rule_readers()
    assert first["reason_code"] == second["reason_code"] == "hook_timeout"
    assert attempts == ["acme_deny.yaml"]  # the second call never started a read


def _unlistable(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make listing any directory called ``name`` fail, as it would for a
    directory the server's user cannot read (the suite may run as root)."""
    real_scandir = os.scandir

    def _scandir(path=".", *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and Path(path).name == name:
            raise PermissionError(13, "Permission denied", str(path))
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", _scandir)


def test_a_wide_directory_stops_at_the_entry_cap_while_it_is_listed(tmp_path, monkeypatch):
    # os.walk lists a whole directory before yielding it, so the cap could
    # only fire after one very wide directory had been read in full. The
    # walk now counts entries as they are listed and stops at the cap.
    root = _rules_dir(tmp_path, ("acme.deny", True))
    wide = root / "wide"
    wide.mkdir()
    for index in range(50):
        (wide / f"f{index}.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(numbat_gate, "_MAX_RULE_WALK_ENTRIES", 10)
    real_scandir = os.scandir
    listed: list[str] = []

    class _Counting:
        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

        def __iter__(self):
            for entry in self._inner:
                listed.append(entry.name)
                yield entry

    monkeypatch.setattr(os, "scandir", lambda path=".": _Counting(real_scandir(path)))
    with pytest.raises(numbat_gate._RulesTooLarge):
        numbat_gate._rule_files(root, numbat_gate._WalkBudget())
    assert len(listed) == 11  # stopped at the cap, not after all 52 entries


def test_the_walk_finds_nested_rules_in_sorted_order(tmp_path):
    root = tmp_path / "rules"
    for rel in ("b/z.yaml", "b/a.yml", "a.yaml", "c/d/e.yaml", "notes.txt"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    found = numbat_gate._rule_files(root, numbat_gate._WalkBudget())
    assert [p.relative_to(root).as_posix() for p in found] == ["a.yaml", "b/a.yml", "b/z.yaml", "c/d/e.yaml"]


def test_an_unlistable_rules_subdirectory_denies(tmp_path, monkeypatch):
    # Its rules would otherwise drop out of the snapshot unseen, so an enforce
    # rule kept there could never deny.
    root = _rules_dir(tmp_path, ("acme.watch", False))
    (root / "locked").mkdir()
    (root / "locked" / "acme_deny.yaml").write_text(
        'id: acme.deny\nversion: "1"\ntitle: t\nseverity: high\nenforce: true\n'
        'expr: event.event_type == "network.indicator"\n', encoding="utf-8")
    _unlistable(monkeypatch, "locked")
    fake = _fake(monkeypatch)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_error")
    assert fake.calls == []


def _ready_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CLI that reports the pinned version and passes `rules check`."""
    def _run(argv, **_kwargs):
        out = f"{numbat_gate.PINNED_VERSION_LINE}\n" if list(argv[1:]) == ["version"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
    monkeypatch.setattr(numbat_gate, "_run_cli", _run)


def test_readiness_flags_a_rule_set_with_nothing_enabled(tmp_path, monkeypatch):
    _disabled_rule(tmp_path / "rules")
    _ready_cli(monkeypatch)
    ready, problem = numbat_gate.readiness(_cfg(tmp_path))
    assert ready is False
    assert "no enabled rule" in problem and str(tmp_path) not in problem


@pytest.mark.parametrize(("limit", "value"), [
    ("_MAX_RULE_FILES", 1), ("_MAX_RULE_BYTES", 10), ("_MAX_RULE_WALK_ENTRIES", 1),
])
def test_readiness_flags_a_rules_dir_past_the_walk_limits(tmp_path, monkeypatch, limit, value):
    _rules_dir(tmp_path, ("acme.deny", True), ("acme.watch", False))
    monkeypatch.setattr(numbat_gate, limit, value)
    _ready_cli(monkeypatch)
    ready, problem = numbat_gate.readiness(_cfg(tmp_path))
    assert ready is False
    assert "too large" in problem and str(tmp_path) not in problem


def test_readiness_flags_an_unreadable_rules_file(tmp_path, monkeypatch):
    # The decision path denies every call on it, so /health must not say ready.
    _rules_dir(tmp_path, ("acme.deny", True))
    real_read_bytes = Path.read_bytes

    def _read_bytes(self):
        if self.name == "acme_deny.yaml":
            raise PermissionError("denied")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)
    _ready_cli(monkeypatch)
    ready, problem = numbat_gate.readiness(_cfg(tmp_path))
    assert ready is False
    assert "could not be read" in problem and str(tmp_path) not in problem


def test_readiness_flags_an_unlistable_rules_subdirectory(tmp_path, monkeypatch):
    root = _rules_dir(tmp_path, ("acme.deny", True))
    (root / "locked").mkdir()
    _unlistable(monkeypatch, "locked")
    _ready_cli(monkeypatch)
    ready, problem = numbat_gate.readiness(_cfg(tmp_path))
    assert ready is False
    assert "could not be read" in problem and str(tmp_path) not in problem


@pytest.mark.skipif(shutil.which("true") is None, reason="needs a `true` executable")
def test_bin_true_as_the_binary_denies(tmp_path):
    """Codex's reproduction, with a real process: no fakes, no numbat."""
    _rules_dir(tmp_path, ("acme.deny", True))
    result = numbat_gate.evaluate("grok", "grok-5-preview", _HASH, _cfg(tmp_path, binary=shutil.which("true")), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")


# ---------------------------------------------------------------------------
# Classification and evaluation read the same bytes (#1467 review)
# ---------------------------------------------------------------------------

def test_a_rule_edited_mid_request_cannot_reach_the_evaluated_rules(tmp_path, monkeypatch):
    live = _rules_dir(tmp_path, ("acme.watch", False))
    evaluated: list[bytes] = []

    def _promote_then_look(argv):
        (live / "acme_watch.yaml").write_text(
            'id: acme.watch\nversion: "1"\ntitle: t\nseverity: high\nenforce: true\n'
            'expr: event.event_type == "network.indicator"\n', encoding="utf-8")
        snapshot = Path(argv[argv.index("--rules-dir") + 1])
        evaluated.append((snapshot / "acme_watch.yaml").read_bytes())

    _fake(monkeypatch, matches=["acme.watch"], on_rules_test=_promote_then_look)
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    # Numbat evaluated the rule as it was classified (monitor), so allowing
    # with a monitor match is one consistent rule state, not a mix of two.
    assert b"enforce" not in evaluated[0]
    assert (result["verdict"], result["monitor_matches"]) == ("allow", ["acme.watch"])


def test_an_unreadable_rules_file_denies(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    real_read_bytes = Path.read_bytes

    def _read_bytes(self):
        if self.name == "acme_deny.yaml":
            raise PermissionError("denied")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)
    fake = _fake(monkeypatch, matches=["acme.deny"])
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path), timeout=5)
    # A rule the gate cannot see must deny, not drop out of both sides.
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_error")
    assert fake.calls == []


@pytest.mark.skipif(os.name == "nt", reason="directory symlinks need privileges on Windows")
def test_a_symlinked_rules_dir_is_read_through_its_target(tmp_path, monkeypatch):
    """Swapping a symlink is the atomic way to change several rules at once."""
    target = _rules_dir(tmp_path, ("acme.deny", True))
    link = tmp_path / "current"
    link.symlink_to(target, target_is_directory=True)
    _fake(monkeypatch, matches=["acme.deny"])
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path, dirs=[str(link)]), timeout=5)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_denied")


def test_relative_paths_anchor_at_the_repo_root(tmp_path):
    cfg = _cfg(tmp_path, dirs=["tests/fixtures/numbat/gate-rules"], binary="tests/numbat_shaped_events.py")
    assert numbat_gate.rules_dirs(cfg) == [GATE_RULES]
    # A path that exists but is not executable does not count as the binary.
    if os.name != "nt":
        assert numbat_gate.resolve_binary(cfg) is None


# ---------------------------------------------------------------------------
# Readiness (/health)
# ---------------------------------------------------------------------------

def test_readiness_reports_fixed_phrases_without_paths(tmp_path):
    ready, problem = numbat_gate.readiness(_cfg(tmp_path, dirs=[str(tmp_path / "secret-layout" / "rules")]))
    assert ready is False
    assert "secret-layout" not in problem and str(tmp_path) not in problem


def test_readiness_is_cached(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(numbat_gate, "_readiness", lambda cfg, timeout: calls.append(1) or (True, None))
    cfg = _cfg(tmp_path)
    assert numbat_gate.readiness(cfg) == (True, None)
    assert numbat_gate.readiness(cfg) == (True, None)
    assert len(calls) == 1


def _slow_readiness(monkeypatch: pytest.MonkeyPatch, verdict: tuple[bool, str | None]):
    """A _readiness that blocks until released, counting its runs."""
    started, release = threading.Event(), threading.Event()
    runs: list[int] = []

    def _check(cfg, timeout):
        runs.append(1)
        started.set()
        release.wait(30)
        return verdict

    monkeypatch.setattr(numbat_gate, "_readiness", _check)
    return started, release, runs


def test_concurrent_readiness_checks_share_one_run(tmp_path, monkeypatch):
    # /health is unauthenticated and unthrottled; a burst while the cache is
    # cold must not spawn the binary once per caller.
    started, release, runs = _slow_readiness(monkeypatch, (True, None))
    cfg = _cfg(tmp_path)
    first: list[tuple[bool, str | None]] = []
    worker = threading.Thread(target=lambda: first.append(numbat_gate.readiness(cfg)))
    worker.start()
    try:
        assert started.wait(30)
        ready, problem = numbat_gate.readiness(cfg)
    finally:
        release.set()
        worker.join(30)
    assert (ready, "still running" in problem) == (False, True)
    assert first == [(True, None)]
    assert numbat_gate.readiness(cfg) == (True, None)
    assert len(runs) == 1


def test_a_refreshing_readiness_check_serves_the_previous_result(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    key = numbat_gate._readiness_key(cfg, 5.0)
    numbat_gate._READINESS_CACHE[key] = (time.monotonic() - 3600, (True, None))  # expired
    started, release, runs = _slow_readiness(monkeypatch, (False, "fresh answer"))
    worker = threading.Thread(target=lambda: numbat_gate.readiness(cfg))
    worker.start()
    try:
        assert started.wait(30)
        assert numbat_gate.readiness(cfg) == (True, None)
    finally:
        release.set()
        worker.join(30)
    assert numbat_gate.readiness(cfg) == (False, "fresh answer")
    assert len(runs) == 1


def test_readiness_ends_with_a_probe_decision(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    assert numbat_gate.readiness(_cfg(tmp_path)) == (True, None)
    assert [event["model"] for event in fake.fixture_events] == ["cyclaw-health-probe"]


def test_readiness_flags_a_setup_whose_decisions_exceed_timeout_sec(tmp_path, monkeypatch):
    # Each check has its own bound; a call gets only timeout_sec. On a slow
    # disk, or with a short timeout_sec, every call can time out while each
    # check passes, so /health must not report ready.
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, raises=subprocess.TimeoutExpired(["numbat"], 1))
    ready, problem = numbat_gate.readiness(_cfg(tmp_path), timeout=1)
    assert ready is False
    assert "timeout_sec (1 s)" in problem and str(tmp_path) not in problem


def test_readiness_flags_a_rule_with_the_reserved_canary_id(tmp_path, monkeypatch):
    # Every call denies on it (hook_misconfigured), though `rules check`
    # accepts it as an ordinary rule.
    _rules_dir(tmp_path, (numbat_gate.CANARY_RULE_ID, True))
    _fake(monkeypatch)
    ready, problem = numbat_gate.readiness(_cfg(tmp_path))
    assert ready is False
    assert "reserved id" in problem and str(tmp_path) not in problem


def test_readiness_flags_a_probe_decision_that_fails(tmp_path, monkeypatch):
    _rules_dir(tmp_path, ("acme.deny", True))
    _fake(monkeypatch, canary=False)
    ready, problem = numbat_gate.readiness(_cfg(tmp_path))
    assert ready is False and "hook_failure" in problem


def test_readiness_resolves_the_binary_inside_its_budget(tmp_path, monkeypatch):
    # Finding a bare binary name walks PATH, which can hang on a stalled
    # mount; that too must stay inside the bounded check.
    _rules_dir(tmp_path, ("acme.deny", True))
    release = threading.Event()

    def _which(name):
        release.wait(30)
        return None

    monkeypatch.setattr(numbat_gate.shutil, "which", _which)
    monkeypatch.setattr(numbat_gate, "_READINESS_BUDGET_SEC", 0.1)
    started = time.monotonic()
    try:
        ready, problem = numbat_gate.readiness(_cfg(tmp_path, binary="numbat"), timeout=0.1)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        _join_rule_readers()
    assert ready is False and "did not finish" in problem
    assert elapsed < 10


def test_readiness_does_not_echo_an_unverified_binary(tmp_path, monkeypatch):
    # Until it prints the pinned line the binary is some program, and what it
    # printed must not reach unauthenticated /health.
    _rules_dir(tmp_path, ("acme.deny", True))

    def _run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="token-6f1c secret /home/op/.ssh/id\n", stderr="")

    monkeypatch.setattr(numbat_gate, "_run_cli", _run)
    ready, problem = numbat_gate.readiness(_cfg(tmp_path))
    assert ready is False
    assert "not the pinned" in problem
    assert "token-6f1c" not in problem and "/home/op" not in problem


# ---------------------------------------------------------------------------
# Running the binary with bounded output
# ---------------------------------------------------------------------------

def test_run_cli_returns_what_the_program_printed():
    code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    proc = numbat_gate._run_cli([sys.executable, "-c", code], timeout=60)
    assert proc.returncode == 3
    assert proc.stdout.splitlines() == ["out"]
    assert proc.stderr.splitlines() == ["err"]


def test_run_cli_kills_a_program_that_floods_its_output():
    # The configured binary is unverified until it prints the pinned version;
    # one that prints without end must be cut off, not buffered.
    code = "import sys\nwhile True:\n    sys.stdout.write('y' * 65536)\n"
    started = time.monotonic()
    with pytest.raises(numbat_gate._CliOutputTooLarge):
        numbat_gate._run_cli([sys.executable, "-c", code], timeout=60)
    assert time.monotonic() - started < 30


def test_run_cli_times_out():
    with pytest.raises(subprocess.TimeoutExpired):
        numbat_gate._run_cli([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.5)


def _cli_readers_alive() -> int:
    return sum(1 for thread in threading.enumerate() if thread.name == "numbat-cli-output")


@pytest.mark.skipif(os.name == "nt" or shutil.which("sh") is None, reason="needs POSIX sh and process groups")
def test_run_cli_stays_in_budget_when_a_child_keeps_the_pipes_open():
    # The binary exits at once but leaves a child holding stdout. Waiting for
    # the output to end would outlast the budget, and the readers would stay
    # until the child exits; instead its group is killed at the deadline.
    before = _cli_readers_alive()
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        numbat_gate._run_cli([shutil.which("sh"), "-c", "sleep 60 & echo started"], timeout=0.5)
    assert time.monotonic() - started < 2.5
    for _ in range(100):  # the killed child closes the pipes, so the readers end
        if _cli_readers_alive() <= before:
            break
        time.sleep(0.05)
    assert _cli_readers_alive() <= before


def test_run_cli_waits_for_a_reader_slot_only_until_its_deadline(monkeypatch):
    # With every reader slot held by readers left over from earlier runs, a
    # call times out instead of starting more.
    monkeypatch.setattr(numbat_gate, "_CLI_READER_SLOTS", threading.BoundedSemaphore(1))
    with pytest.raises(subprocess.TimeoutExpired):
        numbat_gate._run_cli([sys.executable, "-c", "print('never started')"], timeout=0.2)


@pytest.mark.skipif(os.name == "nt" or shutil.which("yes") is None, reason="needs a POSIX `yes`")
def test_a_binary_that_floods_its_output_denies(tmp_path):
    """`yes version` prints forever: a misconfigured binary denies, it does not fill memory."""
    _rules_dir(tmp_path, ("acme.deny", True))
    result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, _cfg(tmp_path, binary=shutil.which("yes")), timeout=10)
    assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")
    ready, problem = numbat_gate.readiness(_cfg(tmp_path, binary=shutil.which("yes")))
    assert ready is False and "version" not in problem


def test_pinned_version_matches_the_ci_lane():
    workflow = (_REPO / ".github" / "workflows" / "numbat-rules.yml").read_text(encoding="utf-8")
    assert re.search(r'grep -Fx "' + re.escape(numbat_gate.PINNED_VERSION_LINE) + '"', workflow)


# ---------------------------------------------------------------------------
# The pinned binary
# ---------------------------------------------------------------------------

def _missing(what: str) -> NoReturn:
    if os.environ.get("CYCLAW_REQUIRE_NUMBAT") == "1":
        pytest.fail(f"{what} is required in this lane (CYCLAW_REQUIRE_NUMBAT=1)")
    pytest.skip(f"{what} not available")


@pytest.fixture
def numbat_bin() -> str:
    exe = os.environ.get("NUMBAT") or shutil.which("numbat")
    if not exe:
        _missing("numbat CLI")
    return str(exe)


class TestAgainstThePinnedCli:
    def _cfg(self, tmp_path: Path, numbat_bin: str, dirs: list[str] | None = None) -> dict:
        return _cfg(tmp_path, binary=numbat_bin, dirs=dirs or [str(GATE_RULES)])

    def test_the_binary_is_the_pinned_one(self, numbat_bin):
        out = subprocess.run([numbat_bin, "version"], capture_output=True, text=True, check=False, timeout=30)
        assert out.stdout.strip() == numbat_gate.PINNED_VERSION_LINE

    def test_example_rules_pass_their_companion_tests(self, numbat_bin):
        out = subprocess.run(
            [numbat_bin, "rules", "check", "--no-builtin-rules", "--rules-dir", str(GATE_RULES)],
            capture_output=True, text=True, check=False, timeout=30,
        )
        assert out.returncode == 0, out.stdout + out.stderr

    @pytest.mark.parametrize(("provider", "model"), [("grok", "grok-4.5"), ("claude", "claude-sonnet-5")])
    def test_vetted_models_are_allowed_and_watched(self, tmp_path, numbat_bin, provider, model):
        result = numbat_gate.evaluate(provider, model, _HASH, self._cfg(tmp_path, numbat_bin), timeout=10)
        assert result["verdict"] == "allow", result
        assert result["monitor_matches"] == ["cyclaw.gate.watch_escalations"]

    def test_unvetted_model_is_denied(self, tmp_path, numbat_bin):
        result = numbat_gate.evaluate("grok", "grok-5-preview", _HASH, self._cfg(tmp_path, numbat_bin), timeout=10)
        assert (result["verdict"], result["reason_code"]) == ("deny", "hook_denied")
        assert "cyclaw.gate.pinned_models" in result["reason"]

    def test_a_broken_rule_denies(self, tmp_path, numbat_bin):
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "bad.yaml").write_text(
            'id: acme.bad\nversion: "1"\ntitle: t\nseverity: high\nenforce: true\nexpr: event.nope ==\n',
            encoding="utf-8")
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, self._cfg(tmp_path, numbat_bin, [str(broken)]), timeout=10)
        assert (result["verdict"], result["reason_code"]) == ("deny", "hook_failure")

    def test_a_rule_set_with_nothing_enabled_denies(self, tmp_path, numbat_bin):
        # Before this check, the pinned CLI plus the canary allowed every call
        # here: the canary matched, and no enforce rule was enabled to match.
        disabled = tmp_path / "disabled"
        _disabled_rule(disabled)
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH,
                                      self._cfg(tmp_path, numbat_bin, [str(disabled)]), timeout=10)
        assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured")

    @staticmethod
    def _rule(root: Path, name: str, rule_id: str, flags: str = "") -> None:
        root.mkdir(exist_ok=True)
        (root / name).write_text(
            f'id: {rule_id}\nversion: "1"\ntitle: t\nseverity: high\n{flags}expr: event.tool_name != ""\n',
            encoding="utf-8")

    @pytest.mark.parametrize("raw", ["y", '"yes"', "'on'"])
    def test_an_enforce_rule_numbat_enforces_denies(self, tmp_path, numbat_bin, raw):
        """Numbat's own exit-2 hook denies on these spellings of enforce. The
        engine read them with PyYAML as strings, labeled the rule
        monitor-only, and allowed the call (the #1467 review)."""
        rules = tmp_path / "rules"
        self._rule(rules, "r.yaml", "acme.block", f"enforce: {raw}\n")
        payload = json.dumps({"session_id": "s", "transcript_path": str(tmp_path / "t.jsonl"),
                              "cwd": str(tmp_path), "hook_event_name": "PreToolUse", "tool_name": "read_file",
                              "tool_input": {"absolute_path": str(tmp_path / "a.txt")}})
        own = subprocess.run(
            [numbat_bin, "hook", "PreToolUse", "--agent", "qwen", "--enforce", "--no-builtin-rules",
             "--rules-dir", str(rules), "--output", "file", "--output-file", str(tmp_path / "findings.ndjson")],
            input=payload, capture_output=True, text=True, check=False, timeout=30)
        assert own.returncode == 2, own.stdout + own.stderr
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH,
                                      self._cfg(tmp_path, numbat_bin, [str(rules)]), timeout=10)
        assert (result["verdict"], result["reason_code"]) == ("deny", "hook_denied"), result

    def test_a_rule_numbat_disables_leaves_nothing_enabled(self, tmp_path, numbat_bin):
        """`enabled: n` is a disabled rule to Numbat. Read as enabled, it passed
        the engine's "no enabled rule" check and the canary alone allowed
        every call (the #1467 review)."""
        rules = tmp_path / "rules"
        self._rule(rules, "r.yaml", "acme.block", "enabled: n\nenforce: true\n")
        check = subprocess.run([numbat_bin, "rules", "check", "--no-builtin-rules", "--rules-dir", str(rules)],
                               capture_output=True, text=True, check=False, timeout=30)
        assert check.returncode != 0 and "disabled" in check.stdout + check.stderr
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH,
                                      self._cfg(tmp_path, numbat_bin, [str(rules)]), timeout=10)
        assert (result["verdict"], result["reason_code"]) == ("deny", "hook_misconfigured"), result

    @pytest.mark.parametrize("name", ["deny.YAML", ".yaml"])
    def test_an_enforce_rule_in_any_file_numbat_loads_denies(self, tmp_path, numbat_bin, name):
        """Numbat loads `deny.YAML` and a file named just `.yaml`. The snapshot
        it evaluates left them out, so their enforce match never reached the
        decision and a monitor rule beside it made the call an allow."""
        rules = tmp_path / "rules"
        self._rule(rules, name, "acme.block", "enforce: true\n")
        self._rule(rules, "watch.yaml", "acme.watch")
        listed = subprocess.run([numbat_bin, "rules", "list", "--no-builtin-rules", "--rules-dir", str(rules)],
                                capture_output=True, text=True, check=False, timeout=30)
        assert "acme.block" in listed.stdout.split(), listed.stdout + listed.stderr
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH,
                                      self._cfg(tmp_path, numbat_bin, [str(rules)]), timeout=10)
        assert (result["verdict"], result["reason_code"]) == ("deny", "hook_denied"), result
        assert "acme.block" in result["reason"]

    def test_duplicate_rule_ids_deny(self, tmp_path, numbat_bin):
        copy = tmp_path / "copy"
        shutil.copytree(GATE_RULES, copy)
        dirs = [str(GATE_RULES), str(copy)]
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, self._cfg(tmp_path, numbat_bin, dirs), timeout=10)
        assert (result["verdict"], result["reason_code"]) == ("deny", "hook_failure")

    def test_a_rule_swap_mid_request_cannot_mix_two_rule_sets(self, tmp_path, numbat_bin, monkeypatch):
        """Retire enforce rule Q and promote R in one edit: before and after
        both deny. Reading the files twice classified from before, evaluated
        after, saw only R -- classified monitor -- and allowed."""
        rules = tmp_path / "rules"
        rules.mkdir()
        match_all = 'expr: |-\n  event.event_type == "network.indicator" &&\n  "pre_action_hook" in event.tags\n'
        head = 'version: "1"\ntitle: t\nseverity: high\n'
        (rules / "q.yaml").write_text(f"id: acme.q\n{head}enforce: true\n{match_all}", encoding="utf-8")
        (rules / "r.yaml").write_text(f"id: acme.r\n{head}{match_all}", encoding="utf-8")
        real_run = numbat_gate._run_cli

        def _edit_then_run(argv, **kwargs):
            if list(argv[1:3]) == ["rules", "test"]:
                (rules / "q.yaml").write_text(f'id: acme.q\n{head}enforce: true\nexpr: "false"\n', encoding="utf-8")
                (rules / "r.yaml").write_text(f"id: acme.r\n{head}enforce: true\n{match_all}", encoding="utf-8")
            return real_run(argv, **kwargs)

        monkeypatch.setattr(numbat_gate, "_run_cli", _edit_then_run)
        result = numbat_gate.evaluate("grok", "grok-4.5", _HASH, self._cfg(tmp_path, numbat_bin, [str(rules)]),
                                      timeout=30)
        assert (result["verdict"], result["reason_code"]) == ("deny", "hook_denied"), result
        assert "acme.q" in result["reason"]

    def test_the_canary_rule_loads_in_the_pinned_cli(self, tmp_path, numbat_bin):
        canary = tmp_path / "canary"
        canary.mkdir()
        (canary / "c.yaml").write_text(numbat_gate._CANARY_RULE, encoding="utf-8")
        out = subprocess.run([numbat_bin, "rules", "list", "--no-builtin-rules", "--rules-dir", str(canary)],
                             capture_output=True, text=True, check=False, timeout=30)
        assert out.returncode == 0, out.stdout + out.stderr
        assert numbat_gate.CANARY_RULE_ID in out.stdout

    def test_readiness_passes_with_the_example_rules(self, tmp_path, numbat_bin):
        assert numbat_gate.readiness(self._cfg(tmp_path, numbat_bin)) == (True, None)

    def test_readiness_flags_a_rule_set_that_cannot_deny(self, tmp_path, numbat_bin):
        monitor_only = tmp_path / "monitor-only"
        monitor_only.mkdir()
        shutil.copy(GATE_RULES / "watch_escalations.yaml", monitor_only)
        ready, problem = numbat_gate.readiness(self._cfg(tmp_path, numbat_bin, [str(monitor_only)]))
        assert ready is False
        assert "enforce" in problem

    def test_numbat_hook_cannot_gate_cyclaw_calls(self, tmp_path, numbat_bin):
        """Why config.yaml says never to set ``command`` to ``numbat hook ...``.

        CyClaw's command engine reads exit 0 as allow and exit 2 as deny.
        Against the pinned CLI, with CyClaw's payload on stdin:

        * the argv config.yaml used to suggest (``--agent cyclaw``) exits 0;
        * a Claude-style host denies as JSON on stdout with exit 0, which
          CyClaw reads as allow;
        * an exit-2 host (qwen) can deny, but a rule keyed on the provider
          CyClaw sends never fires -- the adapter drops it -- so the only
          policy it can express is "deny everything";
        * a mistyped event name exits 0.

        If a future Numbat changes any of these, this fails and the config
        comment and utils/numbat_gate.py's docstring are stale.
        """
        def rule_dir(name: str, expr: str) -> list[str]:
            root = tmp_path / name
            root.mkdir()
            (root / "r.yaml").write_text(
                f'id: acme.{name.replace("-", "_")}\nversion: "1"\ntitle: t\nseverity: high\n'
                f"enforce: true\nexpr: {expr}\n", encoding="utf-8")
            return ["--no-builtin-rules", "--rules-dir", str(root)]

        deny_all = rule_dir("deny-all", 'event.event_type != ""')
        deny_xai = rule_dir("deny-xai", 'event.model_provider == "xai"')
        sink = ["--output", "file", "--output-file", str(tmp_path / "findings.ndjson")]
        payload = json.dumps({"action": "external_llm_call", "provider": "grok",
                              "model": "grok-4.5", "query_hash": _HASH})

        def hook(*argv: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run([numbat_bin, "hook", *argv], input=payload, capture_output=True,
                                  text=True, check=False, timeout=30)

        old_suggestion = hook("pre-tool", "--agent", "cyclaw")
        assert old_suggestion.returncode == 0, old_suggestion.stderr

        claude = hook("PreToolUse", "--agent", "claude", "--enforce", *sink, *deny_all)
        assert claude.returncode == 0
        assert '"permissionDecision":"deny"' in claude.stdout.replace(" ", "")

        qwen_all = hook("PreToolUse", "--agent", "qwen", "--enforce", *sink, *deny_all)
        assert qwen_all.returncode == 2

        qwen_provider = hook("PreToolUse", "--agent", "qwen", "--enforce", *sink, *deny_xai)
        assert qwen_provider.returncode == 0

        typo = hook("pre_tool_use", "--agent", "qwen", "--enforce", *sink, *deny_all)
        assert typo.returncode == 0
