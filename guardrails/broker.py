"""NeMo ``check()`` around the existing CyClaw generation helper.

Phase 3 of issue #1134: NVIDIA's non-generating ``LLMRails.check`` wraps
``client.generate``. This module never grants I3 and never calls
``generate_async``. Graph sees it only via ``utils/guardrail_bridge``.

Not a tool broker. No tool name-gate ships: ``utils/tool_broker.py`` was
removed once its only caller, the harness console, went away (PR #1367).
"""

from __future__ import annotations

import logging
from typing import Any

from guardrails.config import GuardrailsConfig
from guardrails.integration import check_input, check_output, get_cyclaw_guardrails
from guardrails.metrics import GuardrailMetrics
from guardrails.rails import GROUNDING_SCOPE_KEY
from utils.errors import RAGError

logger = logging.getLogger("cyclaw.guardrails.broker")


_KNOWN_FLOWS = frozenset({
    "check soul mutation", "check injection", "check cyclaw jailbreak",
    "handle identity question", "block prompt extraction", "check grounding",
    "check soul leak", "check cyclaw facts", "stay in local knowledge",
    "no unauthed external advice",
})


def _status_name(result: object) -> str | None:
    status = getattr(result, "status", None)
    name = getattr(status, "name", status)
    return name.upper() if isinstance(name, str) else None


def _status_blocked(result: object) -> bool:
    return _status_name(result) == "BLOCKED"


def _blocking_rail(result: object) -> str:
    rail = getattr(result, "rail", None)
    return f"nemo_check:{rail}" if isinstance(rail, str) and rail in _KNOWN_FLOWS else "nemo_check"


def _live_check(rails: object, messages: list[dict[str, Any]], *, input_only: bool = False) -> object | None:
    """Invoke the pinned NeMo check signature once; a failure may have side effects."""
    check = getattr(rails, "check", None)
    if not callable(check):
        return None
    kwargs: dict[str, object] = {"messages": messages}
    if input_only:
        from nemoguardrails.rails.llm.options import RailType

        kwargs["rail_types"] = [RailType.INPUT]
    return check(**kwargs)


class GuardrailBroker:
    """Own live checks and deterministic fallback around one generation."""

    def __init__(self, cfg: GuardrailsConfig, metrics: GuardrailMetrics) -> None:
        self.cfg = cfg
        self.metrics = metrics
        self._rails: object | None = None
        self._engine_attempted = False
        self.blocked_rail: str | None = None
        self.blocked_rails: list[str] = []
        self.degraded = False

    def _mark_degraded(self, reason: str, *, query: str = "") -> None:
        logger.warning("NeMo check degraded (%s)", reason)
        self.metrics.record_skipped(reason=reason, query=query)
        self.degraded = True

    def _engine(self) -> object | None:
        if self._rails is not None or self._engine_attempted:
            return self._rails
        self._engine_attempted = True
        try:
            self._rails = get_cyclaw_guardrails(self.cfg)
        except Exception:
            self._mark_degraded("engine_error")
        return self._rails

    def check_user(self, query: str) -> bool:
        """Run the offline input floor whenever the live verdict is unavailable."""
        try:
            rails = self._engine()
            result = _live_check(rails, [{"role": "user", "content": query}], input_only=True)
            if _status_name(result) not in {"PASSED", "BLOCKED"}:
                self._mark_degraded("check_input_unavailable", query=query)
            elif _status_blocked(result):
                self.blocked_rail = _blocking_rail(result)
                self.blocked_rails = [self.blocked_rail]
                self.metrics.record_blocked(stage="input", rail=self.blocked_rail, reason="blocked", query=query)
                return True
            else:
                return False
        except Exception:
            self._mark_degraded("check_input_error", query=query)
        fallback = check_input(query, cfg=self.cfg, metrics=self.metrics)
        self.blocked_rails = fallback["rails"]
        self.blocked_rail = next(iter(self.blocked_rails), None)
        return fallback["blocked"]

    def check_assistant(self, query: str, answer: str, *, grounding_context: str | None) -> bool:
        """Fallback keeps soul-leak protection; None excludes only grounding."""
        if grounding_context is None:
            context: dict[str, object] = {GROUNDING_SCOPE_KEY: False}
        else:
            context = {"relevant_chunks": grounding_context, GROUNDING_SCOPE_KEY: True}
        try:
            rails = self._engine()
            result = _live_check(rails, [
                {"role": "context", "content": context},
                {"role": "user", "content": query},
                {"role": "assistant", "content": answer},
            ])
            if _status_name(result) not in {"PASSED", "BLOCKED"}:
                self._mark_degraded("check_output_unavailable", query=query)
            elif _status_blocked(result):
                self.blocked_rail = _blocking_rail(result)
                self.blocked_rails = [self.blocked_rail]
                self.metrics.record_blocked(stage="output", rail=self.blocked_rail, reason="blocked", query=query)
                return True
            else:
                return False
        except Exception:
            self._mark_degraded("check_output_error", query=query)
        fallback = check_output(answer, grounding_context, query=query, cfg=self.cfg, metrics=self.metrics)
        self.blocked_rails = fallback["rails"]
        self.blocked_rail = next(iter(self.blocked_rails), None)
        return fallback["blocked"]


def guarded_generate(
    client: Any,
    prompt: str,
    *,
    query: str,
    label: str,
    spend_context: dict[str, object] | None,
    cfg: GuardrailsConfig,
    metrics: GuardrailMetrics,
    grounding_context: str | None = None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Input ``check()`` → existing ``client.generate`` → output ``check()``.

    Returns ``(answer, error, block)``. ``block`` is None when every check
    ran and passed. When a check refused, the answer is the block message
    and ``block`` is ``{"stage": "input" | "output", "rails": [...]}``: an
    input refusal means the model never ran, an output refusal replaced its
    answer. When a check could not run (no engine, or ``check()`` raised) and
    none refused, ``block`` is ``{"stage": "degraded", "rails": []}``: the
    answer passed the deterministic fallback checks. A refusal also includes
    ``degraded=True`` when a live check was unavailable. The graph records
    both facts. ``grounding_context`` is passed to
    :meth:`GuardrailBroker.check_assistant`.
    """
    broker = GuardrailBroker(cfg, metrics)
    degraded: dict[str, Any] = {"stage": "degraded", "rails": []}
    if broker.check_user(query or prompt):
        return cfg.block_message, None, {
            "stage": "input", "rails": broker.blocked_rails,
            **({"degraded": True} if broker.degraded else {}),
        }
    try:
        if spend_context is None:
            answer = client.generate(prompt)
        else:
            answer = client.generate(prompt, spend_context=spend_context)
    except RAGError as exc:
        return "", f"{exc.code}: {exc.message}", degraded if broker.degraded else None
    if broker.check_assistant(query or prompt, answer, grounding_context=grounding_context):
        return cfg.block_message, None, {
            "stage": "output", "rails": broker.blocked_rails,
            **({"degraded": True} if broker.degraded else {}),
        }
    return answer, None, degraded if broker.degraded else None
