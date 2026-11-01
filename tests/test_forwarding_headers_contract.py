"""gate.py and gate_auth.py must agree on the reverse-proxy forwarding headers.

Both modules define ``_FORWARDING_HEADERS``, the presence-only set that stops a
proxy on this host from making every remote caller look like a loopback peer:
gate.py uses it for the ``api_key_optional`` bypass and the ``/index/build``
guard, gate_auth.py for the loopback-only bootstrap route. A header added to one
copy and not the other leaves one route family open behind a proxy, so the two
literals are pinned equal here (docs/audits/2026-10-31-ponytail-audit.md).

The check parses the source with ``ast`` instead of importing either module:
``import gate`` at test-module level triggers full app init (CLAUDE.md §4).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_NAME = "_FORWARDING_HEADERS"


def _forwarding_headers(source: str) -> tuple[str, ...]:
    """Return the module-level ``_FORWARDING_HEADERS`` literal from *source*."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == _NAME for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, tuple), f"{_NAME} must stay a tuple literal"
            return value
    raise AssertionError(f"{_NAME} not found as a module-level assignment")


def _read(name: str) -> tuple[str, ...]:
    return _forwarding_headers((_REPO_ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("module", ["gate.py", "gate_auth.py"])
def test_forwarding_headers_are_lowercase_unique_and_non_empty(module: str) -> None:
    headers = _read(module)
    assert headers, f"{module} {_NAME} is empty"
    # Starlette's request.headers matches case-insensitively, but a duplicate or a
    # mixed-case entry signals a hand edit that skipped this contract.
    assert all(isinstance(h, str) and h == h.lower() and h.strip() == h for h in headers)
    assert len(set(headers)) == len(headers), f"{module} {_NAME} has duplicates"


def test_gate_and_gate_auth_forwarding_headers_match() -> None:
    assert set(_read("gate.py")) == set(_read("gate_auth.py")), (
        "gate.py and gate_auth.py _FORWARDING_HEADERS diverged; update both together"
    )


def test_parser_detects_a_divergent_copy() -> None:
    # Guards the guard: a one-sided addition must change what the parser returns.
    source = (_REPO_ROOT / "gate_auth.py").read_text(encoding="utf-8")
    widened = source.replace('"forwarded",', '"forwarded",\n    "x-forwarded-port",', 1)
    assert widened != source, "fixture anchor moved; update this test"
    assert set(_forwarding_headers(widened)) != set(_read("gate.py"))
