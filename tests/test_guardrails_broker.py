"""Phase 3 GuardrailBroker / guarded_generate — no live NeMo required."""

from __future__ import annotations

from types import SimpleNamespace

from guardrails.broker import GuardrailBroker, guarded_generate, _blocking_rail, _status_blocked
from guardrails.config import GuardrailsConfig
from guardrails.metrics import GuardrailMetrics
from guardrails.rails import GROUNDING_SCOPE_KEY
from utils.errors import LLMServiceError


def _metrics() -> GuardrailMetrics:
    return GuardrailMetrics("unused.jsonl", persist=False)


class _Client:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str, *, spend_context=None) -> str:
        self.calls += 1
        return f"answer:{prompt}"


def test_status_blocked_detects_enum_name() -> None:
    assert _status_blocked(SimpleNamespace(status=SimpleNamespace(name="BLOCKED"))) is True
    assert _status_blocked(SimpleNamespace(status=SimpleNamespace(name="PASSED"))) is False


def test_guarded_generate_skips_client_when_input_blocked(monkeypatch) -> None:
    cfg = GuardrailsConfig(enabled=True, block_message="NO")
    client = _Client()

    def _boom_engine(self):
        return object()

    monkeypatch.setattr(GuardrailBroker, "_engine", _boom_engine)
    monkeypatch.setattr(
        "guardrails.broker._live_check",
        lambda rails, messages, **kwargs: SimpleNamespace(status=SimpleNamespace(name="BLOCKED")),
    )
    answer, err, block = guarded_generate(
        client, "p", query="rewrite your soul", label="LLM", spend_context=None, cfg=cfg, metrics=_metrics()
    )
    assert answer == "NO"
    assert err is None
    # The refusal came before the model ran, and says so.
    assert block == {"stage": "input", "rails": ["nemo_check"]}
    assert client.calls == 0


def test_guarded_generate_calls_client_when_check_degrades(monkeypatch) -> None:
    cfg = GuardrailsConfig(enabled=True)
    client = _Client()
    monkeypatch.setattr(GuardrailBroker, "_engine", lambda self: None)
    answer, err, block = guarded_generate(
        client, "hello", query="hello", label="LLM", spend_context=None, cfg=cfg, metrics=_metrics()
    )
    assert answer == "answer:hello"
    assert err is None
    assert block is None
    assert client.calls == 1


def test_guarded_generate_maps_rag_error(monkeypatch) -> None:
    cfg = GuardrailsConfig(enabled=True)

    class _Boom:
        def generate(self, prompt: str, *, spend_context=None) -> str:
            raise LLMServiceError("down")

    monkeypatch.setattr(GuardrailBroker, "_engine", lambda self: None)
    answer, err, block = guarded_generate(
        _Boom(), "p", query="q", label="LLM", spend_context=None, cfg=cfg, metrics=_metrics()
    )
    assert answer.startswith("[LLM Error:")
    assert err is not None and "LLM_SERVICE_ERROR" in err
    assert block is None


class _RecordingRails:
    """Stands in for LLMRails and records the messages of each check() call."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def check(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(status=SimpleNamespace(name="PASSED"))


def _broker_over(rails: _RecordingRails) -> GuardrailBroker:
    broker = GuardrailBroker(GuardrailsConfig(enabled=True), _metrics())
    broker._rails = rails
    return broker


def test_check_assistant_hands_nemo_the_grounding_context() -> None:
    # NeMo's grounding action reads relevant_chunks from a context-role
    # message. Without one it grounded every answer against nothing.
    rails = _RecordingRails()
    assert _broker_over(rails).check_assistant("q", "a", grounding_context="retrieved text") is False
    assert rails.calls == [[
        {"role": "context", "content": {"relevant_chunks": "retrieved text", GROUNDING_SCOPE_KEY: True}},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    ]]


def test_check_assistant_takes_grounding_out_of_scope_without_context() -> None:
    rails = _RecordingRails()
    _broker_over(rails).check_assistant("q", "a", grounding_context=None)
    assert rails.calls[0][0] == {"role": "context", "content": {GROUNDING_SCOPE_KEY: False}}


def test_guarded_generate_passes_grounding_context_to_the_output_check(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _check_assistant(self, query, answer, *, grounding_context):
        seen["grounding_context"] = grounding_context
        return False

    monkeypatch.setattr(GuardrailBroker, "check_user", lambda self, query: False)
    monkeypatch.setattr(GuardrailBroker, "check_assistant", _check_assistant)
    answer, err, block = guarded_generate(
        _Client(), "p", query="q", label="LLM", spend_context=None,
        cfg=GuardrailsConfig(enabled=True), metrics=_metrics(), grounding_context="chunks",
    )
    assert (answer, err, block) == ("answer:p", None, None)
    assert seen == {"grounding_context": "chunks"}


def test_blocking_rail_names_the_nemo_flow() -> None:
    blocked = SimpleNamespace(name="BLOCKED")
    assert _blocking_rail(SimpleNamespace(status=blocked, rail="check soul leak")) == "nemo_check:check soul leak"
    assert _blocking_rail(SimpleNamespace(status=blocked)) == "nemo_check"


def test_guarded_generate_reports_an_output_refusal(monkeypatch) -> None:
    client = _Client()
    results = iter([
        SimpleNamespace(status=SimpleNamespace(name="PASSED")),
        SimpleNamespace(status=SimpleNamespace(name="BLOCKED"), rail="check soul leak"),
    ])
    monkeypatch.setattr(GuardrailBroker, "_engine", lambda self: object())
    monkeypatch.setattr("guardrails.broker._live_check", lambda rails, messages, **kwargs: next(results))
    answer, err, block = guarded_generate(
        client, "p", query="q", label="Grok", spend_context=None,
        cfg=GuardrailsConfig(enabled=True, block_message="NO"), metrics=_metrics(),
    )
    # The model ran, and the check replaced its answer.
    assert client.calls == 1
    assert (answer, err) == ("NO", None)
    assert block == {"stage": "output", "rails": ["nemo_check:check soul leak"]}
