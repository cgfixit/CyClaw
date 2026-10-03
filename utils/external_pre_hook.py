"""Synchronous pre-action hook runner for external LLM fallbacks.

CyClaw runs this checkpoint before any call to Grok or Claude, after the I3
triple gate has already allowed it; it can only take calls away. Two engines
decide, selected by ``policy.fallback.pre_action_hook.engine``:

* ``command`` (default): the configured argv receives a JSON payload on stdin
  (``action``, ``provider``, ``model``, ``query_hash``) and answers by exit
  code -- exit 0 allows, exit 2 denies, and any other exit, crash, or timeout
  fails closed (deny + audit).
* ``numbat``: ``utils.numbat_gate`` has the pinned Numbat CLI evaluate the
  proposed call against operator rules; a match of an ``enforce: true`` rule
  denies, and every engine failure denies. ``numbat hook ...`` itself is no
  substitute as the ``command``: it cannot see the provider or URL, and it
  exits 0 on errors (see utils/numbat_gate.py for the verified behavior).

Every verdict carries a ``reason_code`` from a fixed vocabulary
(``REASON_CODES``). graph.py stamps it on the audit record as
``pre_action_hook_reason``, cyclaw-metrics counts it, and with
``emit_verdict`` on it is projected into the Numbat stream.

This module is intentionally isolated from the request path's optional layers:
it does not import agentic, sync, guardrails, harness, telegram, or opentweet,
and it reaches utils.numbat_emitter and utils.numbat_gate only through lazy,
call-time imports.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess  # nosec B404 - list-form only, no shell, operator-configured argv
import threading
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("cyclaw.external_pre_hook")

# Same shape as utils/spend.py's _QUERY_HASH_RE (kept separate on purpose --
# only 2 call sites, not worth a shared helper).
_QUERY_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_TIMEOUT_SEC = 5
MIN_TIMEOUT_SEC = 1
MAX_TIMEOUT_SEC = 30

ENGINES = ("command", "numbat")
# The only verdict mode that exists: a deny blocks. "monitor" (log a deny but
# let the call through) loosens an I3 safeguard and must not ship until a
# separate dual-run observation issue is filed. A rule-level trial is already
# available without it: a Numbat rule without enforce: true only reports.
VERDICT_MODES = ("enforce",)

# hook_allowed is the one allow code; every other code is a deny.
REASON_CODES = (
    "hook_allowed",
    "hook_denied",
    "hook_timeout",
    "hook_error",
    "hook_failure",
    "hook_misconfigured",
)

# Only the literal Python True arms the hook / emission. A YAML string such as
# "false" or "true" must not be treated as a security-enabling boolean.


def _is_literal_true(value: Any) -> bool:
    return value is True


# Provider string -> Numbat-friendly model_provider value. Keep in sync with
# utils/numbat_emitter._AUDIT_MODEL_PROVIDERS where possible.
_PROVIDER_TO_VENDOR = {
    "grok": "xai",
    "claude": "anthropic",
}


def _hook_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Return the policy.fallback.pre_action_hook block, if any."""
    if not isinstance(cfg, dict):
        return {}
    policy = cfg.get("policy", {})
    fallback = policy.get("fallback", {}) if isinstance(policy, dict) else {}
    if not isinstance(fallback, dict):
        return {}
    block = fallback.get("pre_action_hook", {})
    return block if isinstance(block, dict) else {}


