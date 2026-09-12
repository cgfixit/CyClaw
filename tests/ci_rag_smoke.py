#!/usr/bin/env python3
"""Real (non-mocked) offline RAG smoke test for CI.

Unlike a fully-mocked smoke (a hardcoded MockRetriever that returned a constant
dict), this exercises the *actual* retrieval stack end to end:

  1. Build a real ChromaDB (semantic) + BM25 (keyword) index from data/corpus
     via retrieval.indexer.build_index().
  2. Instantiate the real HybridRetriever and run real hybrid_search() calls for
     several questions the committed corpus (data/corpus/cyclaw_overview.md)
     answers.
  3. Assert every query returns a hit whose fused score clears the configured
     retrieval.min_score gate (the 0.028 "vault hit" threshold from config.yaml)
     AND lands on the expected source doc -- i.e. the same path that the
     static/terminal.html /query endpoint exercises for a real RAG reply.

The min_score is read from config.yaml (NOT hardcoded) so the assertion tracks
the real gate and cannot silently drift if the threshold is retuned.

Queries are deliberately phrased close to the committed corpus headings so they
land well above the gate at stable CI runtime -- this is a regression smoke,
not a recall-tuning benchmark.

No LLM is involved: CI has no LM Studio, so this stops at retrieval (the part
ChromaDB + BM25 + RRF actually own). Generation is covered separately by the
gate/graph unit tests with a mocked LLM.

Exit non-zero on any failure so the CI step goes red on a real retrieval regression.
"""

import statistics
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Direct-script execution needs the repository root on sys.path before these
# project imports; module execution already has the same root naturally.
import yaml  # noqa: E402

from retrieval.indexer import build_index  # noqa: E402
from retrieval.hybrid_search import HybridRetriever  # noqa: E402
from tests import judge_eval  # noqa: E402

# K matches the live eval plane's evidence window. Floors are for this
# synthetic 24-case fixture (20 scored; 4 out-of-corpus skipped). Tighten
# from a measured origin/main run, do not copy faithfulness 0.80 here.
K = judge_eval.MAX_EVIDENCE_HITS
MIN_HIT_AT_K = 1.0
MIN_RECALL_AT_K = 1.0
MIN_MRR = 0.5

# (query, expected_source_substring) — each answerable by data/corpus/cyclaw_overview.md.
# Phrased near-verbatim to corpus content to clear the min_score gate reliably in CI.
QUERIES = [
    ("What fusion method does CyClaw use to blend semantic and keyword results?", "cyclaw_overview"),
    ("How does CyClaw combine ChromaDB vector embeddings with BM25 keyword search?", "cyclaw_overview"),
    ("What does CyClaw use for rate limiting to protect against DoS attacks?", "cyclaw_overview"),
    (
        "According to the CyClaw Deployment section, what does CyClaw use "
        "for local LLM inference offline?",
        "cyclaw_overview",
    ),
]


def unique_source_stems(hits: Sequence[object], k: int) -> list[str]:
    """First-seen Path(hit.source).stem, capped at k unique documents."""
    stems: list[str] = []
    for hit in hits:
        stem = Path(str(getattr(hit, "source", ""))).stem
        if not stem or stem in stems:
            continue
        stems.append(stem)
        if len(stems) >= k:
            break
    return stems


def hit_at_k(ranked: Sequence[str], expected: frozenset[str], k: int) -> float | None:
    if not expected:
        return None
    return 1.0 if expected.intersection(ranked[:k]) else 0.0


def recall_at_k(ranked: Sequence[str], expected: frozenset[str], k: int) -> float | None:
    if not expected:
        return None
    return len(expected.intersection(ranked[:k])) / len(expected)


def mean_reciprocal_rank(ranked: Sequence[str], expected: frozenset[str]) -> float | None:
    if not expected:
        return None
    for index, stem in enumerate(ranked, start=1):
        if stem in expected:
            return 1.0 / index
    return 0.0


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def groundedness_retrieval_metrics(retriever: HybridRetriever) -> tuple[int, float, float, float]:
    """Return (n_scored, hit@K, Recall@K, MRR) over cases with expected sources."""
    hits_out: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    for case in judge_eval.load_cases():
        expected = frozenset(case.expected_source_ids)
        if not expected:
            continue
        ranked = unique_source_stems(retriever.hybrid_search(case.query), K)
        hit = hit_at_k(ranked, expected, K)
        rec = recall_at_k(ranked, expected, K)
        mrr = mean_reciprocal_rank(ranked, expected)
        assert hit is not None and rec is not None and mrr is not None
        hits_out.append(hit)
        recalls.append(rec)
        mrrs.append(mrr)
    return len(hits_out), _mean(hits_out), _mean(recalls), _mean(mrrs)


