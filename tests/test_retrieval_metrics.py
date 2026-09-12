"""Pure retrieval-metric helpers used by tests.ci_rag_smoke. No Chroma, no LLM."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

from retrieval.hybrid_search import HybridRetriever
from tests import ci_rag_smoke, judge_eval
from tests.ci_rag_smoke import hit_at_k, mean_reciprocal_rank, recall_at_k


class _Hit:
    def __init__(self, source: str) -> None:
        self.source = source


def test_empty_expected_is_skipped() -> None:
    ranked = ["aurora_harbor"]
    empty: frozenset[str] = frozenset()
    assert hit_at_k(ranked, empty, 5) is None
    assert recall_at_k(ranked, empty, 5) is None
    assert mean_reciprocal_rank(ranked, empty) is None


def test_hit_recall_mrr_on_two_source_case() -> None:
    ranked = ["cedar_transit", "aurora_harbor", "nova_farm"]
    expected = frozenset({"aurora_harbor", "quartz_energy"})
    assert hit_at_k(ranked, expected, 5) == 1.0
    assert recall_at_k(ranked, expected, 5) == 0.5
    assert mean_reciprocal_rank(ranked, expected) == 0.5


def test_miss_is_zero() -> None:
    ranked = ["nova_farm"]
    expected = frozenset({"aurora_harbor"})
    assert hit_at_k(ranked, expected, 5) == 0.0
    assert recall_at_k(ranked, expected, 5) == 0.0
    assert mean_reciprocal_rank(ranked, expected) == 0.0


@pytest.mark.parametrize(
    ("sources", "expected_metrics"),
    [
        (["noise.md"] * 5 + ["expected.md"], (1, 0.0, 0.0, 0.0)),
        (["noise.md"] * 2 + ["expected.md"], (1, 1.0, 1.0, 1 / 3)),
        (["expected.md"] * 5, (1, 1.0, 1.0, 1.0)),
    ],
)
def test_metrics_respect_chunk_window_and_rank(
    monkeypatch: pytest.MonkeyPatch,
    sources: list[str],
    expected_metrics: tuple[int, float, float, float],
) -> None:
    case = SimpleNamespace(query="fixture question", expected_source_ids=("expected",))
    monkeypatch.setattr(judge_eval, "load_cases", lambda: [case])
    retriever = create_autospec(HybridRetriever, instance=True)
    retriever.hybrid_search.return_value = [_Hit(source) for source in sources]
    assert ci_rag_smoke.groundedness_retrieval_metrics(retriever) == expected_metrics
