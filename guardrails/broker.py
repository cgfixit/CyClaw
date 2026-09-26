"""NeMo ``check()`` around the existing CyClaw generation helper.

Phase 3 of issue #1134: NVIDIA's non-generating ``LLMRails.check`` wraps
``client.generate``. This module never grants I3 and never calls
``generate_async``. Graph sees it only via ``utils/guardrail_bridge``.

Not a tool broker. Tool name-gating is ``utils.tool_broker``
(re-exported as ``guardrails.tool_broker``).
"""

from __future__ import annotations

import logging
from typing import Any

from guardrails.config import GuardrailsConfig
from guardrails.errors import GuardrailsDependencyError, RailsLoadError
from guardrails.integration import get_cyclaw_guardrails
from guardrails.metrics import GuardrailMetrics
from guardrails.rails import GROUNDING_SCOPE_KEY
from utils.errors import RAGError

logger = logging.getLogger("cyclaw.guardrails.broker")


def _status_blocked(result: object) -> bool:
    status = getattr(result, "status", None)
    return "BLOCKED" in str(getattr(status, "name", status)).upper()


def _blocking_rail(result: object) -> str:
    """Audit name for the rail that blocked: ``nemo_check:<flow>``.

    NeMo 0.24's ``RailsResult.rail`` names the Colang flow that stopped the
    content; plain ``nemo_check`` when it names none.
    """
    rail = getattr(result, "rail", None)
    return f"nemo_check:{rail}" if isinstance(rail, str) and rail else "nemo_check"


def _live_check(rails: object, messages: list[dict[str, Any]], *, input_only: bool = False) -> object | None:
    """Call NVIDIA ``check(messages=...)``. None on degrade."""
    check = getattr(rails, "check", None)
    if check is None:
        return None
    kwargs: dict[str, object] = {"messages": messages}
    if input_only:
        try:
            from nemoguardrails.rails.llm.options import RailType
        except ImportError:
            RailType = None  # type: ignore[misc, assignment]
        if RailType is not None:
            kwargs["rail_types"] = [RailType.INPUT]
    try:
        return check(**kwargs)
    except TypeError:
        return check(messages)


class GuardrailBroker:
    """Maps NVIDIA ``RailsResult`` to a block/allow decision. Never grants a route."""

    def __init__(self, cfg: GuardrailsConfig, metrics: GuardrailMetrics) -> None:
        self.cfg = cfg
        self.metrics = metrics
        self._rails: object | None = None
        # Set when a check blocks; guarded_generate reads it after a True.
        self.blocked_rail: str | None = None

    def _engine(self) -> object | None:
        if self._rails is not None:
            return self._rails
        try:
            self._rails = get_cyclaw_guardrails(self.cfg)
        except (GuardrailsDependencyError, RailsLoadError) as exc:
            logger.warning("NeMo check engine unavailable (%s); degrade", type(exc).__name__)
            self.metrics.record_skipped(reason=type(exc).__name__)
            return None
        return self._rails

    def check_user(self, query: str) -> bool:
        """True when live input rails BLOCK. False = allow or degrade."""
        rails = self._engine()
        if rails is None:
            return False
        try:
            result = _live_check(rails, [{"role": "user", "content": query}], input_only=True)
        except Exception:
            logger.warning("NeMo check() input failed; degrade", exc_info=True)
            self.metrics.record_skipped(reason="check_input_error", query=query)
            return False
        if result is not None and _status_blocked(result):
            self.blocked_rail = _blocking_rail(result)
            self.metrics.record_blocked(stage="input", rail=self.blocked_rail, reason="blocked", query=query)
            return True
        return False

    def check_assistant(self, query: str, answer: str, *, grounding_context: str | None) -> bool:
        """True when live output rails BLOCK. False = allow or degrade.

        ``grounding_context`` is the retrieved text the model was given, and
        the grounding rail judges the answer against it. None means the answer
        is not held to the vault (a Grok, Claude or offline best-effort
        answer), so grounding stands down and the other output rails still run.
        """
        rails = self._engine()
        if rails is None:
            return False
        # A context-role message is the only way to set NeMo's relevant_chunks
        # (see integration.safe_generate). Without it the grounding rail
        # scored every answer against nothing and blocked it.
        if grounding_context is None:
            context: dict[str, object] = {GROUNDING_SCOPE_KEY: False}
        else:
            context = {"relevant_chunks": grounding_context, GROUNDING_SCOPE_KEY: True}
        try:
            result = _live_check(
                rails,
                [
                    {"role": "context", "content": context},
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": answer},
                ],
            )
        except Exception:
            logger.warning("NeMo check() output failed; degrade", exc_info=True)
            self.metrics.record_skipped(reason="check_output_error", query=query)
            return False
        if result is not None and _status_blocked(result):
            self.blocked_rail = _blocking_rail(result)
            self.metrics.record_blocked(stage="output", rail=self.blocked_rail, reason="blocked", query=query)
            return True
        return False


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

    Returns ``(answer, error, block)``. ``block`` is None unless a check
    refused, and then the answer is the block message and ``block`` is
    ``{"stage": "input" | "output", "rails": [...]}``. An input refusal
    means the model never ran; an output refusal replaced its answer. The
    graph records both, so the audit shows what actually ran.
    ``grounding_context`` is passed to :meth:`GuardrailBroker.check_assistant`.
    """
    broker = GuardrailBroker(cfg, metrics)
    if broker.check_user(query or prompt):
        return cfg.block_message, None, {"stage": "input", "rails": [broker.blocked_rail or "nemo_check"]}
    try:
        if spend_context is None:
            answer = client.generate(prompt)
        else:
            answer = client.generate(prompt, spend_context=spend_context)
    except RAGError as exc:
        return f"[{label} Error: {exc.message}]", f"{exc.code}: {exc.message}", None
    if broker.check_assistant(query or prompt, answer, grounding_context=grounding_context):
        return cfg.block_message, None, {"stage": "output", "rails": [broker.blocked_rail or "nemo_check"]}
    return answer, None, None
