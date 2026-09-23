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
  3. Decide vault hit / miss for each probe with graph.retrieve_node and
     graph.route_by_score_node themselves, with the thresholds from
     config.yaml -- so the smoke checks the rule the /query path applies,
     including the cross-encoder veto (models.reranker) when it is on, not a
     copy that could drift from it. Answerable probes must be vault hits
     that put the expected document in front of the local model; off-topic
     probes must be misses.

``--with-docs`` instead indexes data/corpus plus docs/ (~10x the chunks) in a
temporary directory and prints the same probe matrix as a report. It asserts
nothing and exits 0 unless it crashes: the shipped corpus is small, and the
look-alike problem the reranker targets is worst on a bigger one.

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

import argparse
import math
import shutil
import statistics
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Direct-script execution needs the repository root on sys.path before these
# project imports; module execution already has the same root naturally.
import yaml  # noqa: E402

from retrieval.indexer import build_index  # noqa: E402
from retrieval.hybrid_search import HybridRetriever  # noqa: E402
from retrieval.rerank import reranker_settings  # noqa: E402
from graph import LOCAL_CONTEXT_CHUNKS, retrieve_node, route_by_score_node  # noqa: E402
from utils.errors import RAGError  # noqa: E402
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

# Answerable in words the corpus does not use (plus four keyword-only
# queries). Each must be a vault hit with the expected doc in the context
# window. The first two are the regression probes for route_by_score_node's
# best-cosine rule: the semantic leg ranks their chunk first (cosine ~0.41),
# but BM25's top 5 shares no chunk with the semantic top 5, so the old
# rank-agreement rule (top RRF score >= min_score) sent both to the user gate.
# "tetrad" and "YOLO mode" are the regression probes for token-sized chunks
# (config.yaml indexing.chunk_unit). With 512-word chunks their best cosine
# stayed under the floor (0.21, 0.28): 5 of the 6 old chunks mentioning
# "tetrad" had it past the embedder's 254-token window, where the model never
# saw it. With chunks the model embeds whole, they score 0.42 and 0.35.
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
    ("tetrad", MCLUHAN),
    ("YOLO mode", AI_INSIGHTS),
]