def _normalize_timeout(raw: Any) -> int:
    """Coerce timeout to an integer inside [1, 30]; default to 5 on bad input."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SEC
    if value < MIN_TIMEOUT_SEC:
        return MIN_TIMEOUT_SEC
    if value > MAX_TIMEOUT_SEC:
        return MAX_TIMEOUT_SEC
    return value


def verdict_mode(block: dict[str, Any]) -> str:
    """The configured verdict mode; anything but "enforce" warns and enforces.

    ``verdict_mode`` is the key. ``fail_mode`` is its old name, still read when
    ``verdict_mode`` is absent: it never chose what happens when the hook
    fails (that is always fail-closed), only whether a deny blocks, which the
    #1453 review showed the old name hid. Boot validation rejects any other
    value outright; this runtime guard covers configs that skip validation.
    """
    raw = block.get("verdict_mode", block.get("fail_mode", "enforce"))
    if raw not in VERDICT_MODES:
        logger.warning("pre_action_hook verdict_mode=%r is not supported; using enforce", raw)
    return "enforce"


def _engine(block: dict[str, Any]) -> str | None:
    raw = block.get("engine", "command")
    return raw if raw in ENGINES else None


def _deny(reason_code: str, reason: str) -> dict[str, Any]:
    return {"verdict": "deny", "reason_code": reason_code, "reason": reason}


def _run_command(block: dict[str, Any], provider: str, model: str, query_hash: str, timeout: int) -> dict[str, Any]:
    """The ``command`` engine: operator argv, JSON on stdin, exit-code verdict."""
    command = block.get("command")
    if not command:
        # Enabled with nothing to run used to ALLOW every call, silently: a
        # control the operator turned on that did nothing. Fail closed like
        # every other misconfiguration (#1458 Phase 1).
        logger.warning("pre_action_hook is enabled with an empty command; denying")
        return _deny("hook_misconfigured", "pre_action_hook is enabled but command is empty")
    if not isinstance(command, list) or not all(isinstance(c, str) for c in command):
        logger.warning("pre_action_hook command is not a list of strings; denying")
        return _deny("hook_misconfigured", "invalid hook command configuration")

    payload = {
        "action": "external_llm_call",
        "provider": provider,
        "model": model,
        "query_hash": query_hash,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    try:
        proc = subprocess.run(  # noqa: S603  # nosec B603 - list-form, no shell, operator-configured argv
            command,
            input=payload_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("pre_action_hook timed out after %ss; denying", timeout)
        return _deny("hook_timeout", f"hook timed out after {timeout}s")
    except (OSError, ValueError) as exc:
        logger.warning("pre_action_hook failed to run: %s; denying", exc)
        return _deny("hook_error", f"hook execution failed: {exc}")

    if proc.returncode == 0:
        return {"verdict": "allow", "reason_code": "hook_allowed", "reason": "hook exited 0"}

    if proc.returncode == 2:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip() if proc.stderr else ""
        reason = stderr_text or "hook returned exit code 2 (deny)"
        logger.warning("pre_action_hook denied %s: %s", provider, reason)
        return _deny("hook_denied", reason)

    # Any other non-zero exit is treated as a failure and fails closed.
    stdout_text = proc.stdout.decode("utf-8", errors="replace").strip() if proc.stdout else ""
    stderr_text = proc.stderr.decode("utf-8", errors="replace").strip() if proc.stderr else ""
    detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
    logger.warning("pre_action_hook failed for %s: %s; denying", provider, detail)
    return _deny("hook_failure", f"hook failure: {detail}")


def _run_numbat(provider: str, model: str, query_hash: str, cfg: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    """The ``numbat`` engine, imported only when selected."""
    try:
        from utils.numbat_gate import evaluate
    except Exception as exc:  # noqa: BLE001 - a missing engine must deny, not allow
        logger.warning("pre_action_hook could not load the numbat engine: %s; denying", exc)
        return _deny("hook_error", "numbat engine unavailable")
    result = evaluate(provider, model, query_hash, cfg, timeout=timeout)
    if result.get("verdict") != "allow":
        logger.warning("pre_action_hook (numbat) denied %s: %s", provider, result.get("reason"))
    return result


def _provider_url(provider: str, cfg: dict[str, Any] | None) -> str | None:
    models = cfg.get("models") if isinstance(cfg, dict) else None
    section = models.get(provider) if isinstance(models, dict) else None
    url = section.get("base_url") if isinstance(section, dict) else None
    return url if isinstance(url, str) and url else None


def _emit_hook_verdict(
    *,
    provider: str,
    model: str,
    query_hash: str,
    result: dict[str, Any],
    engine: str,
    cfg: dict[str, Any] | None,
) -> None:
    """Project a hook verdict into the Numbat stream, fail-soft.

    One event per decided call (#1458 Phase 2): an allow is a
    ``network.indicator`` with ``decision: "allowed"`` and the provider URL --
    the egress about to happen; a policy deny (``hook_denied``) is a
    ``permission.denied``; a deny because the hook itself broke is a
    low-confidence ``network.indicator`` with ``decision: "denied"``.

    Lazy-imports utils.numbat_emitter so this module stays free of a module-
    scope emitter import (I6 hygiene) and so a projection failure cannot change
    the hook's graph verdict.
    """
    try:
        from utils.logger import include_query_hash
        from utils.numbat_emitter import emit_numbat_event, redact_url_for_numbat
    except Exception as exc:  # noqa: BLE001 - projection must not break the hook
        logger.warning("pre_action_hook could not load numbat_emitter: %s", exc)
        return

    try:
        reason_code = str(result.get("reason_code") or "hook_failure")
        allowed = result.get("verdict") == "allow"
        policy_deny = reason_code == "hook_denied"
        # Schema 0.3.0 has additionalProperties:false and no query_hash
        # property, so the hash rides inside content_preview -- the same
        # contract as the mainline audit projection. Gated the same way too:
        # a hash that is not 64-hex, OR logging.audit_fields.include_query_hash
        # is false, is dropped (no content_preview) rather than emitted.
        content_preview = None
        if include_query_hash(cfg) and _QUERY_HASH_RE.fullmatch(query_hash):
            content_preview = json.dumps({"query_hash": query_hash}, separators=(",", ":"))
        tags = ["pre_action_hook", reason_code, f"engine:{engine}"]
        tags += [f"monitor_match:{rule}" for rule in result.get("monitor_matches") or []]
        emit_numbat_event(
            "permission.denied" if policy_deny else "network.indicator",
            model=model,
            model_provider=_PROVIDER_TO_VENDOR.get(provider, provider),
            tool_name="external_llm_call",
            decision="allowed" if allowed else "denied",
            url=redact_url_for_numbat(_provider_url(provider, cfg)),
            approval_required=True if policy_deny else None,
            approval_decision="denied" if policy_deny else None,
            approval_reason=reason_code if policy_deny else None,
            actor="system",
            entrypoint="cyclaw",
            tags=tags,
            confidence="high" if allowed or policy_deny else "low",
            content_preview=content_preview,
            artifact_type="pre_action_hook",
            cfg=cfg,
        )
    except Exception as exc:  # noqa: BLE001 - derived stream must never fail the caller
        logger.warning("pre_action_hook numbat emit failed: %s", exc)


# The last decided verdict, for diagnostics only (never an input to routing).
_LAST_VERDICT_LOCK = threading.Lock()
_LAST_VERDICT: dict[str, Any] | None = None


def _record_last_verdict(provider: str, engine: str, result: dict[str, Any]) -> None:
    global _LAST_VERDICT
    with _LAST_VERDICT_LOCK:
        _LAST_VERDICT = {
            "verdict": result.get("verdict"),
            "reason_code": result.get("reason_code"),
            "provider": provider,
            "engine": engine,
            "at": datetime.now(UTC).isoformat(),
        }


def last_verdict() -> dict[str, Any] | None:
    """The most recent decided verdict in this process: codes only, no free text."""
    with _LAST_VERDICT_LOCK:
        return dict(_LAST_VERDICT) if _LAST_VERDICT else None


def run_pre_action_hook(
    provider: str,
    model: str,
    query_hash: str,
    cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run the configured pre-action hook and return a verdict.

    Returns ``{"verdict": "allow"}`` when the hook is disabled (the checkpoint
    is a no-op, so existing deployments are unaffected), otherwise
    ``{"verdict": "allow" | "deny", "reason_code": ..., "reason": ...}``.
    Once enabled, nothing but an explicit allow from the engine allows.
    """
    block = _hook_cfg(cfg)

    if not _is_literal_true(block.get("enabled", False)):
        return {"verdict": "allow"}

    verdict_mode(block)
    timeout = _normalize_timeout(block.get("timeout_sec", DEFAULT_TIMEOUT_SEC))
    emit_verdict = _is_literal_true(block.get("emit_verdict", False))
    engine = _engine(block)

    if engine == "numbat":
        result = _run_numbat(provider, model, query_hash, cfg, timeout)
    elif engine == "command":
        result = _run_command(block, provider, model, query_hash, timeout)
    else:
        logger.warning("pre_action_hook engine=%r is not one of %s; denying", block.get("engine"), ENGINES)
        result = _deny("hook_misconfigured", f"unknown pre_action_hook engine {block.get('engine')!r}")
        engine = "unknown"

    _record_last_verdict(provider, engine, result)
    if emit_verdict:
        # A write can no longer hold the verdict: the stream's writer thread
        # takes it and waits for it at most numbat_emitter._WRITE_WAIT_SEC.
        _emit_hook_verdict(
            provider=provider,
            model=model,
            query_hash=query_hash,
            result=result,
            engine=engine,
            cfg=cfg,
        )
    return result


def hook_readiness(cfg: dict[str, Any] | None) -> tuple[bool, str | None] | None:
    """Whether an enabled hook could decide a call now; None when disabled.

    For /health: never runs the operator's command (it is a policy decision
    and may have side effects), only checks it resolves; the numbat engine
    checks its binary, pinned version, and rules, and runs one probe
    decision within timeout_sec, via utils.numbat_gate. Either way the
    filesystem work runs bounded, one check at a time, and cached
    (utils.numbat_gate.bounded_readiness), since a stalled mount can block
    it. Problems are fixed phrases that name no argv or file contents.
    """
    block = _hook_cfg(cfg)
    if not _is_literal_true(block.get("enabled", False)):
        return None
    engine = _engine(block)
    if engine is None:
        return False, f"unknown engine {block.get('engine')!r}"
    timeout = _normalize_timeout(block.get("timeout_sec", DEFAULT_TIMEOUT_SEC))
    try:
        from utils.numbat_gate import bounded_readiness, readiness
    except Exception:  # noqa: BLE001 - a broken engine import is itself the finding
        return False, "pre-action hook readiness check unavailable"
    if engine == "numbat":
        return readiness(cfg, timeout=timeout)
    command = block.get("command")
    if not command:
        return False, "enabled with an empty command, so every external call is denied"
    if not isinstance(command, list) or not all(isinstance(c, str) for c in command) or not command[0]:
        return False, "command is not a list of strings with a non-empty command[0], so every external call is denied"
    exe = command[0]
    # The budget is the call's own: a call has to find and start command[0]
    # within timeout_sec too.
    return bounded_readiness(("command", exe, os.environ.get("PATH", "")), timeout,
                             lambda: _command_readiness(exe))


def _command_readiness(exe: str) -> tuple[bool, str | None]:
    if os.path.isabs(exe):
        found = os.path.isfile(exe) and os.access(exe, os.X_OK)
    else:
        found = shutil.which(exe) is not None
    if not found:
        return False, "command[0] is not an executable on PATH, so every external call is denied"
    return True, None
