#!/usr/bin/env python3
"""Render the CyClaw terminal in isolated browser contexts.

This is an optional browser lane. It requires the Playwright Python package and
an installed Chromium browser. It never contacts an external provider.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Every /auth/* route answers 503 while auth.enabled ships false (CLAUDE.md
# section 2), and auth_admin.js probes /auth/whoami on load. Chromium logs any
# non-2xx resource as a console error, so that one documented refusal is not a
# console failure. Any other path, or any other status, still is.
_EXPECTED_AUTH_OFF = "Failed to load resource: the server responded with a status of 503"


def _expected_console_error(message: Any) -> bool:
    url = (message.location or {}).get("url", "")
    return message.text.startswith(_EXPECTED_AUTH_OFF) and urlsplit(url).path.startswith("/auth/")


# terminal.js ends every query in exactly one of these entries: an answer, an
# online-confirmation prompt, or an error. #results is visible from page load,
# so waiting on it alone passed while the console still read "searching vault".
_QUERY_DONE = ".answer-entry, .confirm-entry, .error-entry"


def _exercise(page: Any) -> list[str]:
    page.locator("#queryInput").fill("what is CyClaw")
    page.locator("#sendBtn").click()
    done = page.locator(_QUERY_DONE).first
    done.wait_for(state="visible", timeout=120_000)
    if "error-entry" in (done.get_attribute("class") or ""):
        return [f"query ended in an error entry: {done.inner_text()[:200]!r}"]
    return []


def _render(page: Any, name: str, url: str, out: Path, mobile: bool, exercise: bool) -> list[str]:
    failures: list[str] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    request_failures: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error" and not _expected_console_error(message)
        else None,
    )
    page.on(
        "requestfailed",
        lambda request: request_failures.append(
            f"{request.method} {request.url}: {request.failure}"
        ),
    )
    try:
        # Not "networkidle": the console polls /health every 15 s and leaves the
        # /auth/whoami 503 body unread, which Chromium counts as in flight, so
        # idle never arrives. Wait for load plus the query input instead.
        page.goto(url, wait_until="load", timeout=30_000)
        page.locator("#queryInput").wait_for(state="visible", timeout=10_000)
        if not page.locator("body").inner_text().strip():
            failures.append(f"{name}: body rendered empty")
        if exercise:
            failures.extend(f"{name}: {failure}" for failure in _exercise(page))
    except Exception as exc:
        failures.append(f"{name}: browser flow failed: {type(exc).__name__}: {exc}")
    suffix = "mobile" if mobile else "desktop"
    page.screenshot(path=str(out / f"{name}-{suffix}.png"), full_page=True)
    if page_errors:
        failures.append(f"{name}: page errors: {page_errors}")
    if console_errors:
        failures.append(f"{name}: console errors: {console_errors}")
    if request_failures:
        failures.append(f"{name}: request failures: {request_failures}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://127.0.0.1:8787/")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--no-exercise", action="store_true")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: install playwright and a Chromium browser for rendering evidence")
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        for mobile, viewport in (
            (False, {"width": 1440, "height": 1000}),
            (True, {"width": 390, "height": 844}),
        ):
            context = browser.new_context(viewport=viewport, is_mobile=mobile)
            page = context.new_page()
            failures.extend(
                _render(page, "terminal", args.gateway, args.out, mobile, not args.no_exercise)
            )
            context.close()
        browser.close()

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"PASS: browser rendering and screenshots written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
