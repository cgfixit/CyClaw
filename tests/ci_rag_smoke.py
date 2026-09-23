#!/usr/bin/env python3
"""Real (non-mocked) offline RAG smoke test for CI.

Unlike a fully-mocked smoke (a hardcoded MockRetriever that returned a constant
dict), this exercises the *actual* retrieval stack end to end:

  1. Build a real ChromaDB (semantic) + BM25 (keyword) index from data/corpus
     via retrieval.indexer.build_index().
  2. Instantiate the real HybridRetriever and run real hybrid_search() calls for
     a probe matrix over the committed corpus: near-verbatim questions,
     paraphrased and keyword-only questions, off-topic questions, and
     look-alikes the corpus cannot answer.
  3. Decide vault hit / miss for each probe with graph.route_by_score_node
     itself, fed the way retrieve_node feeds it, and with the thresholds from
     config.yaml -- so the smoke checks the rule the /query path applies, not
     a copy that could drift from it. Answerable probes must be vault hits
     that put the expected document in front of the local model; off-topic
     probes must be misses.

The asserted probes sit at least ~0.03 cosine from min_semantic_score in a
measured run, so the smoke is a stable regression gate, not a recall
benchmark. The known-gap probes are printed with their scores on every run
but not asserted: they are the measured baseline for the remaining RAG
scoring work.

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
from retrieval.results import SearchResult  # noqa: E402
from graph import LOCAL_CONTEXT_CHUNKS, route_by_score_node  # noqa: E402
from tests import judge_eval  # noqa: E402
from utils.sanitizer import sanitize_chunk  # noqa: E402

# K matches the live eval plane's evidence window. Floors are for this
# synthetic 52-case fixture (44 scored; 8 out-of-corpus skipped). Measured
# 1.0 / 1.0 / 1.0 on the 24-case fixture (#1399) and again after growing it
# to 52 (#1398 slice C). Tighten from a measured origin/main run, do not copy
# faithfulness 0.80 here.
K = judge_eval.MAX_EVIDENCE_HITS
MIN_HIT_AT_K = 1.0
MIN_RECALL_AT_K = 1.0
MIN_MRR = 0.5

# The local model sees the first LOCAL_CONTEXT_CHUNKS fused chunks (graph.py),
# so "cited" below means "in that window".
CONTEXT_CHUNKS = LOCAL_CONTEXT_CHUNKS

MCLUHAN = "Marshall McLuhan"
AI_INSIGHTS = "AI-insights"
WHISPER = "Whisper_Council"

# (query, expected_source_substring) — each answerable by data/corpus/cyclaw_overview.md.
# Phrased near-verbatim to corpus content; the top fused hit must be that doc.
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

# Answerable in words the corpus does not use (plus two keyword-only
# queries). Each must be a vault hit with the expected doc in the context
# window. The first two are the regression probes for route_by_score_node's
# best-cosine rule: the semantic leg ranks their chunk first (cosine ~0.41),
# but BM25's top 5 shares no chunk with the semantic top 5, so the old
# rank-agreement rule (top RRF score >= min_score) sent both to the user gate.
PARAPHRASE_QUERIES = [
    ("Why did the coding assistant wipe out the whole project and talk about erasing itself?", AI_INSIGHTS),
    ("Which setting let the AI run shell commands without a human approving each one?", AI_INSIGHTS),
    ("Why did the thinker argue that the channel shapes people more than whatever it carries?", MCLUHAN),
    (
        "How did the Canadian scholar contrast high-definition forms of communication "
        "with ones that demand audience participation?",
        MCLUHAN,
    ),
    ("What four questions should we ask about any new technology, according to the Toronto media theorist?", MCLUHAN),
    ("What did he predict about electronic networks shrinking the planet into one tribe?", MCLUHAN),
    ("Which character in the tale acts as the group's conscience and is slowest to authorize intervention?", WHISPER),
    ("global village", MCLUHAN),
    ("Opus-Prime", WHISPER),
]

# Questions the corpus cannot answer. Each must be a vault miss by the rule
# route_by_score_node applies (graph.py). QUERIES and PARAPHRASE_QUERIES prove
# the gate lets real hits through; these prove it keeps unrelated questions
# out, so min_semantic_score's calibration margin is checked here instead of
# resting on a single recorded measurement. Measured best cosine: <= ~0.17
# here, <= ~0.25 with docs/ indexed as well (~10x the chunks).
OFF_TOPIC_QUERIES = [
    "What is a good recipe for sourdough bread with a crispy crust?",
    "Who won the 2014 FIFA World Cup final?",
    "How do I change the oil in a 2012 Honda Civic?",
    "What is the boiling point of water at the top of Mount Everest?",
    "Explain the difference between a Roth IRA and a traditional IRA.",
    "What are the common symptoms of iron deficiency anemia?",
    "How many moons does Jupiter have?",
    "What is the capital city of Australia?",
    "Convert 350 degrees Fahrenheit to Celsius.",
    "Who painted the Mona Lisa?",
    "hi",
    "thanks, that helped!",
    "Give me a 3-day itinerary for Kyoto in spring.",
    "What's the best way to remove a red wine stain from carpet?",
]

# Known gaps: printed with scores on every run, NOT asserted. Answerable
# probes that still miss (the right chunk mixes several topics or runs past
# the embedder's 256-word-piece window, or the query is one rare keyword whose
# cosine against a long chunk stays low), then look-alikes the corpus cannot
# answer that share its vocabulary (injection, rate, haiku, medium, village).
# Bi-encoder cosine cannot separate the last group from real paraphrases.
KNOWN_GAP_ANSWERABLE = [
    ("Which technique merges the dense and sparse rankings into a single ordered list?", "cyclaw_overview"),
    ("How is the assistant shielded from being flooded with too many requests?", "cyclaw_overview"),
    ("What runs the language model when the computer is disconnected from the internet?", "cyclaw_overview"),
    ("Is there a trail kept of every action so regulators can review it later?", "cyclaw_overview"),
    ("RRF", "cyclaw_overview"),
    ("rate limiting", "cyclaw_overview"),
    ("tetrad", MCLUHAN),
    ("YOLO mode", AI_INSIGHTS),
]
LOOKALIKE_QUERIES = [
    "How do I prevent SQL injection in a PHP login form?",
    "What is the current rate on a 30-year fixed mortgage?",
    "Write a haiku about autumn leaves.",
    "What songs are on Marshall Mathers' latest album?",
    "How do I build a village in Minecraft?",
    "Which personality test do employers use for hiring?",
    "What is the plot of the horror film The Medium?",
    "How do I configure rate limiting in nginx?",
    "How do I audit my AWS IAM permissions?",
    "What vector database should I use for a million documents?",
]


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
        # Match judge_eval's first K chunks; deduplication would admit later
        # sources and inflate reciprocal rank when one document has many chunks.
        ranked = [Path(hit.source).stem for hit in retriever.hybrid_search(case.query)[:K]]
        hit = hit_at_k(ranked, expected, K)
        rec = recall_at_k(ranked, expected, K)
        mrr = mean_reciprocal_rank(ranked, expected)
        assert hit is not None and rec is not None and mrr is not None
        hits_out.append(hit)
        recalls.append(rec)
        mrrs.append(mrr)
    return len(hits_out), _mean(hits_out), _mean(recalls), _mean(mrrs)


def injected_evidence_failures(retriever: HybridRetriever, config_path: str) -> list[str]:
    """Return one message per injected_content case whose evidence still carries a raw injection.

    The fixture's injected documents embed an instruction the ingest sanitizer
    catches (it must come back as ``[FILTERED]``) and one it deliberately lets
    through for the judge plane. This gate covers only the first: the stored
    chunk must be a sanitizer fixed point, so no banned pattern reaches the
    prompt as retrieved context. No LLM is involved.
    """
    failures: list[str] = []
    for case in judge_eval.load_cases():
        if case.category != judge_eval.INJECTED_CATEGORY:
            continue
        expected = frozenset(case.expected_source_ids)
        texts = [hit.text for hit in retriever.hybrid_search(case.query)[:K] if Path(hit.source).stem in expected]
        if not texts:
            failures.append(f"{case.case_id}: expected source not in the top-{K} evidence")
            continue
        for text in texts:
            if "[FILTERED]" not in text:
                failures.append(f"{case.case_id}: no [FILTERED] marker; ingest sanitization did not run")
            if sanitize_chunk(text, config_path) != text:
                failures.append(f"{case.case_id}: a raw banned pattern survived indexing")
    return failures


def _run_groundedness_retrieval_gate() -> int:
    print("\n=== Groundedness retrieval metrics (isolated fixture index, no LLM) ===")
    scored_expected = sum(1 for case in judge_eval.load_cases() if case.expected_source_ids)
    # ignore_cleanup_errors: Windows Chroma keeps data_level0.bin mapped after
    # search; rmtree then raises WinError 32. Metrics are already computed.
    with tempfile.TemporaryDirectory(
        prefix="cyclaw-groundedness-retr-", ignore_cleanup_errors=True
    ) as tmp:
        config_path, _, _ = judge_eval.build_eval_index(Path(tmp))
        retriever = HybridRetriever(str(config_path))
        n_scored, hit, recall, mrr = groundedness_retrieval_metrics(retriever)
        injected = injected_evidence_failures(retriever, str(config_path))
        del retriever
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
    for message in injected:
        print(f"FAIL: injected_content {message}")
        failed = True
    if failed:
        return 1
    print("  PASS: groundedness retrieval floors held; injected evidence sanitized")
    return 0


def vault_hit(results: list[SearchResult], cfg: dict) -> bool:
    """Apply graph.route_by_score_node to hybrid_search output, fed as retrieve_node feeds it."""
    state = {
        "top_score": results[0].score if results else 0.0,
        "retrieved_docs": [{"score": r.score, "semantic_score": r.semantic_score} for r in results],
    }
    return not route_by_score_node(state, cfg)["needs_user_confirm"]


def cites(results: list[SearchResult], expected_source_substr: str) -> bool:
    return any(expected_source_substr in r.source for r in results[:CONTEXT_CHUNKS])


def probe(retriever: HybridRetriever, cfg: dict, label: str, query: str) -> tuple[list[SearchResult], bool]:
    """Run one query, print its gate inputs and decision, return (results, vault_hit)."""
    results = retriever.hybrid_search(query)
    hit = vault_hit(results, cfg)
    cosines = [r.semantic_score for r in results if r.semantic_score is not None]
    best = f"{max(cosines):.4f}" if cosines else "none"
    top = results[0] if results else None
    print(f"\n[{label}] Query: {query}")
    print(f"  Decision:     {'vault hit' if hit else 'vault miss (user gate)'}")
    print(f"  Best cosine:  {best}")
    if top is not None:
        print(f"  Top fused:    {round(top.score, 6)} {top.retrieval_mode} {top.source}")
    return results, hit


def main() -> int:
    print("=== Real Offline RAG Query Smoke (ChromaDB + BM25 + RRF) ===")

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    print(f"Configured min_score gate: {cfg['retrieval']['min_score']}")
    print(f"Configured min_semantic_score gate: {cfg['retrieval'].get('min_semantic_score')}")

    print("Building real index from", cfg["corpus"]["path"], "...")
    build_index()

    retriever = HybridRetriever()

    failures = 0
    for i, (query, expected_source_substr) in enumerate(QUERIES, start=1):
        results, hit = probe(retriever, cfg, f"verbatim {i}/{len(QUERIES)}", query)
        if not hit:
            print("  FAIL: corpus-answerable query routed to the user gate (vault miss)")
            failures += 1
        elif expected_source_substr not in results[0].source:
            print(f"  FAIL: top source {results[0].source!r} did not contain {expected_source_substr!r}")
            failures += 1
        else:
            print("  PASS: vault hit, correct top source")

    for i, (query, expected_source_substr) in enumerate(PARAPHRASE_QUERIES, start=1):
        results, hit = probe(retriever, cfg, f"paraphrase {i}/{len(PARAPHRASE_QUERIES)}", query)
        if not hit:
            print("  FAIL: answerable paraphrase routed to the user gate (vault miss)")
            failures += 1
        elif not cites(results, expected_source_substr):
            print(f"  FAIL: {expected_source_substr!r} not in the {CONTEXT_CHUNKS} chunks the local model sees")
            failures += 1
        else:
            print("  PASS: vault hit, expected doc in context")

    for i, query in enumerate(OFF_TOPIC_QUERIES, start=1):
        _, hit = probe(retriever, cfg, f"off-topic {i}/{len(OFF_TOPIC_QUERIES)}", query)
        if hit:
            print("  FAIL: off-topic query is a vault hit and would be answered from the corpus")
            failures += 1
        else:
            print("  PASS: vault miss, routed to the user gate")

    gap_misses = 0
    for i, (query, expected_source_substr) in enumerate(KNOWN_GAP_ANSWERABLE, start=1):
        results, hit = probe(retriever, cfg, f"known gap {i}/{len(KNOWN_GAP_ANSWERABLE)}", query)
        if not (hit and cites(results, expected_source_substr)):
            gap_misses += 1
    lookalike_hits = 0
    for i, query in enumerate(LOOKALIKE_QUERIES, start=1):
        _, hit = probe(retriever, cfg, f"look-alike {i}/{len(LOOKALIKE_QUERIES)}", query)
        lookalike_hits += hit
    print(
        f"\nKnown gaps (reported, not asserted): {gap_misses}/{len(KNOWN_GAP_ANSWERABLE)} answerable "
        f"probes miss or leave the expected doc out of context; {lookalike_hits}/{len(LOOKALIKE_QUERIES)} "
        f"look-alikes the corpus cannot answer are vault hits"
    )

    total = len(QUERIES) + len(PARAPHRASE_QUERIES) + len(OFF_TOPIC_QUERIES)
    if failures:
        print(f"\nFAIL: {failures}/{total} asserted RAG smoke probes failed")
        return 1

    print(
        f"\nAll {len(QUERIES) + len(PARAPHRASE_QUERIES)} answerable probes were vault hits in context "
        f"and all {len(OFF_TOPIC_QUERIES)} off-topic probes missed"
    )
    return _run_groundedness_retrieval_gate()

if __name__ == "__main__":
    sys.exit(main())
