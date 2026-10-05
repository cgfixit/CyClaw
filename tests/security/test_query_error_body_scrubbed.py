"""A degraded /query (HTTP 200 with ``error`` set) must not publish host details.

The 200-on-degraded contract stays (see tests/test_runtime_errors.py Group 2,
and the e2e-fixes DECISION). What this file pins is the other half of that
contract: when graph.py hands back a stand-in answer such as
``[LLM Error: ...]`` together with ``state["error"]``, gate.py runs BOTH fields
through ``public_error()`` before they reach the console (static/terminal.js
renders them verbatim, escaped, as an ERROR entry). If that scrub ever moves or
is narrowed to one field, the raw exception text -- server filesystem paths
and live credential values -- would land in the browser.

Scope note (deliberate): ``public_error`` does not strip loopback URLs or host
names, so these tests do not assert on them; the console user is already
authenticated to this same host.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import MOCK_HIGH_SCORE_RESULTS, MockLocalLLM, MockRetriever, TEST_CONFIG

POSIX_PATH = "/home/alice-shield/.cyclaw/models/private-model.gguf"
WINDOWS_PATH = "C:\\Users\\alice-shield\\cyclaw\\private-model.gguf"
# Shaped like a real key and long enough for redact_sensitive's live-value pass.
LIVE_SECRET = "xai-shieldtest-0123456789abcdef0123456789abcdef"


@pytest.fixture()
def degraded_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, MagicMock]]:
    """TestClient whose graph returns a caller-chosen degraded state."""
    from fastapi.testclient import TestClient

    from utils.logger import reset_config_cache

    monkeypatch.setenv("GROK_API_KEY", LIVE_SECRET)
    reset_config_cache()
    cfg: dict[str, Any] = copy.deepcopy(TEST_CONFIG)
    cfg["logging"]["audit_file"] = str(tmp_path / "audit.jsonl")
    cfg["logging"]["log_file"] = str(tmp_path / "gateway.log")
    mock_graph = MagicMock()

    with (
        patch("gate.yaml.safe_load", return_value=cfg),
        patch("gate.cfg", cfg),
        patch("gate.HybridRetriever"),
        patch("gate.LocalLLMClient"),
        patch("gate.build_graph", return_value=mock_graph),
        patch("gate.check_input", side_effect=lambda q: q),
        patch("gate.check_all", return_value=[]),
    ):
        import gate

        gate.cfg = cfg
        names = ("retriever", "local_llm", "grok", "compiled_graph")
        saved = {k: getattr(gate, k, None) for k in names}
        try:
            fakes: dict[str, object] = {
                "retriever": MockRetriever(MOCK_HIGH_SCORE_RESULTS),  # type: ignore[no-untyped-call]
                "local_llm": MockLocalLLM(),  # type: ignore[no-untyped-call]
                "grok": None,
                "compiled_graph": mock_graph,
            }
            for k, v in fakes.items():
                setattr(gate, k, v)
            client = TestClient(gate.app, base_url="http://localhost")  # DevSkim: ignore DS162092,DS137138
            yield client, mock_graph
        finally:
            for k, v in saved.items():
                setattr(gate, k, v)
    reset_config_cache()


def _state(answer: str, error: str) -> dict[str, Any]:
    return {
        "query": "q",
        "answer": answer,
        "answer_model": "local",
        "answer_sources": [],
        "retrieved_docs": [],
        "top_score": 0.85,
        "retrieval_mode": "hybrid",
        "needs_user_confirm": False,
        "audit_event": {},
        "error": error,
    }


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (
            f"[LLM Error: model file missing at {POSIX_PATH}]",
            f"LLM_SERVICE_ERROR: model file missing at {POSIX_PATH}",
        ),
        (
            f"[LLM Error: cannot open {WINDOWS_PATH}]",
            f"LLM_SERVICE_ERROR: cannot open {WINDOWS_PATH}",
        ),
        (
            f"[LLM Error: endpoint rejected key {LIVE_SECRET}]",
            f"ENDPOINT_TRUST: endpoint rejected key {LIVE_SECRET}",
        ),
    ],
    ids=["posix-path", "windows-path", "live-secret"],
)
def test_degraded_query_scrubs_answer_and_error(degraded_gate: tuple[Any, MagicMock], answer: str, error: str) -> None:
    client, graph = degraded_gate
    graph.invoke.return_value = _state(answer, error)

    resp = client.post("/query", json={"query": "anything"})

    assert resp.status_code == 200  # contract unchanged
    body = resp.json()
    raw = resp.text
    for leaked in ("alice-shield", "private-model.gguf", LIVE_SECRET):
        assert leaked not in raw, f"{leaked!r} reached the /query body"
    # Both fields are still present and still recognisable, so the console's
    # stand-in detection (terminal.js isStubAnswer) keeps working.
    assert body["error"]
    assert body["answer"].startswith("[LLM Error:")
    assert body["answer"].endswith("]")


def test_scrub_is_applied_to_answer_only_when_error_is_set(degraded_gate: tuple[Any, MagicMock]) -> None:
    """A normal answer is not rewritten: the scrub is tied to ``error``."""
    client, graph = degraded_gate
    state = _state("See /docs/setup.md for steps.", "")
    state.pop("error")
    graph.invoke.return_value = state

    body = client.post("/query", json={"query": "anything"}).json()

    assert body["answer"] == "See /docs/setup.md for steps."
