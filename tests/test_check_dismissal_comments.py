"""Contract tests for scripts/check_dismissal_comments.py (issue #1779).

Synthetic alert fixtures only: no network, no token, no clock. The API fetch
is exercised by replacing the module's single HTTP seam, ``_get_json``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_dismissal_comments.py"
_API = "https://api.github.com"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_dismissal_comments", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_dismissal_comments"] = module
    spec.loader.exec_module(module)
    return module


cdc = _load()
CUTOFF = cdc.parse_cutoff("2026-11-07")


def _alert(number: int, dismissed_at: str, comment: object, updated_at: str | None = None) -> dict[str, Any]:
    return {
        "number": number,
        "state": "dismissed",
        "dismissed_at": dismissed_at,
        "updated_at": updated_at or dismissed_at,
        "dismissed_comment": comment,
        "dismissed_reason": "false positive",
        "html_url": f"https://github.com/o/r/security/code-scanning/{number}",
    }


@pytest.mark.parametrize("comment", [None, "", "   ", "\n\t"])
def test_missing_or_blank_comment_is_a_gap(comment: object) -> None:
    gaps, in_scope = cdc.find_gaps([_alert(1, "2026-11-08T00:00:00Z", comment)], CUTOFF)
    assert [gap.number for gap in gaps] == [1]
    assert in_scope == 1


def test_written_comment_is_not_a_gap() -> None:
    gaps, in_scope = cdc.find_gaps([_alert(1, "2026-11-08T00:00:00Z", "Checked graph.py@abc1234.")], CUTOFF)
    assert gaps == []
    assert in_scope == 1


def test_cutoff_is_inclusive_and_older_dismissals_are_out_of_scope() -> None:
    alerts = [
        _alert(1, "2026-11-06T23:59:59Z", None),
        _alert(2, "2026-11-07T00:00:00Z", None),
    ]
    gaps, in_scope = cdc.find_gaps(alerts, CUTOFF)
    assert [gap.number for gap in gaps] == [2]
    assert in_scope == 1


def test_non_dismissed_alerts_are_ignored() -> None:
    alert = _alert(1, "2026-11-08T00:00:00Z", None)
    alert["state"] = "open"
    assert cdc.find_gaps([alert], CUTOFF) == ([], 0)


def test_bad_timestamp_is_an_error_not_a_pass() -> None:
    with pytest.raises(cdc.CheckError):
        cdc.find_gaps([_alert(1, "not-a-date", None)], CUTOFF)


def test_pagination_stops_once_past_the_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "first": ([_alert(1, "2026-11-09T00:00:00Z", None)], f"{_API}/page2"),
        "page2": ([_alert(2, "2026-10-01T00:00:00Z", None)], f"{_API}/page3"),
    }
    calls: list[str] = []

    def fake_get(url: str, token: str) -> tuple[Any, str | None]:
        calls.append(url)
        key = "first" if "code-scanning/alerts" in url else url.rsplit("/", 1)[1]
        return pages[key]

    monkeypatch.setattr(cdc, "_get_json", fake_get)
    gaps, in_scope = cdc.find_gaps(cdc.fetch_dismissed_alerts(_API, "o/r", "t", CUTOFF), CUTOFF)
    assert [gap.number for gap in gaps] == [1]
    assert in_scope == 1
    assert len(calls) == 2  # page3 is never requested
    assert "state=dismissed" in calls[0] and "sort=updated" in calls[0]


def test_pagination_refuses_a_foreign_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cdc,
        "_get_json",
        lambda url, token: ([_alert(1, "2026-11-09T00:00:00Z", None)], "https://evil.example/next"),
    )
    with pytest.raises(cdc.CheckError, match="another origin"):
        list(cdc.fetch_dismissed_alerts(_API, "o/r", "t", CUTOFF))


def test_non_list_api_payload_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cdc, "_get_json", lambda url, token: ({"message": "Bad credentials"}, None))
    with pytest.raises(cdc.CheckError):
        list(cdc.fetch_dismissed_alerts(_API, "o/r", "t", CUTOFF))


def test_exit_codes_distinguish_gaps_clean_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    gap_file = tmp_path / "gap.json"
    gap_file.write_text(json.dumps([_alert(7, "2026-11-08T00:00:00Z", "")]), encoding="utf-8")
    clean_file = tmp_path / "clean.json"
    clean_file.write_text(json.dumps([_alert(8, "2026-11-08T00:00:00Z", "ok")]), encoding="utf-8")
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{}", encoding="utf-8")
    out = tmp_path / "out.json"

    assert cdc.main(["--fixture", str(gap_file), "--json-out", str(out)]) == cdc.EXIT_GAPS
    assert [gap["number"] for gap in json.loads(out.read_text(encoding="utf-8"))["gaps"]] == [7]
    assert cdc.main(["--fixture", str(clean_file)]) == cdc.EXIT_OK
    assert cdc.main(["--fixture", str(bad_file)]) == cdc.EXIT_ERROR


def test_missing_token_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert cdc.main(["--repo", "o/r"]) == cdc.EXIT_ERROR


def test_pagination_cap_allows_exactly_max_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cdc, "_MAX_PAGES", 3)

    def pages(limit: int) -> Any:
        count = [0]

        def fake_get(url: str, token: str) -> tuple[Any, str | None]:
            count[0] += 1
            alert = _alert(count[0], "2026-11-09T00:00:00Z", "ok")
            return [alert], (f"{_API}/next" if count[0] < limit else None)

        return fake_get

    monkeypatch.setattr(cdc, "_get_json", pages(3))
    assert len(list(cdc.fetch_dismissed_alerts(_API, "o/r", "t", CUTOFF))) == 3
    monkeypatch.setattr(cdc, "_get_json", pages(4))
    with pytest.raises(cdc.CheckError, match="stopped after 3 pages"):
        list(cdc.fetch_dismissed_alerts(_API, "o/r", "t", CUTOFF))


def test_unexpected_failures_never_read_as_gaps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # An uncaught exception exits 1, the "gaps found" code; both cases must be 2.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    bad_number = tmp_path / "bad-number.json"
    alert = _alert(1, "2026-11-08T00:00:00Z", None)
    alert["number"] = None
    bad_number.write_text(json.dumps([alert]), encoding="utf-8")
    assert cdc.main(["--fixture", str(bad_number)]) == cdc.EXIT_ERROR

    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps([_alert(2, "2026-11-08T00:00:00Z", "ok")]), encoding="utf-8")
    unwritable = tmp_path / "missing-dir" / "summary.md"
    assert cdc.main(["--fixture", str(clean), "--summary-out", str(unwritable)]) == cdc.EXIT_ERROR
