"""Sandboxed verification executor for the agentic coding harness.

This is the production-grade gate the audit named as the biggest engineering
gap: something that can actually run ``pytest``/``ruff``/the invariant guard
over a working tree, rather than the ``in``-substring scoring
``harness_optimizer``'s fixture runner uses today.

Read ``docs/THREAT_MODEL.md`` sections 4-6 before wiring this into anything
live -- this package is the one that requires the amendment recorded there:
adding code execution to a layer previously documented as "deliberately
non-executing" is a real, named change to the threat model, not a detail.

Never imported by ``gate.py``/``graph.py``/``mcp_hybrid_server.py`` (I6).
Its callers are the operator-run, CLI-only real-repo path:
``agentic/real_repo_loop.py`` runs ``run_verification`` and the manifest
checks, and ``agentic/cli.py`` builds ``Check`` objects from the operator's
required checks manifest. Both ship gated off (``agentic.enabled: false``),
and no HTTP route reaches either.
"""

from __future__ import annotations

from agentic.executor.hard_sandbox import HardSandboxUnavailable, production_sandbox
from agentic.executor.runner import (
    Check,
    CheckResult,
    VerificationReport,
    run_verification,
)

__all__ = [
    "Check",
    "CheckResult",
    "HardSandboxUnavailable",
    "VerificationReport",
    "production_sandbox",
    "run_verification",
]
