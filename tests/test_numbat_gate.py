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
    default). A ``rules test`` call reports the engine's canary rule -- the
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
        self.fixture_events: list[dict] = []

    def __call__(self, argv, **kwargs):
        if list(argv[1:]) == ["version"]:
            self.version_calls.append(list(argv))
            if self.version_raises is not None:
                raise self.version_raises
            return subprocess.CompletedProcess(argv, 0, stdout=f"{self.version}\n", stderr="")
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
    monkeypatch.setattr(numbat_gate.subprocess, "run", fake)
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


@pytest.mark.parametrize("enforce_value", ["true", 1, "yes"])
def test_only_a_yaml_boolean_enforce_can_deny(tmp_path, enforce_value):
    root = _rules_dir(tmp_path)
    (root / "r.yaml").write_text(
        f'id: acme.r\nversion: "1"\ntitle: t\nseverity: high\nenforce: {json.dumps(enforce_value)}\n'
        'expr: event.event_type == "network.indicator"\n', encoding="utf-8")
    assert numbat_gate.classify_rules([root]) == ({"acme.r"}, set())


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
    assert event["url"] == "https://api.x.ai/v1"
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
    assert event["url"] == "https://api.anthropic.com/v1"


def test_gate_event_url_carries_no_credentials(tmp_path, monkeypatch):
    """endpoint_trust pins only the hostname, so userinfo or a key in the query
    string could ride a configured base_url; rules see host and path only."""
    _rules_dir(tmp_path, ("acme.deny", True))
    fake = _fake(monkeypatch)
    cfg = _cfg(tmp_path)
    cfg["models"]["grok"]["base_url"] = "https://ops:s3cr3t-tok@api.x.ai/v1?api_key=k3y-val#frag"
    numbat_gate.evaluate("grok", "grok-4.5", _HASH, cfg, timeout=5)
    event = fake.fixture_events[0]
    assert event["url"] == "https://api.x.ai/v1"
    assert "s3cr3t-tok" not in json.dumps(event)
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
    monkeypatch.setattr(numbat_gate, "_readiness", lambda binary, dirs: calls.append(1) or (True, None))
    cfg = _cfg(tmp_path)
    assert numbat_gate.readiness(cfg) == (True, None)
    assert numbat_gate.readiness(cfg) == (True, None)
    assert len(calls) == 1


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
        real_run = subprocess.run

        def _edit_then_run(argv, **kwargs):
            if list(argv[1:3]) == ["rules", "test"]:
                (rules / "q.yaml").write_text(f'id: acme.q\n{head}enforce: true\nexpr: "false"\n', encoding="utf-8")
                (rules / "r.yaml").write_text(f"id: acme.r\n{head}enforce: true\n{match_all}", encoding="utf-8")
            return real_run(argv, **kwargs)

        monkeypatch.setattr(numbat_gate.subprocess, "run", _edit_then_run)
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
