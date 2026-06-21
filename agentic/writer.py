"""GitHub WRITE scaffold for the agentic layer -- DISABLED and STUBBED in v0.1.

This module deliberately CANNOT mutate GitHub state. It exists to (a) document
the exact gate a future write capability must pass, and (b) let tests prove that
the gate refuses every under-satisfied request. Wiring real execution is a
separate, individually-reviewed change behind the same gate.

The gate is the out-of-band analogue of CyClaw's "Triple-Gated External Access"
invariant for the Grok path. A write *plan* is produced only when ALL of:

    1. cfg.mode == "write"            (operator put the layer in write mode)
    2. cfg.writes_enabled is True     (explicit second flag, defaults False)
    3. a non-empty human ``reason``   (governance: no anonymous mutations)
    4. confirm is True                (explicit per-call confirmation)

are satisfied simultaneously. Even then, ``plan_write`` returns a DRY-RUN plan
(the argv it *would* run) and never executes it -- ``EXECUTION_ENABLED`` is a
hard ``False`` and the one place that would execute raises ``NotImplementedError``.
Any gate failure raises ``AgenticWriteRefused`` and is audited.
"""

from __future__ import annotations

from agentic.config import AgenticConfig
from utils.errors import AgenticError, AgenticWriteRefused
from utils.logger import audit_log

# HARD KILL SWITCH. v0.1 never executes a write. Flipping this to True is NOT
# sufficient to enable writes -- the executor below is intentionally unimplemented
# so that a future enablement is a deliberate, reviewed code change, not a flag.
EXECUTION_ENABLED = False

# Write ops the planner knows how to *describe* (not execute).
_WRITE_OPS = frozenset({"pr_comment", "issue_comment", "pr_create"})


def _build_write_argv(op: str, repo: str, params: dict, gh_bin: str = "gh") -> list[str]:
    """Build the argv a write WOULD use, for display in the dry-run plan only."""
    if op == "pr_comment":
        return [gh_bin, "pr", "comment", str(int(params["number"])),
                "--repo", repo, "--body", str(params["body"])]
    if op == "issue_comment":
        return [gh_bin, "issue", "comment", str(int(params["number"])),
                "--repo", repo, "--body", str(params["body"])]
    if op == "pr_create":
        return [gh_bin, "pr", "create", "--repo", repo,
                "--title", str(params["title"]), "--body", str(params["body"]),
                "--draft"]
    raise AgenticError(f"Unknown write op: {op!r}", details={"op": op, "allowed": sorted(_WRITE_OPS)})


def _refuse(reason_msg: str, *, op: str, gate: str, reason: str) -> AgenticWriteRefused:
    audit_log({
        "event": "agentic_write_refused",
        "op": op,
        "gate": gate,
        "reason": reason or "",
    })
    return AgenticWriteRefused(reason_msg, details={"op": op, "failed_gate": gate})


def plan_write(
    cfg: AgenticConfig,
    op: str,
    reason: str,
    *,
    confirm: bool = False,
    gh_bin: str = "gh",
    **params: object,
) -> dict:
    """Validate the write gate and return a DRY-RUN plan. Never executes.

    Raises ``AgenticWriteRefused`` if any gate fails, ``AgenticError`` for an
    unknown op. On full gate satisfaction returns a dict describing the argv that
    a (future) executor would run -- but nothing is executed in v0.1.
    """
    if op not in _WRITE_OPS:
        raise AgenticError(
            f"Unknown write op: {op!r}",
            details={"op": op, "allowed": sorted(_WRITE_OPS)},
        )

    # Gate 1: write mode.
    if not cfg.is_write_mode:
        raise _refuse("agentic.mode is not 'write'", op=op, gate="mode", reason=reason)
    # Gate 2: explicit writes_enabled flag.
    if not cfg.writes_enabled:
        raise _refuse("agentic.writes_enabled is False", op=op, gate="writes_enabled", reason=reason)
    # Gate 3: human reason string.
    if not (isinstance(reason, str) and reason.strip()):
        raise _refuse("a non-empty human reason is required", op=op, gate="reason", reason=reason)
    # Gate 4: per-call confirmation.
    if confirm is not True:
        raise _refuse("explicit confirm=True is required", op=op, gate="confirm", reason=reason)

    # All gates satisfied -- still a dry run in v0.1.
    argv = _build_write_argv(op, cfg.repo, dict(params), gh_bin=gh_bin)
    plan = {
        "status": "dry_run_plan",
        "op": op,
        "repo": cfg.repo,
        "reason": reason,
        "would_run": argv,
        "executed": False,
        "note": "v0.1 never executes writes; EXECUTION_ENABLED is False.",
    }
    audit_log({
        "event": "agentic_write_dryrun",
        "op": op,
        "repo": cfg.repo,
        "reason": reason,
    })
    return plan


def execute_write(plan: dict) -> dict:  # pragma: no cover - intentionally unreachable in v0.1
    """Placeholder executor. Intentionally not implemented in v0.1.

    Enabling real writes is a deliberate future change: implement this behind the
    same gate, add explicit tests, and only then consider flipping
    ``EXECUTION_ENABLED``. Until then this refuses loudly.
    """
    raise NotImplementedError(
        "Agentic write execution is intentionally disabled in v0.1. "
        "plan_write() only produces dry-run plans."
    )


__all__ = ["EXECUTION_ENABLED", "plan_write", "execute_write"]