def _run_groundedness_retrieval_gate() -> int:
    print("\n=== Groundedness retrieval metrics (isolated fixture index, no LLM) ===")
    scored_expected = sum(1 for case in judge_eval.load_cases() if case.expected_source_ids)
    with tempfile.TemporaryDirectory(prefix="cyclaw-groundedness-retr-") as tmp:
        config_path, _, _ = judge_eval.build_eval_index(Path(tmp))
        retriever = HybridRetriever(str(config_path))
        n_scored, hit, recall, mrr = groundedness_retrieval_metrics(retriever)
    print(f"  scored_cases: {n_scored} (expected {scored_expected})")
    print(f"  hit@{K}:      {hit:.4f}  (floor {MIN_HIT_AT_K})")
    print(f"  recall@{K}:   {recall:.4f}  (floor {MIN_RECALL_AT_K})")
    print(f"  MRR:        {mrr:.4f}  (floor {MIN_MRR})")
    if n_scored != scored_expected:
        print(f"FAIL: expected {scored_expected} cases with source labels, got {n_scored}")
        return 1
    failed = False
    if hit < MIN_HIT_AT_K:
        print(f"FAIL: hit@{K} {hit:.4f} < {MIN_HIT_AT_K}")
        failed = True
    if recall < MIN_RECALL_AT_K:
        print(f"FAIL: recall@{K} {recall:.4f} < {MIN_RECALL_AT_K}")
        failed = True
    if mrr < MIN_MRR:
        print(f"FAIL: MRR {mrr:.4f} < {MIN_MRR}")
        failed = True
    if failed:
        return 1
    print("  PASS: groundedness retrieval floors held")
    return 0


def main() -> int:
    print("=== Real Offline RAG Query Smoke (ChromaDB + BM25 + RRF) ===")

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    min_score = float(cfg["retrieval"]["min_score"])
    min_semantic = float(cfg["retrieval"].get("min_semantic_score") or 0.0)
    print(f"Configured min_score gate: {min_score}")
    print(f"Configured min_semantic_score gate: {min_semantic}")

    print("Building real index from", cfg["corpus"]["path"], "...")
    build_index()

    retriever = HybridRetriever()

    failures = 0
    for i, (query, expected_source_substr) in enumerate(QUERIES, start=1):
        print(f"\n[{i}/{len(QUERIES)}] Query: {query}")
        results = retriever.hybrid_search(query)

        if not results:
            print("  FAIL: retriever returned zero hits for a corpus-answerable query")
            failures += 1
            continue

        top = results[0]
        print(f"  Top source: {top.source}")
        print(f"  Top score:  {round(top.score, 6)} (gate: {min_score})")
        print(f"  Semantic:   {top.semantic_score} (gate: {min_semantic})")
        print(f"  Mode:       {top.retrieval_mode}")

        if top.score < min_score:
            print(f"  FAIL: top score {top.score} below min_score gate {min_score} (vault miss)")
            failures += 1
            continue

        if top.semantic_score is not None and top.semantic_score < min_semantic:
            print(
                f"  FAIL: semantic_score {top.semantic_score} below "
                f"min_semantic_score {min_semantic}"
            )
            failures += 1
            continue

        if expected_source_substr not in top.source:
            print(f"  FAIL: top source {top.source!r} did not contain {expected_source_substr!r}")
            failures += 1
            continue

        print("  PASS: vault hit above gate, correct source")

    if failures:
        print(f"\nFAIL: {failures}/{len(QUERIES)} RAG smoke queries failed")
        return 1

    print(f"\nAll {len(QUERIES)} real RAG queries passed (vault hits above the {min_score} gate)")
    return _run_groundedness_retrieval_gate()


if __name__ == "__main__":
    sys.exit(main())
