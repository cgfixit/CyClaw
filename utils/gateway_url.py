"""Resolve gateway ports and browser URLs without importing or starting the gateway."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import yaml


def resolve_port(api: dict[str, Any], override: str | None = None) -> int:
    """Use a nonblank environment/launcher override, then config, then 8787."""
    text = override.strip() if override is not None else ""
    if text:
        try:
            if not text.isascii() or not text.isdecimal():
                raise ValueError
            port = int(text)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise ValueError(f"CYCLAW_GATE_PORT / --port must be an integer 1..65535 (got {override!r})") from None
        return port
    port = api.get("port", 8787)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"api.port must be an unquoted integer 1..65535 (got {port!r})")
    return port


def read_gate_port(config_path: Path) -> int:
    """Validate service config without inheriting the generating shell's port."""
    try:
        with config_path.open(encoding="utf-8") as stream:
            cfg = yaml.safe_load(stream) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read {config_path}: {exc}") from exc
    api = cfg.get("api") if isinstance(cfg, dict) else None
    return resolve_port(api if isinstance(api, dict) else {})


def gateway_url(cfg: dict[str, Any], port_override: str | None = None) -> str:
    api = cfg.get("api") if isinstance(cfg.get("api"), dict) else {}
    tls = api.get("tls") if isinstance(api.get("tls"), dict) else {}
    scheme = "https" if tls.get("enabled") is True else "http"
    host = api.get("host", "127.0.0.1")
    # Wildcard bind addresses are not browser destinations.
    host = {"": "127.0.0.1", "0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)  # nosec B104 # noqa: S104 - URL only; no bind
    if ":" in host:
        host = f"[{host}]"

    # macOS callers pass their flag/default explicitly.
    raw = port_override if port_override is not None else os.environ.get("CYCLAW_GATE_PORT")
    port = resolve_port(api, raw)
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
