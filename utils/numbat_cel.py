"""CEL sanitizer backend for Numbat-shaped structured-field rules.

Optional, default-off, and monitor-only.  Rules evaluate over safe,
already-hashed/structured request fields (never raw prompt text) and emit a
low-confidence Numbat event on match.  They do NOT block ``/query``; the regex
banned_patterns list remains the fail-closed baseline.

A match is projected as ``tool.result`` from ``tool_name: "cel_monitor"`` with
``decision: "allowed"``, because the request was allowed: nothing here can
deny it.  It used to be ``permission.denied`` with ``decision: "denied"``,
which recorded a block that never happened and could satisfy the first step
of Numbat sequence rules keyed on denials, such as the shipped
``chain.permission_denied_then_runtime_bypass`` (issue #1458 Phase 3).

The ``cel-python`` import is lazy and guarded by ``numbat.cel.enabled``.  When
disabled, this module never imports the optional dependency, so the core
request path stays free of it (I6 hygiene).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger("cyclaw.numbat_cel")

DEFAULT_MAX_RULE_MS = 20.0

# Same shape as utils/external_pre_hook.py's _QUERY_HASH_RE: only a real
# SHA-256 hex digest may ride in the emitted preview.
_QUERY_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

# answer_model role (graph.py's GraphState vocabulary) -> Numbat model_provider.
# The two local roles resolve to the configured local provider at call time.
_ROLE_PROVIDERS = {"grok": "xai", "claude": "anthropic"}
_LOCAL_ROLES = frozenset({"local", "offline-best-effort"})


def model_provider_for_role(answer_model: str | None, cfg: dict[str, Any] | None = None) -> str:
    """Map an answer_model role to the provider that produced the answer.

    Returns ``""`` for roles where no model ran ("hook-denied",
    "guardrail-blocked", "external-unavailable", the empty user-gate pause).
    gate.py's old prefix check answered "ollama" for all of those, so a CEL
    rule such as ``model_provider == "ollama"`` matched requests no local model
    ever touched.
    """
    role = answer_model or ""
    if role in _ROLE_PROVIDERS:
        return _ROLE_PROVIDERS[role]
    if role in _LOCAL_ROLES:
        models = cfg.get("models") if isinstance(cfg, dict) else None
        local = models.get("local_llm") if isinstance(models, dict) else None
        provider = local.get("provider") if isinstance(local, dict) else None
        return provider if isinstance(provider, str) and provider else "ollama"
    return ""


def _cel_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        return {}
    numbat = cfg.get("numbat")
    block = numbat.get("cel") if isinstance(numbat, dict) else None
    return block if isinstance(block, dict) else {}


def _is_literal_true(value: Any) -> bool:
    return value is True


def _compile_rules(rules: list[Any]) -> list[tuple[int, Any]]:
    """Compile CEL expression strings; skip bad rules with a warning."""
    try:
        import celpy
    except Exception as exc:  # noqa: BLE001 - fail-open: missing optional dep
        logger.warning("cel-python is not installed: %s", exc)
        return []

    env = celpy.Environment()
    compiled: list[tuple[int, Any]] = []
    for idx, expr in enumerate(rules):
        if not isinstance(expr, str) or not expr:
            logger.warning("numbat.cel.rules[%d] is not a string; skipping", idx)
            continue
        try:
            ast = env.compile(expr)
            compiled.append((idx, env.program(ast)))
        except Exception as exc:  # noqa: BLE001 - one bad rule must not break others
            logger.warning("numbat.cel.rules[%d] failed to compile: %s", idx, exc)
    return compiled


def cel_readiness(cfg: dict[str, Any] | None) -> tuple[bool, str | None] | None:
    """Report enabled evaluator availability and compilation of every rule.

    Does not evaluate synthetic inputs: valid rules can depend on populated
    request fields. Runtime evaluation and asynchronous alert delivery are
    separate; disabling the Numbat projection does not disable this evaluator.
    """
    block = _cel_cfg(cfg)
    if block.get("enabled") is not True:
        return None
    rules = block.get("rules")
    if not isinstance(rules, list) or not rules:
        return False, "CEL rules are empty or invalid"
    try:
        import celpy  # noqa: F401 - distinguish missing dependency from bad rules
    except Exception:
        return False, "CEL dependency unavailable"
    try:
        compiled = _compile_rules(rules)
    except Exception:
        return False, "CEL rule compilation failed"
    if len(compiled) != len(rules):
        return False, "CEL rule compilation failed"
    return True, None


def _max_rule_ms(raw: Any) -> float:
    """numbat.cel.max_rule_ms as a positive number; anything else is the default.

    The budget only decides when to log a slow rule, but a string or null from
    YAML (``max_rule_ms: "20"``) used to reach the ``elapsed_ms > max_ms``
    compare, which sits outside the per-rule guard, and raise TypeError out of
    this never-raise function. gate.py's outer guard kept ``/query`` alive,
    but the monitor then did nothing on any request.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        return DEFAULT_MAX_RULE_MS
    return float(raw)


def _build_activation(fields: dict[str, Any]) -> dict[str, Any]:
    """Convert plain Python values to CEL-friendly values when possible."""
    try:
        import celpy

        return {k: celpy.json_to_cel(v) for k, v in fields.items()}
    except Exception:  # noqa: BLE001 - degrade to native values
        return fields


