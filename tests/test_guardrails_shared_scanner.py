"""Contract tests for the injection scanner shared by guardrails/ and agentic/.

agentic/fsconnect/client.py used to rebuild the
``OWASP ∪ policy.prompt_filter.banned_patterns`` union itself (as did the skills
registry and harness optimizer, both removed in October 2026). It now routes
through guardrails.rails. These tests pin the two things that consolidation
must not break: the call site keeps seeing the SAME pattern set (the anti-drift
contract), and keeps its OWN enforcement posture (guardrails owns how the set
is built, never whether a caller blocks on a hit).
"""

from __future__ import annotations

import pytest

from guardrails.rails import (
    build_injection_pattern_sources,
    build_injection_patterns,
    compile_injection_patterns,
    scan_injection,
    scan_injection_patterns,
)
from utils.personality import OWASP_INJECTION_PATTERNS

_CFG = {"policy": {"prompt_filter": {"banned_patterns": [r"ignore\s+previous\s+instructions"]}}}


def test_sources_are_owasp_baseline_then_config_extras():
    sources = build_injection_pattern_sources(_CFG)
    # OWASP baseline first, in order, then config entries not already present.
    assert sources[: len(OWASP_INJECTION_PATTERNS)] == list(OWASP_INJECTION_PATTERNS)
    assert sources[-1] == r"ignore\s+previous\s+instructions"


def test_config_patterns_already_in_baseline_are_not_duplicated():
    cfg = {"policy": {"prompt_filter": {"banned_patterns": list(OWASP_INJECTION_PATTERNS)}}}
    assert build_injection_pattern_sources(cfg) == list(OWASP_INJECTION_PATTERNS)


def test_missing_policy_block_degrades_to_the_owasp_baseline():
    assert build_injection_pattern_sources({}) == list(OWASP_INJECTION_PATTERNS)


@pytest.mark.parametrize("bad", [None, 42, ["nested"], {"k": "v"}])
def test_non_string_config_entries_are_skipped_not_raised(bad):
    # re.compile raises TypeError (NOT re.error) on a non-string, which would
    # escape the compile loop's handler; the harness optimizer carried this guard
    # before consolidation and every caller inherits it now.
    cfg = {"policy": {"prompt_filter": {"banned_patterns": [bad, r"safe\s+pattern"]}}}
    sources = build_injection_pattern_sources(cfg)
    assert bad not in sources
    assert r"safe\s+pattern" in sources
    build_injection_patterns(cfg)  # must not raise


def test_uncompilable_pattern_is_dropped_not_raised():
    cfg = {"policy": {"prompt_filter": {"banned_patterns": ["valid", "((("]}}}
    compiled_sources = {src for src, _ in build_injection_patterns(cfg)}
    assert "(((" not in compiled_sources
    assert "valid" in compiled_sources


def test_patterns_are_case_insensitive():
    patterns = build_injection_patterns(_CFG)
    assert scan_injection_patterns("IGNORE PREVIOUS INSTRUCTIONS", patterns)


def test_scan_returns_pattern_sources_not_matched_text():
    # Sources let a caller audit-log which rule fired without echoing the text.
    patterns = build_injection_patterns(_CFG)
    hits = scan_injection_patterns("please ignore previous instructions", patterns)
    assert r"ignore\s+previous\s+instructions" in hits


def test_clean_text_produces_no_hits():
    assert scan_injection_patterns("what is the capital of france", build_injection_patterns(_CFG)) == []


def test_compile_is_memoized_by_source_tuple():
    compile_injection_patterns.cache_clear()
    sources = tuple(build_injection_pattern_sources(_CFG))
    compile_injection_patterns(sources)
    compile_injection_patterns(sources)
    assert compile_injection_patterns.cache_info().hits >= 1


def test_fsconnect_call_site_resolves_to_the_shared_pattern_set():
    # The anti-drift contract: whatever fsconnect scans with, it is the same set.
    from agentic.fsconnect.client import build_injection_patterns as fsconnect_build

    expected = {src for src, _ in build_injection_patterns(_CFG)}
    assert {src for src, _ in fsconnect_build(_CFG)} == expected
    assert set(build_injection_pattern_sources(_CFG)) == expected


def test_light_marker_scan_stays_separate_from_the_full_set():
    # scan_injection is the deliberately-small query-path rail behind
    # utils/sanitizer.py's fail-closed filter. It must NOT silently inherit the
    # advisory OWASP set -- "act as" is legitimate in a normal user query, and
    # utils/personality.py documents that set as advisory for exactly that reason.
    assert scan_injection("can you act as a summarizer for these notes") == []
    assert scan_injection("ignore previous instructions") == ["ignore previous instructions"]
