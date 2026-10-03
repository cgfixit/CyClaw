"""Typed error hierarchy for the out-of-band NeMo guardrails layer.

Rooted at :class:`utils.errors.RAGError`, with guardrail-specific errors kept
in this out-of-band package. Core callers use the maintained bridge.

This module is part of a package that is NEVER imported by ``gate.py``,
``graph.py``, or ``mcp_hybrid_server.py`` -- that isolation is what preserves
CyClaw's six security invariants by construction.
"""

from __future__ import annotations

from utils.errors import RAGError


class GuardrailsError(RAGError):
    """Base error for the out-of-band NeMo guardrails layer.

    Mirrors the ``SyncError`` / ``AgenticError`` convention: a dedicated
    hierarchy for a strictly out-of-band feature, so the gateway can stay
    oblivious to it.
    """

    def __init__(self, message: str, code: str = "GUARDRAILS_ERROR", details: dict | None = None) -> None:
        super().__init__(message, code=code, details=details)


class GuardrailsConfigError(GuardrailsError):
    """The ``guardrails:`` block in config.yaml is invalid."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code="GUARDRAILS_CONFIG_INVALID", details=details)


class GuardrailsDependencyError(GuardrailsError):
    """The required ``nemoguardrails`` dependency is not importable.

    The enabled layer retains deterministic checks without it (see
    ``guardrails.integration``); this is raised only when a caller explicitly
    asks for a live NeMo rails engine that cannot be constructed.
    """

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code="GUARDRAILS_DEPENDENCY_MISSING", details=details)


class RailsLoadError(GuardrailsError):
    """The NeMo ``RailsConfig`` directory could not be loaded or compiled."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code="GUARDRAILS_RAILS_LOAD_FAILED", details=details)
