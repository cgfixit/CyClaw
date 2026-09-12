"""Pure retrieval-metric helpers used by tests.ci_rag_smoke. No Chroma, no LLM."""

from __future__ import annotations

from tests.ci_rag_smoke import hit_at_k, mean_reciprocal_rank, recall_at_k, unique_source_stems


class _Hit:
    def __init__(self, source: str) -> None:
        self.source = source


def test_unique_source_stems_dedupes_chunks_and_caps_k() -> None:
    hits = [
        _Hit("aurora_harbor.md"),
        _Hit("/tmp/aurora_harbor.md"),
        _Hit("cedar_transit.md"),
        _Hit("lumen_library.md"),
    ]
    assert unique_source_stems(hits, k=2) == ["aurora_harbor", "cedar_transit"]


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
