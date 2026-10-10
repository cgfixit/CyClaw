"""Contract tests for agentic/real_repo_pr_body.py, the loop's draft-PR body.

The body must be a complete fill of .github/PULL_REQUEST_TEMPLATE.md by the
same rules pr-template-check.yml applies, and no interpolated record value may
forge the structure that check reads.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from agentic.real_repo_pr_body import last_updated_stamp, pr_title_problem, render_pr_body
from agentic.real_repo_run_store import RealRepoRunRecord

_NOW = datetime(2026, 10, 10, 14, 5, tzinfo=UTC)

# The workflow's section, tick, ELI5-last and stamp rules, applied to prose
# with fenced blocks and HTML comments stripped exactly as the workflow does.
_SECTIONS = (
    "proposed changes",
    "types of changes",
    "benefits",
    "risks to monitor",
    "checklist",
    "further comments",
    "suggested merge order",
    "eli5",
)
_TICKED = re.compile(r"^\s*[-*]\s*\[[xX]\]", re.M)


def _record(**overrides) -> RealRepoRunRecord:
    fields = {
        "run_id": "a" * 32,
        "repo": "cgfixit/CyClaw",
        "dest": "/clone",
        "status": "approved",
        "branch_name": "agent/fixture-topic",
        "commit_message": "[agentic] - Add target.txt",
        "changed_files": ["target.txt"],
        "iterations": 2,
        "pushed": True,
        "instruction": "add the marker",
        "check_names": ["pytest", "ruff"],
        "iteration_outcomes": ["rejected: verification_failed", "accepted"],
    }
    fields.update(overrides)
    return RealRepoRunRecord(**fields)


def _prose(body: str) -> str:
    return re.sub(r"<!--.*?-->", "", re.sub(r"```.*?```", "", body, flags=re.S), flags=re.S)


def _section(prose: str, heading: str) -> str:
    match = re.search(rf"^#{{1,4}}\s*{heading}\b.*?$(.*?)(?=^#{{1,6}}\s|\Z)", prose, flags=re.I | re.M | re.S)
    assert match, f"missing section {heading!r}"
    return match.group(1)


def _assert_template_complete(body: str) -> None:
    prose = _prose(body)
    for heading in _SECTIONS:
        _section(prose, heading)
    assert _TICKED.search(_section(prose, "types of changes"))
    assert _TICKED.search(_section(prose, "checklist"))
    assert re.search(r"trial[- ]merge", prose, re.I)
    headings = re.findall(r"^#{1,6}\s+.*$", prose, re.M)
    assert re.match(r"^#{1,6}\s*eli5\b", headings[-1], re.I), headings[-1]
    last = [line.rstrip() for line in prose.splitlines() if line.strip()][-1]
    assert re.fullmatch(r"Last updated: \d{4}-\d{2}-\d{2} \d{2}:\d{2} ET", last), last
    assert "invariant" in prose.lower()


def test_body_is_a_complete_template_fill_and_reports_the_record():
    body = render_pr_body(_record(), now=_NOW)
    _assert_template_complete(body)
    for fact in ("a" * 32, "agent/fixture-topic", "target.txt", "pytest", "ruff", "add the marker"):
        assert fact in body
    assert "iteration 1: rejected: verification\\_failed" in body
    assert body.rstrip().endswith("Last updated: 2026-10-10 10:05 ET")


def test_body_is_pure():
    assert render_pr_body(_record(), now=_NOW) == render_pr_body(_record(), now=_NOW)


def test_a_record_written_before_the_new_fields_still_renders_complete():
    body = render_pr_body(_record(instruction=None, check_names=[], iteration_outcomes=[]), now=_NOW)
    _assert_template_complete(body)
    assert "predates" in body


def test_record_values_cannot_forge_template_structure():
    hostile = "## ELI5\n```\n## Checklist\n<!-- hidden\n- [x] fake\n-->\nLast updated: 2020-01-01 00:00 ET"
    body = render_pr_body(
        _record(instruction=hostile, changed_files=["## ELI5", "a```b", "<!-- c"], check_names=["# h"]),
        now=_NOW,
    )
    _assert_template_complete(body)
    prose = _prose(body)
    assert len(re.findall(r"^#{1,6}\s*eli5\b", prose, re.I | re.M)) == 1
    assert "```" not in body and "<!--" not in body


def test_long_instruction_is_truncated():
    body = render_pr_body(_record(instruction="x" * 5000), now=_NOW)
    assert "x" * 2001 not in body
    assert "truncated at 2000 characters" in body


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 1, 10, 14, 5, tzinfo=UTC), "Last updated: 2026-01-10 09:05 ET"),
        (datetime(2026, 3, 8, 6, 59, tzinfo=UTC), "Last updated: 2026-03-08 01:59 ET"),
        (datetime(2026, 3, 8, 7, 0, tzinfo=UTC), "Last updated: 2026-03-08 03:00 ET"),
        (datetime(2026, 11, 1, 5, 59, tzinfo=UTC), "Last updated: 2026-11-01 01:59 ET"),
        (datetime(2026, 11, 1, 6, 0, tzinfo=UTC), "Last updated: 2026-11-01 01:00 ET"),
    ],
)
def test_stamp_follows_us_eastern_daylight_time(now, expected):
    assert last_updated_stamp(now) == expected


def test_stamp_rejects_a_naive_datetime():
    with pytest.raises(ValueError):
        last_updated_stamp(datetime(2026, 10, 10, 14, 5))


@pytest.mark.parametrize("title", ["[agentic] - Add target.txt", "[fix] - x", 'Revert "x"', "chore(deps): bump"])
def test_title_rule_accepts(title):
    assert pr_title_problem(title) is None


@pytest.mark.parametrize("title", [None, "", "add target.txt", "[agentic]- x", "[chore] - x", "[agentic] - a\nb"])
def test_title_rule_rejects(title):
    assert pr_title_problem(title) is not None