def evaluate_cel_monitor(
    *,
    query_hash: str | None = None,
    top_score: float | None = None,
    answer_model: str | None = None,
    guardrail_blocked: bool | None = None,
    guardrail_rails: list[str] | None = None,
    model_provider: str | None = None,
    source_hashes: list[str] | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[int]:
    """Evaluate enabled CEL rules over structured fields.

    Returns a list of matched rule indices.  Never raises: a disabled config,
    missing optional dependency, or bad rule results in an empty list so the
    request path cannot be derailed by a policy-engine problem.
    """
    block = _cel_cfg(cfg)
    if not _is_literal_true(block.get("enabled", False)):
        return []

    rules = block.get("rules") or []
    if not isinstance(rules, list) or not rules:
        return []

    compiled = _compile_rules(rules)
    if not compiled:
        return []

    fields: dict[str, Any] = {
        "query_hash": query_hash or "",
        "top_score": top_score if top_score is not None else 0.0,
        "answer_model": answer_model or "",
        "guardrail_blocked": bool(guardrail_blocked),
        "guardrail_rails": list(guardrail_rails or []),
        "model_provider": model_provider or "",
        "source_hashes": list(source_hashes or []),
    }
    activation = _build_activation(fields)
    max_ms = _max_rule_ms(block.get("max_rule_ms"))
    matches: list[int] = []

    for idx, prgm in compiled:
        start = time.monotonic()
        try:
            result = prgm.evaluate(activation)
            if bool(result):
                matches.append(idx)
        except Exception as exc:  # noqa: BLE001 - fail-open per rule
            logger.warning("numbat.cel.rules[%d] evaluation failed: %s", idx, exc)
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > max_ms:
            logger.warning(
                "numbat.cel.rules[%d] exceeded %sms budget (%.2fms)",
                idx, max_ms, elapsed_ms,
            )

    return matches


def _match_preview(
    matches: list[int], query_hash: str | None, cfg: dict[str, Any] | None, cap: int,
) -> tuple[str, bool]:
    """JSON preview joining a match back to its query, within ``cap`` characters.

    Returns ``(preview, truncated)``. query_hash goes first because it is the
    only join key to the rag_query record; the matched indices also ride in
    the tags, so they are the part dropped, whole, when a long match list
    would overflow the schema's cap. ``truncated`` reports that drop: the same
    content_preview_truncated contract as the audit projection's packer, so a
    consumer never mistakes the shortened preview for a complete one.
    """
    from utils.logger import include_query_hash  # lazy, like this module's other imports

    preview: dict[str, Any] = {}
    if query_hash and _QUERY_HASH_RE.fullmatch(query_hash) and include_query_hash(cfg):
        preview["query_hash"] = query_hash
    text = json.dumps({**preview, "cel_rules_matched": matches}, separators=(",", ":"))
    if len(text) <= cap:
        return text, False
    return json.dumps(preview, separators=(",", ":")), True


def monitor_request(
    *,
    query_hash: str | None = None,
    top_score: float | None = None,
    answer_model: str | None = None,
    guardrail_blocked: bool | None = None,
    guardrail_rails: list[str] | None = None,
    model_provider: str | None = None,
    source_hashes: list[str] | None = None,
    llm_model: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> None:
    """Monitor-only CEL hook.  Emits a Numbat event on rule match; never blocks.

    ``answer_model`` is the graph's answer ROLE ("local", "grok", ...), which
    the rules see; ``llm_model`` is the concrete model that answered (the
    vendor-resolved served_model when the provider reported one, else the
    configured tag) and is what the event's ``model`` field carries. It is
    omitted when unknown rather than filled with the role.
    """
    matches = evaluate_cel_monitor(
        query_hash=query_hash,
        top_score=top_score,
        answer_model=answer_model,
        guardrail_blocked=guardrail_blocked,
        guardrail_rails=guardrail_rails,
        model_provider=model_provider,
        source_hashes=source_hashes,
        cfg=cfg,
    )
    if not matches:
        return

    try:
        from utils.numbat_emitter import CONTENT_PREVIEW_MAX_CHARS, emit_numbat_event
    except Exception as exc:  # noqa: BLE001 - projection must not fail the caller
        logger.warning("numbat_cel could not load numbat_emitter: %s", exc)
        return

    try:
        content_preview, preview_truncated = _match_preview(matches, query_hash, cfg, CONTENT_PREVIEW_MAX_CHARS)
        emit_numbat_event(
            "tool.result",
            model=llm_model or None,
            model_provider=model_provider or None,
            tool_name="cel_monitor",
            # Monitor-only: the request this describes was allowed.
            decision="allowed",
            actor="system",
            entrypoint="cyclaw",
            tags=["cel_monitor", "monitor_only", f"rules:{','.join(str(i) for i in matches)}"],
            confidence="low",
            content_preview=content_preview,
            content_preview_truncated=preview_truncated,
            artifact_type="cel_monitor",
            cfg=cfg,
        )
    except Exception as exc:  # noqa: BLE001 - derived stream must never fail the caller
        logger.warning("numbat_cel emit failed: %s", exc)
