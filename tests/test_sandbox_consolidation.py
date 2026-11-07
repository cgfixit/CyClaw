"""Behavior contracts for the maintained Sandbox helpers and their delegates."""

from __future__ import annotations

import importlib.util
from io import BytesIO
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.request import HTTPHandler, ProxyHandler, Request, build_opener
from urllib.response import addinfourl

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / ".claude/skills/CyClaw-Sandbox"


def load_helper(name):
    spec = importlib.util.spec_from_file_location("sandbox_console", CANONICAL / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("url", [
    "https://example.com", "file:///etc/hosts", "http://example.com",  # DevSkim: ignore DS137138,DS162092 - synthetic refused URL; no real network transport
    "http://127.0.0.1@external.invalid", "http://user@localhost",  # DevSkim: ignore DS137138,DS162092 - synthetic refused URL; no real network transport
    "http://localhost/path", "http://localhost?query", "http://localhost#fragment",  # DevSkim: ignore DS137138,DS162092 - synthetic refused URL; no real network transport
])
def test_console_refuses_non_loopback_origins_before_transport(url, monkeypatch):
    module = load_helper("test_terminal_consoles.py")
    monkeypatch.setattr(module, "BASE_URL", url)
    transport = MagicMock()
    monkeypatch.setattr(module, "_OPEN", transport)
    with pytest.raises(ValueError):
        module.ConsoleTest()._request("GET", "/soul")
    transport.assert_not_called()


def test_console_refuses_redirect_with_bearer_key():
    module = load_helper("test_terminal_consoles.py")
    request = Request("http://127.0.0.1/soul", headers={"Authorization": "Bearer synthetic"})  # DevSkim: ignore DS137138,DS162092 - synthetic refused URL; no real network transport
    calls = []

    class Redirect(HTTPHandler):
        def http_open(self, req):
            calls.append(req.full_url)
            headers = Message()
            headers["Location"] = "http://external.invalid"  # DevSkim: ignore DS137138,DS162092 - synthetic refused URL; no real network transport
            response = addinfourl(BytesIO(), headers, req.full_url, 302)
            response.msg = "redirect"
            return response

    opener = build_opener(ProxyHandler({}), module._NoRedirect(), Redirect())
    with pytest.raises(HTTPError, match="302"):
        opener.open(request)
    assert calls == [request.full_url]


@pytest.mark.parametrize("value, expected", [("nosniff", True), ("unsafe", False)])
def test_console_checks_header_values_case_insensitively(value, expected, monkeypatch):
    module = load_helper("test_terminal_consoles.py")
    headers = Message()
    headers["x-content-type-options"] = value
    headers["x-frame-options"] = "DENY"
    response = MagicMock()
    response.__enter__.return_value = SimpleNamespace(headers=headers)

    def open_probe(request, **kwargs):
        if request.get_header("Authorization"):
            raise HTTPError(request.full_url, 401, "unauthorized", {}, None)
        return response

    monkeypatch.setattr(module, "_OPEN", open_probe)
    tester = module.ConsoleTest()
    monkeypatch.setattr(tester, "_request", lambda *a, **kw: (200, {}))
    tester.run_all()
    checks = {name: ok for name, ok, _ in tester.tests}
    assert checks["X-Content-Type-Options header"] is expected
    assert checks["X-Frame-Options header"] is True
