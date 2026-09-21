"""Resolve a launcher's browser URL without importing or starting the gateway."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import yaml


def gateway_url(cfg: dict[str, Any], port_override: str | None = None) -> str:
    api = cfg.get("api") if isinstance(cfg.get("api"), dict) else {}
    tls = api.get("tls") if isinstance(api.get("tls"), dict) else {}
    scheme = "https" if tls.get("enabled") is True else "http"
    host = api.get("host", "127.0.0.1")
    # Wildcard bind addresses are not browser destinations.
    host = {"": "127.0.0.1", "0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)  # nosec B104 # noqa: S104 - URL only; no bind
    if ":" in host:
        host = f"[{host}]"

    # Match gate._listen_port; macOS callers pass their flag/default explicitly.
    raw = port_override if port_override is not None else os.environ.get("CYCLAW_GATE_PORT")
    if raw is None or not raw.strip():
        configured = api.get("port", 8787)
        port = int(configured) if isinstance(configured, int) else 8787
    else:
        if not raw.strip().isdigit():
            raise ValueError("gateway port must be an integer")
        port = int(raw.strip())
    if not 1 <= port <= 65535:
        raise ValueError("gateway port must be between 1 and 65535")
    return f"{scheme}://{host}:{port}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--port", help="Explicit launcher port; overrides environment and config")
    args = parser.parse_args()
    with args.config.open(encoding="utf-8") as stream:
        cfg = yaml.safe_load(stream) or {}
    print(gateway_url(cfg, args.port))


if __name__ == "__main__":
    main()
