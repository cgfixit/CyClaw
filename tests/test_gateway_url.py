"""The browser destination must match the gateway's effective listener."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from utils.gateway_url import gateway_url


@pytest.mark.parametrize(
    ("api", "override", "environment", "expected"),
    [
        ({}, None, None, "http://127.0.0.1:8787"),
        ({"host": "127.0.0.2", "port": 8799}, None, None, "http://127.0.0.2:8799"),
        ({"host": "localhost", "tls": {"enabled": True}}, None, "8999", "https://localhost:8999"),
        ({"host": "::1"}, None, None, "http://[::1]:8787"),
        ({"host": "0.0.0.0"}, None, None, "http://127.0.0.1:8787"),  # noqa: S104 - no socket opened
        ({"host": "::"}, None, None, "http://[::1]:8787"),
        ({"host": ""}, None, None, "http://127.0.0.1:8787"),
        ({"port": 8799}, "9000", "8999", "http://127.0.0.1:9000"),
        ({"port": 8799}, None, " ", "http://127.0.0.1:8799"),
        ({"port": "8799", "tls": {"enabled": "true"}}, None, None, "http://127.0.0.1:8787"),
        ({"host": "10.0.0.112", "tls": {"enabled": True}}, None, None, "https://10.0.0.112:8787"),
    ],
)
def test_gateway_url(api, override, environment, expected, monkeypatch) -> None:
    monkeypatch.delenv("CYCLAW_GATE_PORT", raising=False)
    if environment is not None:
        monkeypatch.setenv("CYCLAW_GATE_PORT", environment)
    assert gateway_url({"api": api}, override) == expected


@pytest.mark.parametrize("port", ["not-a-port", "0", "65536", "-1"])
def test_gateway_url_rejects_invalid_port_override(port) -> None:
    with pytest.raises(ValueError):
        gateway_url({}, port)


def test_gateway_url_cli_works_outside_checkout(tmp_path: Path) -> None:
    config = tmp_path / "operator config.yaml"
    config.write_text('api:\n  host: 127.0.0.2\n  port: 8999\n  tls:\n    enabled: true\n', encoding="utf-8")
    helper = Path(__file__).resolve().parents[1] / "utils" / "gateway_url.py"
    result = subprocess.run(
        [sys.executable, str(helper), str(config), "--port", "9000"],
        cwd=tmp_path, env={**os.environ, "CYCLAW_GATE_PORT": "8000"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://127.0.0.2:9000"