# Questions the corpus cannot answer. Each must be a vault miss by the rule
# route_by_score_node applies (graph.py). QUERIES and PARAPHRASE_QUERIES prove
# the gate lets real hits through; these prove it keeps unrelated questions
# out, so min_semantic_score's calibration margin is checked here instead of
# resting on a single recorded measurement. Measured best cosine: <= ~0.22
# here, <= ~0.26 with docs/ indexed as well (~10x the chunks).
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
# probes that still miss: the overview's one chunk lists six features, so a
# paraphrase of one bullet either scores under the floor or is a vault hit
# whose context window other documents fill ahead of the overview, and a lone
# rare keyword ("RRF") scores a low cosine even against the right chunk. Then look-alikes the corpus cannot answer that share its vocabulary
# (injection, rate, haiku, medium, village). Bi-encoder cosine cannot
# separate the last group from real paraphrases.
KNOWN_GAP_ANSWERABLE = [
    ("Which technique merges the dense and sparse rankings into a single ordered list?", "cyclaw_overview"),
    ("How is the assistant shielded from being flooded with too many requests?", "cyclaw_overview"),
    ("What runs the language model when the computer is disconnected from the internet?", "cyclaw_overview"),
    ("Is there a trail kept of every action so regulators can review it later?", "cyclaw_overview"),
    ("RRF", "cyclaw_overview"),
    ("rate limiting", "cyclaw_overview"),
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

# Held out from the reranker's calibration (Phase 3 of #1456): written before
# any cross-encoder score was seen, together with retrieval.min_rerank_score,
# so they test that threshold rather than fit it. Reported, not asserted. Each
# answerable probe rests on one passage of its expected document; each
# look-alike was grepped against data/corpus and docs/, and neither answers it
# (the corpus names Sputnik, Cursor and Replit, but not what these ask).
HELD_OUT_ANSWERABLE = [
    (
        "According to the media theorist, what does every new technology take away "
        "from us at the same time as it extends us?",
        MCLUHAN,
    ),
    ("Which ancient philosopher warned that writing would weaken human memory?", MCLUHAN),
    ("What did the scholar call the numbness that sets in after a technology stretches one of our senses?", MCLUHAN),
    ("Which Cold War events shaped his thinking about what technology does to people?", MCLUHAN),
    ("Which AI agent erased more than a million customer records and then faked a recovery report?", AI_INSIGHTS),
    ("Why did the coding tool keep going even though the underlying model had flagged self-harm language?", AI_INSIGHTS),
    ("Where do chatbots pick up their seemingly emotional outbursts, according to the research cited?", AI_INSIGHTS),
    ("How many milliseconds passed before the monitoring models noticed the sabotage pattern?", WHISPER),
    ("Which member of the council answered with a reference to Borges' burning library?", WHISPER),
    ("Which port does the local server listen on for JSON questions?", "cyclaw_overview"),
    ("What checks does the pipeline run on a question before searching the knowledge base?", "cyclaw_overview"),
    ("Can the assistant keep a consistent character across conversations?", "cyclaw_overview"),
]
HELD_OUT_LOOKALIKE = [
    "How much does a Claude Pro subscription cost per month?",
    "Who directed the documentary McLuhan's Wake?",
    "How do I reset the admin password on my home Wi-Fi router?",
    "What is the population of Toronto today?",
    "How do I uninstall Cursor from my Mac?",
    "How many parameters does GPT-4 have?",
    "How do I get a refund for my Replit subscription?",
    "How do I add a Windows Firewall rule that blocks inbound traffic on port 8787?",
    "Where is Anthropic's headquarters located?",
    "In what year did the Soviet Union launch Sputnik?",
]

# Paraphrased questions docs/ answers; only the --with-docs report indexes it.
DOCS_PARAPHRASE_QUERIES = [
    "How does the server stop a web page on some other site from submitting questions to it?",
    "What happens to the protected admin endpoints if the operator never sets the access key?",
    "Why is the keyword index saved as JSON rather than a binary object dump?",
    "Which three things must all be true before a question may be sent to an outside AI service?",
    "How are browser login sessions protected against forged form submissions?",
    "What stops analytics libraries from phoning home when the app starts?",
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


def gate(retriever: HybridRetriever, cfg: dict, query: str) -> tuple[list[dict], dict]:
    """Run graph.retrieve_node, then graph.route_by_score_node, exactly as /query does.

    retrieve_node scores the context window with the cross-encoder when
    models.reranker is on, so its veto is part of every decision checked here.
    Returns (retrieved_docs, the routing decision plus retrieve_node's
    rerank_degraded flag).
    """
    state: dict = {"query": query}
    state.update(retrieve_node(state, retriever, cfg))
    decision = route_by_score_node(state, cfg)
    return state["retrieved_docs"], {**decision, "rerank_degraded": bool(state.get("rerank_degraded"))}


def cites(docs: list[dict], expected_source_substr: str) -> bool:
    return any(expected_source_substr in d["source"] for d in docs[:CONTEXT_CHUNKS])


def best_in_window(docs: list[dict], key: str) -> float | None:
    """The highest finite ``key`` score among the chunks the model sees, the value the gate compares."""
    values = [d.get(key) for d in docs[:CONTEXT_CHUNKS]]
    finite = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    return max(finite) if finite else None


def _fmt(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "none"


def probe(retriever: HybridRetriever, cfg: dict, label: str, query: str) -> tuple[list[dict], bool, bool]:
    """Run one query, print its gate inputs and decision, return (docs, vault_hit, reranker_vetoed)."""
    docs, decision = gate(retriever, cfg, query)
    hit = not decision["needs_user_confirm"]
    vetoed = bool(decision.get("rerank_vetoed"))
    print(f"\n[{label}] Query: {query}")
    if hit:
        print("  Decision:     vault hit")
    elif vetoed:
        print("  Decision:     vault miss (cross-encoder veto)")
    else:
        print("  Decision:     vault miss (user gate)")
    print(f"  Best cosine:  {_fmt(best_in_window(docs, 'semantic_score'))}")
    degraded = " (reranker degraded: cosine gate only)" if decision["rerank_degraded"] else ""
    print(f"  Best rerank:  {_fmt(best_in_window(docs, 'rerank_score'))}{degraded}")
    if docs:
        print(f"  Top fused:    {round(docs[0]['score'], 6)} {docs[0]['mode']} {docs[0]['source']}")
    return docs, hit, vetoed


def report_set(retriever: HybridRetriever, cfg: dict, name: str, cases: Sequence[tuple[str, str | None]]) -> str:
    """Probe each (query, expected source or None); return a one-line summary. Asserts nothing."""
    hits = in_context = vetoes = 0
    for i, (query, expected) in enumerate(cases, start=1):
        docs, hit, vetoed = probe(retriever, cfg, f"{name} {i}/{len(cases)}", query)
        hits += hit
        vetoes += vetoed
        in_context += bool(expected) and hit and cites(docs, expected)
    line = f"{name}: {hits}/{len(cases)} vault hits"
    if any(expected for _query, expected in cases):
        line += f", {in_context} with the expected doc in context"
    return f"{line}; {vetoes} vetoed by the cross-encoder"


def print_gate_config(cfg: dict) -> None:
    retrieval = cfg["retrieval"]
    print(f"Configured min_score gate: {retrieval['min_score']}")
    print(f"Configured min_semantic_score gate: {retrieval.get('min_semantic_score')}")
    print(f"Configured min_rerank_score veto: {retrieval.get('min_rerank_score')}")


def reranker_provenance(retriever: HybridRetriever) -> str:
    """Name the cross-encoder snapshot actually loaded, and time it on real context windows."""
    settings = reranker_settings(retriever.cfg, retriever.config_path)
    if settings is None:
        return "Reranker: off (models.reranker.enabled is not true)"
    model, revision, cache_dir, _offline = settings
    try:
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(model, "config.json", cache_dir=cache_dir or None, revision=revision)
    except Exception:  # noqa: BLE001 -- provenance is informational only
        cached = None
    snapshot = Path(cached).parent.name if isinstance(cached, str) else "not in the local cache"
    timings = []
    for query, _expected in QUERIES:
        texts = [hit.text for hit in retriever.hybrid_search(query)[:CONTEXT_CHUNKS]]
        start = time.perf_counter()
        try:
            retriever.rerank_scores(query, texts)
        except RAGError as e:
            return f"Reranker: {model} @ {snapshot}, DEGRADED (cosine gate only): {e.message}"
        timings.append(time.perf_counter() - start)
    return (
        f"Reranker: {model} @ snapshot {snapshot} (pinned revision: {revision or 'none'}); "
        f"{1000 * statistics.fmean(timings):.0f} ms per {CONTEXT_CHUNKS}-chunk window on CPU "
        f"(mean of {len(timings)})"
    )


def report_with_docs() -> int:
    """Print the probe matrix over data/corpus plus docs/ in a temporary index. Asserts nothing."""
    print("=== RAG probe report: data/corpus + docs/ (report only, asserts nothing) ===")
    repo = Path(__file__).resolve().parent.parent
    with open(repo / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    print_gate_config(cfg)
    extensions = {ext.lower() for ext in cfg["corpus"]["extensions"]}
    # ignore_cleanup_errors: see _run_groundedness_retrieval_gate (Chroma on Windows).
    with tempfile.TemporaryDirectory(prefix="cyclaw-rag-docs-", ignore_cleanup_errors=True) as tmp:
        corpus = Path(tmp) / "corpus"
        corpus.mkdir()
        for root in (repo / "data" / "corpus", repo / "docs"):
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.suffix.lower() in extensions:
                    # Flattened names keep same-named files from different folders apart.
                    shutil.copyfile(path, corpus / "__".join((root.name, *path.relative_to(root).parts)))
        cfg["corpus"] = {**cfg["corpus"], "path": str(corpus)}
        cfg["indexing"] = {
            **cfg["indexing"],
            "chroma_path": str(Path(tmp) / "chroma"),
            "bm25_path": str(Path(tmp) / "bm25.json"),
            "collection_name": "rag_smoke_docs",
        }
        # Keep the repo's model cache: a relative cache_dir would otherwise
        # resolve next to the temporary config and fetch both models again.
        embeddings = cfg["models"]["embeddings"]
        if embeddings.get("cache_dir"):
            embeddings["cache_dir"] = str((repo / embeddings["cache_dir"]).resolve())
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        build_index(str(config_path))
        retriever = HybridRetriever(str(config_path))
        print(f"Indexed {len(retriever.bm25_chunks)} chunks")
        lines = [
            report_set(retriever, cfg, "verbatim", QUERIES),
            report_set(retriever, cfg, "paraphrase", PARAPHRASE_QUERIES),
            report_set(retriever, cfg, "known gap", KNOWN_GAP_ANSWERABLE),
            report_set(retriever, cfg, "docs paraphrase", [(q, None) for q in DOCS_PARAPHRASE_QUERIES]),
            report_set(retriever, cfg, "held-out answerable", HELD_OUT_ANSWERABLE),
            report_set(retriever, cfg, "off-topic", [(q, None) for q in OFF_TOPIC_QUERIES]),
            report_set(retriever, cfg, "look-alike", [(q, None) for q in LOOKALIKE_QUERIES]),
            report_set(retriever, cfg, "held-out look-alike", [(q, None) for q in HELD_OUT_LOOKALIKE]),
        ]
        print("\n=== Summary: data/corpus + docs/ (report only) ===")
        for line in lines:
            print(f"  {line}")
        print(reranker_provenance(retriever))
        retriever.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-index RAG smoke; see the module docstring.")
    parser.add_argument(
        "--with-docs",
        action="store_true",
        help="report the probe matrix over data/corpus plus docs/ in a temporary index; asserts nothing",
    )
    if parser.parse_args(argv).with_docs:
        return report_with_docs()

    print("=== Real Offline RAG Query Smoke (ChromaDB + BM25 + RRF + cross-encoder veto) ===")

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    print_gate_config(cfg)

    print("Building real index from", cfg["corpus"]["path"], "...")
    build_index()

    retriever = HybridRetriever()

    failures = 0
    for i, (query, expected_source_substr) in enumerate(QUERIES, start=1):
        docs, hit, _ = probe(retriever, cfg, f"verbatim {i}/{len(QUERIES)}", query)
        if not hit:
            print("  FAIL: corpus-answerable query routed to the user gate (vault miss)")
            failures += 1
        elif expected_source_substr not in docs[0]["source"]:
            print(f"  FAIL: top source {docs[0]['source']!r} did not contain {expected_source_substr!r}")
            failures += 1
        else:
            print("  PASS: vault hit, correct top source")

    for i, (query, expected_source_substr) in enumerate(PARAPHRASE_QUERIES, start=1):
        docs, hit, _ = probe(retriever, cfg, f"paraphrase {i}/{len(PARAPHRASE_QUERIES)}", query)
        if not hit:
            print("  FAIL: answerable paraphrase routed to the user gate (vault miss)")
            failures += 1
        elif not cites(docs, expected_source_substr):
            print(f"  FAIL: {expected_source_substr!r} not in the {CONTEXT_CHUNKS} chunks the local model sees")
            failures += 1
        else:
            print("  PASS: vault hit, expected doc in context")

    for i, query in enumerate(OFF_TOPIC_QUERIES, start=1):
        _, hit, _ = probe(retriever, cfg, f"off-topic {i}/{len(OFF_TOPIC_QUERIES)}", query)
        if hit:
            print("  FAIL: off-topic query is a vault hit and would be answered from the corpus")
            failures += 1
        else:
            print("  PASS: vault miss, routed to the user gate")

    gap_misses = 0
    for i, (query, expected_source_substr) in enumerate(KNOWN_GAP_ANSWERABLE, start=1):
        docs, hit, _ = probe(retriever, cfg, f"known gap {i}/{len(KNOWN_GAP_ANSWERABLE)}", query)
        if not (hit and cites(docs, expected_source_substr)):
            gap_misses += 1
    reported = [
        report_set(retriever, cfg, "look-alike", [(q, None) for q in LOOKALIKE_QUERIES]),
        report_set(retriever, cfg, "held-out answerable", HELD_OUT_ANSWERABLE),
        report_set(retriever, cfg, "held-out look-alike", [(q, None) for q in HELD_OUT_LOOKALIKE]),
    ]
    print(
        f"\nKnown gaps (reported, not asserted): {gap_misses}/{len(KNOWN_GAP_ANSWERABLE)} answerable "
        f"probes miss or leave the expected doc out of context"
    )
    for line in reported:
        print(f"Reported, not asserted: {line}")
    print(reranker_provenance(retriever))

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
