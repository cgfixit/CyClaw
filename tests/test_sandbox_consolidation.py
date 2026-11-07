"""Behavior contracts for the maintained Sandbox helpers and their delegates."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
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


@pytest.mark.parametrize("name", [
    "run_full_verification.py", "gate_runtime_check.py", "test_terminal_consoles.py",
    "verify.sh", "smoke.sh", "macos-smoke.sh",
])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_delegate_preserves_arguments_environment_and_exit(tmp_path, name, exit_code):
    if name.endswith(".sh") and sys.platform == "win32":
        pytest.skip("POSIX shell helper")
    root = tmp_path / "checkout with spaces"
    delegate = root / ".agents/skills/cyclaw-sandbox" / name
    target = root / ".claude/skills/CyClaw-Sandbox" / name
    delegate.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    shutil.copy2(ROOT / ".agents/skills/cyclaw-sandbox" / name, delegate)
    probe = (
        "import json,os,sys\n"
        "print(json.dumps({'args':sys.argv[1:], 'cwd':os.getcwd(), "
        "'marker':os.environ['TEST_MARKER'], 'report':os.environ.get('CYCLAW_REPORT_DIR')}))\n"
        "sys.exit(int(os.environ['TEST_EXIT']))\n"
    )
    target.write_text(
        probe if name.endswith(".py") else '"$TEST_PYTHON" - "$@" <<\'PY\'\n' + probe + "PY\n",
        encoding="utf-8",
    )
    env = {**os.environ, "TEST_PYTHON": sys.executable, "TEST_EXIT": str(exit_code),
           "TEST_MARKER": "preserved", "CYCLAW_REPORT_DIR": str(tmp_path / "report with spaces")}
    expected_report = env["CYCLAW_REPORT_DIR"]
    if name == "smoke.sh" and exit_code:
        env.pop("CYCLAW_REPORT_DIR")
        env["TMPDIR"] = str(tmp_path)
        expected_report = str(tmp_path / "cyclaw-sandbox-report")
    command = [sys.executable if name.endswith(".py") else "/bin/bash", str(delegate), "--probe", "two words"]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == exit_code, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "args": ["--probe", "two words"], "marker": "preserved",
        "report": expected_report,
        "cwd": str(root if name.endswith(".sh") else tmp_path),
    }


@pytest.mark.parametrize("name", ["run_full_verification.py", "gate_runtime_check.py"])
def test_real_python_delegate_fails_without_dependencies(tmp_path, name):
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / ".agents/skills/cyclaw-sandbox" / name)],
        cwd=tmp_path, env={"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")},
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stdout + result.stderr or "LangGraph is required" in result.stdout + result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("shell", ["powershell", "pwsh"])
@pytest.mark.parametrize("port, exit_code", [(None, 0), (9101, 7)])
def test_powershell_delegate_preserves_port_and_exit(tmp_path, shell, port, exit_code):
    executable = shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} unavailable; covered on Windows CI")
    root = tmp_path / "checkout with spaces"
    delegate = root / ".agents/skills/cyclaw-sandbox/windows-smoke.ps1"
    target = root / ".claude/skills/CyClaw-Sandbox/windows-smoke.ps1"
    delegate.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    shutil.copy2(ROOT / ".agents/skills/cyclaw-sandbox/windows-smoke.ps1", delegate)
    target.write_text('param([int]$Port = 8787)\nWrite-Output $Port\nexit ' + str(exit_code), encoding="utf-8")
    command = [executable, "-NoProfile", "-NonInteractive", "-File", str(delegate)]
    if port is not None:
        command += ["-Port", str(port)]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == exit_code, result.stderr
    assert result.stdout.strip() == str(port if port is not None else 8787)
