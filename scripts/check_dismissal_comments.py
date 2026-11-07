#!/usr/bin/env python3
"""Report code-scanning dismissals that carry no written rationale (issue #1779).

Policy (root ``SECURITY.md``, "Code-scanning dismissals"): every alert dismissed
on or after ``EFFECTIVE_DATE`` needs a dismissal reason plus one sentence saying
what was checked. GitHub makes the comment optional, so this is a reporting
check, not a platform gate: it lists dismissed alerts whose ``dismissed_comment``
is null, empty, or whitespace-only, and exits non-zero so the scheduled run goes
red. Historical dismissals before the effective date are deliberately out of
scope; nothing here edits, dismisses, or reopens an alert.

Read-only by construction: the only HTTP verb is GET, and the token is sent
only to the configured API origin. Pagination links to any other origin and
HTTP redirects are refused, so neither a crafted ``Link`` header nor a 30x can
carry the token elsewhere. TLS verification is urllib's default.

Exit codes are an API:
  0  no dismissal on/after the cutoff lacks a rationale
  1  at least one such dismissal was found (listed in the report)
  2  usage, auth, network, or API-shape error; no conclusion was reached

Usage:
  GITHUB_TOKEN=... python3 -I scripts/check_dismissal_comments.py --repo owner/name
  python3 -I scripts/check_dismissal_comments.py --fixture alerts.json   # offline
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EFFECTIVE_DATE = "2026-11-07"
EXIT_OK = 0
EXIT_GAPS = 1
EXIT_ERROR = 2

_DEFAULT_API = "https://api.github.com"
_PER_PAGE = 100
_MAX_PAGES = 200
_TIMEOUT_SEC = 30
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_NEXT_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


class CheckError(Exception):
    """A failure that prevents any conclusion; maps to EXIT_ERROR."""


@dataclass(frozen=True)
class Gap:
    number: int
    dismissed_at: str
    dismissed_reason: str
    dismissed_by: str
    rule: str
    tool: str
    url: str


def parse_timestamp(value: object) -> datetime:
    """Parse a GitHub ISO-8601 timestamp (``...Z``) into an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise CheckError(f"missing or non-string timestamp: {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CheckError(f"unparseable timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_cutoff(value: str) -> datetime:
    """A ``YYYY-MM-DD`` date means midnight UTC; a full timestamp is taken as-is."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        value = f"{value}T00:00:00Z"
    return parse_timestamp(value)


def has_rationale(comment: object) -> bool:
    return isinstance(comment, str) and comment.strip() != ""


def find_gaps(alerts: Iterable[dict[str, Any]], cutoff: datetime) -> tuple[list[Gap], int]:
    """Return (gaps, in_scope) for dismissed alerts at or after ``cutoff``.

    ``in_scope`` counts every dismissed alert on/after the cutoff, so a report
    can show "0 of N" and a zero-gap result is distinguishable from no data.
    """
    gaps: list[Gap] = []
    in_scope = 0
    for alert in alerts:
        if not isinstance(alert, dict):
            raise CheckError(f"alert entry is not an object: {type(alert).__name__}")
        if alert.get("state") != "dismissed":
            continue
        if parse_timestamp(alert.get("dismissed_at")) < cutoff:
            continue
        in_scope += 1
        if has_rationale(alert.get("dismissed_comment")):
            continue
        rule = alert.get("rule") or {}
        tool = alert.get("tool") or {}
        by = alert.get("dismissed_by") or {}
        gaps.append(
            Gap(
                number=int(alert.get("number", 0)),
                dismissed_at=str(alert.get("dismissed_at")),
                dismissed_reason=str(alert.get("dismissed_reason") or "(none)"),
                dismissed_by=str(by.get("login") or "(unknown)") if isinstance(by, dict) else "(unknown)",
                rule=str(rule.get("id") or "(unknown)") if isinstance(rule, dict) else "(unknown)",
                tool=str(tool.get("name") or "(unknown)") if isinstance(tool, dict) else "(unknown)",
                url=str(alert.get("html_url") or ""),
            )
        )
    gaps.sort(key=lambda gap: gap.number)
    return gaps, in_scope


def _origin(url: str) -> tuple[str, str]:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme, parts.netloc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # urllib copies request headers, Authorization included, onto a redirect
    # target on any host. The list endpoint never needs a redirect, so treat
    # one as an error instead of carrying the token somewhere else.
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise CheckError(f"refusing HTTP {code} redirect to {newurl}")


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get_json(url: str, token: str) -> tuple[Any, str | None]:
    if _origin(url)[0] != "https":
        raise CheckError(f"refusing non-https URL: {url}")
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cyclaw-dismissal-comment-check",
        },
        method="GET",
    )
    try:
        with _OPENER.open(request, timeout=_TIMEOUT_SEC) as response:
            body = response.read()
            link = response.headers.get("Link")
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code in (401, 403):
            hint = " (token lacks security-events: read, or code scanning is unavailable)"
        elif exc.code == 404:
            hint = " (repository not found, or code scanning is not enabled)"
        raise CheckError(f"GitHub API returned HTTP {exc.code} for {url}{hint}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CheckError(f"network error fetching {url}: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CheckError(f"non-JSON response from {url}") from exc
    match = _NEXT_LINK_RE.search(link or "")
    return payload, (match.group(1) if match else None)


def fetch_dismissed_alerts(api: str, repo: str, token: str, cutoff: datetime) -> Iterator[dict[str, Any]]:
    """Yield dismissed alerts, newest-updated first, stopping once past the cutoff.

    ``updated_at >= dismissed_at`` for every alert, so once a page's oldest
    ``updated_at`` falls before the cutoff no later page can hold an in-scope
    dismissal. The whole page is still yielded; ``find_gaps`` filters it.
    """
    query = urllib.parse.urlencode(
        {"state": "dismissed", "sort": "updated", "direction": "desc", "per_page": _PER_PAGE}
    )
    url: str | None = f"{api.rstrip('/')}/repos/{repo}/code-scanning/alerts?{query}"
    allowed_origin = _origin(api)
    for _ in range(_MAX_PAGES):
        if url is None:
            return
        if _origin(url) != allowed_origin:
            raise CheckError(f"refusing pagination link to another origin: {url}")
        page, url = _get_json(url, token)
        if not isinstance(page, list):
            raise CheckError("expected a JSON array of alerts from the code-scanning API")
        yield from page
        if not page:
            return
        stamps = [parse_timestamp(alert.get("updated_at")) for alert in page if isinstance(alert, dict)]
        if stamps and min(stamps) < cutoff:
            return
    raise CheckError(f"stopped after {_MAX_PAGES} pages without reaching the cutoff")


def load_fixture(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot read fixture {path}: {exc}") from exc
    if not isinstance(data, list):
        raise CheckError("fixture must be a JSON array of alert objects")
    return data


def _cell(value: str) -> str:
    # Alert fields come from the API; keep a stray pipe or newline from breaking the table.
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(gaps: list[Gap], in_scope: int, cutoff: datetime, repo: str) -> str:
    since = cutoff.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "## Code-scanning dismissal rationale check",
        "",
        f"Repository `{repo}`; dismissals on or after {since} (policy: root `SECURITY.md`).",
        "",
        f"**{len(gaps)} of {in_scope}** in-scope dismissals have no written rationale.",
    ]
    if gaps:
        lines += [
            "",
            "Add a one-sentence comment saying what was checked (scope/revision, and any reopen trigger).",
            "",
            "| Alert | Dismissed (UTC) | Reason | By | Tool / rule |",
            "| --- | --- | --- | --- | --- |",
        ]
        for gap in gaps:
            link = f"[#{gap.number}]({gap.url})" if gap.url else f"#{gap.number}"
            lines.append(
                f"| {link} | {_cell(gap.dismissed_at)} | {_cell(gap.dismissed_reason)} | {_cell(gap.dismissed_by)} | "
                f"{_cell(gap.tool)} / `{_cell(gap.rule)}` |"
            )
    lines.append("")
    lines.append("This is a reporting check, not a platform restriction: GitHub still accepts an empty comment.")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/name")
    parser.add_argument("--since", default=EFFECTIVE_DATE, help="cutoff date/timestamp (default: policy date)")
    parser.add_argument("--fixture", type=Path, help="read alerts from a JSON array instead of the API")
    parser.add_argument("--json-out", type=Path, help="write the machine-readable result here")
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None,
        help="append the Markdown report here (default: $GITHUB_STEP_SUMMARY)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo = args.repo or "(fixture)"
    try:
        cutoff = parse_cutoff(args.since)
        if args.fixture is not None:
            alerts: Iterable[dict[str, Any]] = load_fixture(args.fixture)
        else:
            if not _REPO_RE.fullmatch(args.repo):
                raise CheckError("--repo must be owner/name (or set GITHUB_REPOSITORY)")
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
            if not token:
                raise CheckError("GITHUB_TOKEN (or GH_TOKEN) is not set")
            api = os.environ.get("GITHUB_API_URL", _DEFAULT_API)
            alerts = fetch_dismissed_alerts(api, args.repo, token, cutoff)
        gaps, in_scope = find_gaps(alerts, cutoff)
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    report = render_markdown(gaps, in_scope, cutoff, repo)
    sys.stdout.write(report)
    if args.summary_out is not None:
        with args.summary_out.open("a", encoding="utf-8") as handle:
            handle.write(report)
    if args.json_out is not None:
        result = {
            "repository": repo,
            "cutoff": cutoff.isoformat(),
            "in_scope": in_scope,
            "gaps": [asdict(gap) for gap in gaps],
        }
        args.json_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return EXIT_GAPS if gaps else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
