"""CyClaw-shaped Numbat events against the pinned CLI and its published schema.

Issue #1458 Phase 4. ``tests/numbat_shaped_events.py`` drives every production
producer of the Numbat stream (mainline audit projection, pre-action hook
verdicts, CEL monitor, ops/fsconnect/sqlconnect action plane) and returns what
they wrote. This module holds that output to three contracts:

1. the committed golden file, so emitter shape drift fails the unit lane on
   every OS without any Numbat binary;
2. the published schema-0.3.0 event contract
   (``docs/schema/v0.3.0/event-record.schema.json`` inside the pinned
   release), which covers what ``rules test`` accepts without checking:
   unknown top-level keys, missing required fields, the endpoint object;
3. the pinned CLI itself: CyClaw's own traffic must load and score zero
   findings against the shipped catalog, and CyClaw-shaped exfil/secret-read
   events must still fire the rules that catch them.

Before this existed, the CLI job only scored hand-written action-plane
events. The live stream failed it twice over: every mainline rag_query
carried a ~700-character content_preview ("content_preview exceeds 200
runes"), and every ops event with a redacted ``--reason=`` held a bare
``<redacted>`` the CLI's shell parser rejects as "unsupported or malformed
syntax".

(2) and (3) need the schema directory (``NUMBAT_SCHEMA_DIR``) and the binary
(``NUMBAT`` or ``numbat`` on PATH), which ``.github/workflows/numbat-rules.yml``
provides; there ``CYCLAW_REQUIRE_NUMBAT=1`` turns a missing prerequisite into
a failure instead of a skip. Regenerate the golden files after an intended
emitter change with::

    python -m tests.numbat_shaped_events --frozen --out tests/fixtures/numbat/cyclaw-shaped-events.ndjson
    python -m tests.numbat_shaped_events --frozen --known-bad --out tests/fixtures/numbat/cyclaw-shaped-known-bad.ndjson
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest

from tests.numbat_shaped_events import generate, write_ndjson
from utils.numbat_emitter import (
    _EVENT_TYPE_FORBIDDEN_FIELDS,
    _KNOWN_FIELDS,
    CONTENT_PREVIEW_MAX_CHARS,
    SCHEMA_VERSION,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "numbat"
GOLDEN_CLEAN = _FIXTURES / "cyclaw-shaped-events.ndjson"
GOLDEN_KNOWN_BAD = _FIXTURES / "cyclaw-shaped-known-bad.ndjson"
KNOWN_BAD_RULES = ("exfil.curl_post_file", "secrets.read_private_key")
_REGEN = "python -m tests.numbat_shaped_events --frozen [--known-bad] --out <golden file>"


def _strict() -> bool:
    return os.environ.get("CYCLAW_REQUIRE_NUMBAT") == "1"


def _missing(what: str) -> NoReturn:
    if _strict():
        pytest.fail(f"{what} is required in this lane (CYCLAW_REQUIRE_NUMBAT=1)")
    pytest.skip(f"{what} not available")


def _numbat() -> str:
    exe = os.environ.get("NUMBAT") or shutil.which("numbat")
    if not exe:
        _missing("numbat CLI")
    return str(exe)


def _import_or_missing(name: str) -> Any:
    # One return, no maybe-unbound name: CodeQL does not model _missing as
    # NoReturn, so both a try/except-return and a bind-then-return shape read
    # to it as a possible None or uninitialized value.
    if importlib.util.find_spec(name) is None:
        _missing(name)
    return importlib.import_module(name)


def _event_validator() -> Any:
    jsonschema = _import_or_missing("jsonschema")
    schema_dir = os.environ.get("NUMBAT_SCHEMA_DIR")
    if not schema_dir:
        _missing("NUMBAT_SCHEMA_DIR")
    schema = json.loads((Path(schema_dir) / "event-record.schema.json").read_text(encoding="utf-8"))
    validator_cls = jsonschema.Draft202012Validator
    return validator_cls(schema, format_checker=validator_cls.FORMAT_CHECKER)


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rules_test(exe: str, fixture: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [exe, "rules", "test", "--fixture", str(fixture), *extra],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture(scope="module")
def live_clean() -> list[dict[str, Any]]:
    return generate()


@pytest.fixture(scope="module")
def live_known_bad() -> list[dict[str, Any]]:
    return generate(known_bad=True)


def test_golden_clean_matches_the_live_producers() -> None:
    assert generate(frozen=True) == _load(GOLDEN_CLEAN), f"emitter output drifted; regenerate with: {_REGEN}"


def test_golden_known_bad_matches_the_live_producers() -> None:
    assert generate(known_bad=True, frozen=True) == _load(GOLDEN_KNOWN_BAD), (
        f"emitter output drifted; regenerate with: {_REGEN}"
    )


def test_every_producer_family_is_represented(live_clean) -> None:
    """A producer that silently stops emitting must not shrink the fixture."""
    artifact_types = {event["evidence"]["artifact_type"] for event in live_clean}
    assert artifact_types == {
        "cyclaw_audit_jsonl", "pre_action_hook", "cel_monitor", "ops_runner", "fsconnect", "sqlconnect",
    }
    tags = {tag for event in live_clean for tag in event["tags"]}
    assert {
        "pre_action_hook", "hook_allowed", "hook_denied", "hook_failure", "hook_error",
        "hook_misconfigured", "engine:command", "engine:numbat",
    } <= tags
    decisions = {e["decision"] for e in live_clean if "pre_action_hook" in e["tags"]}
    assert decisions == {"allowed", "denied"}
    audit_events = [e for e in live_clean if e["evidence"]["artifact_type"] == "cyclaw_audit_jsonl"]
    assert len(audit_events) == 19


@pytest.mark.parametrize("which", ["live_clean", "live_known_bad"])
def test_shaped_events_respect_the_contract_bounds_we_know(which, request) -> None:
    """The subset of the schema checkable without the schema file.

    The full published schema is the oracle (test below); this keeps the
    constraints that have already bitten -- content_preview length, unknown
    top-level keys, the CLI's per-type allowlists -- in the unit lane on
    every OS.
    """
    for event in request.getfixturevalue(which):
        assert event["schema_version"] == SCHEMA_VERSION
        assert event["source_agent"] == "unknown"
        assert set(event) <= _KNOWN_FIELDS
        assert not set(event) & _EVENT_TYPE_FORBIDDEN_FIELDS[event["event_type"]]
        preview = event.get("content_preview")
        if preview is not None:
            assert len(preview) <= CONTENT_PREVIEW_MAX_CHARS
            json.loads(preview)
        assert len(event["tags"]) == len(set(event["tags"]))
        assert all(event["tags"])


@pytest.mark.parametrize("which", ["live_clean", "live_known_bad"])
def test_shaped_events_validate_against_the_published_schema(which, request) -> None:
    validator = _event_validator()
    failures = [
        f"{event['event_type']} ({event['evidence']['artifact_type']}): {error.message}"
        for event in request.getfixturevalue(which)
        for error in validator.iter_errors(event)
    ]
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("golden", [GOLDEN_CLEAN, GOLDEN_KNOWN_BAD], ids=["clean", "known-bad"])
def test_golden_files_validate_against_the_published_schema(golden) -> None:
    validator = _event_validator()
    failures = [error.message for event in _load(golden) for error in validator.iter_errors(event)]
    assert not failures, "\n".join(failures)


def test_numbat_cli_scores_live_cyclaw_traffic_clean(tmp_path, live_clean) -> None:
    exe = _numbat()
    fixture = tmp_path / "cyclaw-shaped.ndjson"
    write_ndjson(live_clean, fixture)
    proc = _rules_test(exe, fixture, "--expect-none")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_numbat_cli_flags_live_cyclaw_shaped_known_bad(tmp_path, live_known_bad) -> None:
    exe = _numbat()
    fixture = tmp_path / "cyclaw-shaped-known-bad.ndjson"
    write_ndjson(live_known_bad, fixture)
    expects = [arg for rule in KNOWN_BAD_RULES for arg in ("--expect", rule)]
    proc = _rules_test(exe, fixture, *expects)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for rule in KNOWN_BAD_RULES:
        assert rule in proc.stdout


def test_numbat_cli_scores_the_golden_files(tmp_path) -> None:
    exe = _numbat()
    clean = _rules_test(exe, GOLDEN_CLEAN, "--expect-none")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    expects = [arg for rule in KNOWN_BAD_RULES for arg in ("--expect", rule)]
    bad = _rules_test(exe, GOLDEN_KNOWN_BAD, *expects)
    assert bad.returncode == 0, bad.stdout + bad.stderr
