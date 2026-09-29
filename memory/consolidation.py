"""Consolidation stub — never auto-runs in v1."""

from __future__ import annotations

from typing import Any


def run_consolidation(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return disabled regardless of configuration; v1 never consolidates."""
    return {"status": "disabled", "reason": "consolidation not implemented"}
