"""Typed error hierarchy for the out-of-band NeMo guardrails layer.

Rooted at :class:`utils.errors.RAGError` for consistency with the rest of the
codebase, but defined *here* rather than in ``utils/errors.py`` so the existing
error module stays untouched while this layer is still an early skeleton. Once
the guardrails layer graduates from skeleton status these can be promoted into
``utils/errors.py`` alongside ``SyncError`` / ``AgenticError``.

This module is part of a package that is NEVER imported by ``gate.py``,
``graph.py``, or ``mcp_hybrid_server.py`` -- that isolation is what preserves
CyClaw's five security invariants by construction.
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
    """The ``guardrails:`` block in config.yaml is missing or invalid."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code="GUARDRAILS_CONFIG_INVALID", details=details)


class GuardrailsDependencyError(GuardrailsError):
    """The optional ``nemoguardrails`` dependency is not importable.

    The skeleton is designed to degrade gracefully without it (see
    ``guardrails.integration``); this is raised only when a caller explicitly
    asks for a live NeMo rails engine that cannot be constructed.
    """

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code="GUARDRAILS_DEPENDENCY_MISSING", details=details)


class RailsLoadError(GuardrailsError):
    """The NeMo ``RailsConfig`` directory could not be loaded or compiled."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code="GUARDRAILS_RAILS_LOAD_FAILED", details=details)
