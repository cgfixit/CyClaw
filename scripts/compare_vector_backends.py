#!/usr/bin/env python3
"""Compare ChromaDB vs a sqlite-vec prototype on the shipped corpus (issue #1255 Phase C).

Builds two isolated semantic indices from the same corpus + embedding cache
(the real production chunking/embedding pipeline, via retrieval.indexer and
retrieval.embeddings) -- one through the real ChromaDB backend
(retrieval.vector_store.get_vector_writer/reader), one through a minimal
inline sqlite-vec writer/reader (Phase D's real backend does not exist yet;
this script's sqlite-vec code is prototype-only, not production API).

Runs index-doctor's fixed PROBES query set through both and reports:
  - per-query top-1 source agreement
  - top-k overlap@k (semantic leg only, k=5)
  - build wall-clock, query p50/p95 wall-clock

This is the "measure, don't assume" artifact the issue itself asks for
before Phase D can proceed -- mirrors scripts/measure_local_llm_throughput.py's
own framing (CLAUDE.md's words for this exact class of claim).

Does NOT touch retrieval/vector_store.py or config.yaml. Read-only against
the real corpus; writes only to a throwaway tempdir.

Usage:
    python scripts/compare_vector_backends.py [--config config.yaml] [--k 5] [--json]

Exit: 0 measured (even if backends disagree -- disagreement is the finding,
not a failure), 2 sqlite-vec unavailable, 3 env/config error.
"""

from __future__ import annotations

import argparse
import json
import statistics
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from retrieval.embeddings import embedding_fingerprint, get_embedding, get_embeddings_batch  # noqa: E402
from retrieval.indexer import (  # noqa: E402
    _anchor_index_paths,
    _resolve_config_path,
    load_config,
    load_corpus,
    make_chunker,
)
from retrieval.vector_store import get_vector_writer  # noqa: E402
from utils.errors import RAGError  # noqa: E402
from utils.sanitizer import sanitize_chunk  # noqa: E402

# Mirrors .claude/skills/index-doctor/doctor.py's PROBES -- same corpus-answerable
# query set, so results are directly comparable to that tool's own baseline.
PROBES = [
    "Describe CyClaw in one sentence.",
    "What fusion method blends semantic and keyword retrieval results?",
    "How does CyClaw combine ChromaDB embeddings with BM25 keyword search?",
    "What protects CyClaw against request-flood denial of service?",
    "According to the CyClaw Deployment section, what does CyClaw use for local LLM inference offline?",
]


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


class _SqliteVecPrototype:
    """Minimal inline prototype -- NOT the Phase D production API.

    Mirrors _ChromaWriter/_ChromaReader's method shape closely enough for
    this comparison, but intentionally skips atomicity, fingerprinting, and
    error handling that a real backend module would need (see the issue's
    deep-dive comment for that design).
    """

    def __init__(self, db_path: str, dim: int):
        import sqlite3

        import sqlite_vec

        self._conn = sqlite3.connect(db_path)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.execute(
            f"CREATE VIRTUAL TABLE vec_items USING vec0(embedding float[{dim}] distance_metric=cosine)"
        )
        self._conn.execute(
            "CREATE TABLE meta (rowid INTEGER PRIMARY KEY, source TEXT, chunk_id INT, text TEXT)"
        )

    def add(self, ids: list[str], documents: list[str], embeddings: list, metadatas: list[dict]) -> None:
        # Monotonic rowid, not hash(ids[i]) -- Python's str hash is
        # PYTHONHASHSEED-randomized per process and truncating it to 31 bits
        # has a real collision chance at corpus scale (~19% around 30k
        # chunks per the birthday bound), which would make the second
        # INSERT fail nondeterministically on the rowid primary key (a
        # Codex review finding). ids[i] is already unique by construction
        # (main()'s f"chunk_{i}"), so the loop index is a simpler, always-
        # collision-free stand-in.
        for i, (doc, emb, meta) in enumerate(zip(documents, embeddings, metadatas, strict=True)):
            rowid = i
            self._conn.execute(
                "INSERT INTO vec_items(rowid, embedding) VALUES (?, ?)", [rowid, _serialize(emb)]
            )
            self._conn.execute(
                "INSERT INTO meta(rowid, source, chunk_id, text) VALUES (?, ?, ?, ?)",
                [rowid, meta["source"], meta["chunk_id"], doc],
            )
        self._conn.commit()

    def query(self, embedding: list[float], k: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT vec_items.rowid, 1 - vec_items.distance AS score, "
            "meta.source, meta.chunk_id, meta.text "
            "FROM vec_items JOIN meta ON meta.rowid = vec_items.rowid "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance LIMIT ?",
            [_serialize(embedding), k, k],
        ).fetchall()
        return [
            {"score": score, "source": source, "chunk_id": chunk_id, "text": text}
            for _, score, source, chunk_id, text in rows
        ]

    def close(self) -> None:
        self._conn.close()


def _build_chunks(cfg: dict) -> tuple[list[str], list[dict]]:
    corpus_path = cfg["corpus"]["path"]
    extensions = cfg["corpus"]["extensions"]
    config_path_str = cfg.get("_config_path_str", "config.yaml")

    docs = load_corpus(corpus_path, extensions)
    split_document = make_chunker(cfg, config_path_str)
    all_chunks: list[str] = []
    all_metadata: list[dict] = []
    for source, content in docs:
        chunks = split_document(content)
        for i, chunk in enumerate(chunks):
            all_chunks.append(sanitize_chunk(chunk, config_path_str))
            all_metadata.append({"source": source, "chunk_id": i})
    return all_chunks, all_metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        print("sqlite-vec not installed -- pip install -c constraints.txt sqlite-vec", file=sys.stderr)
        return 2

    try:
        # Same anchoring as retrieval/indexer.py::build_index and
        # retrieval/hybrid_search.py -- a --config pointing at another
        # directory must resolve corpus.path/indexing.*_path relative to
        # that config's own directory, not the process cwd.
        resolved_config_path = _resolve_config_path(args.config)
        config_path_str = str(resolved_config_path)
        cfg = _anchor_index_paths(load_config(config_path_str), resolved_config_path)
        cfg["_config_path_str"] = config_path_str
        dim = int(cfg.get("models", {}).get("embeddings", {}).get("dim", 384))
        chunks, metadata = _build_chunks(cfg)
    except (OSError, ValueError, yaml.YAMLError, RAGError) as exc:
        print(f"Environment/config error: {exc}", file=sys.stderr)
        return 3
    if not chunks:
        print("No corpus chunks found -- check config.yaml's corpus.path", file=sys.stderr)
        return 3
    print(f"Corpus: {len(chunks)} chunks", file=sys.stderr)

    try:
        embeddings = get_embeddings_batch(chunks, config_path_str)
    except (RAGError, ImportError, OSError, RuntimeError, ValueError) as exc:
        # get_embeddings_batch() deliberately does NOT wrap _load_model()
        # failures in RAGError (retrieval/embeddings.py's own docstring: the
        # index-build path must abort loudly, unlike the query path's
        # _cached_embedding, which does wrap for soft-degrade). A missing
        # sentence-transformers package, corrupt cache, or model-load
        # RuntimeError would otherwise escape this except block as an
        # unhandled traceback exiting 1 instead of this script's documented
        # exit 3 (a Codex review finding) -- catch the same raw exception
        # types _cached_embedding itself catches internally.
        print(f"Environment/config error: {exc}", file=sys.stderr)
        return 3
    ids = [f"chunk_{i}" for i in range(len(chunks))]

    # --- Chroma (real production writer) ---
    with tempfile.TemporaryDirectory() as tmp:
        chroma_cfg = dict(cfg)
        # Force chroma explicitly -- if the operator's real config.yaml sets
        # indexing.vector_backend: pgvector, leaving that key inherited from
        # cfg would make get_vector_writer() below return _PgVectorWriter,
        # whose build replaces the REAL configured kb_chunks table. This
        # "Chroma leg" must never touch anything but the throwaway tempdir.
        chroma_cfg["indexing"] = {
            **cfg["indexing"],
            "vector_backend": "chroma",
            "chroma_path": tmp,
            "collection_name": "compare",
        }
        t0 = time.monotonic()
        writer = get_vector_writer(chroma_cfg)
        writer.reset(embedding_fingerprint(cfg.get("models", {}).get("embeddings", {})))
        # Slice writes by indexing.batch_size, mirroring retrieval/indexer.py's
        # own build_index() loop -- a single unbatched writer.add() call would
        # reject any corpus larger than chromadb's per-call cap (5,461 records
        # on the pinned 1.5.9 build) before ever reaching the sqlite-vec
        # comparison, rejecting corpora the real indexer supports fine.
        batch_size = cfg["indexing"]["batch_size"]
        for batch_start in range(0, len(chunks), batch_size):
            batch_end = min(batch_start + batch_size, len(chunks))
            writer.add(
                ids[batch_start:batch_end], chunks[batch_start:batch_end],
                embeddings[batch_start:batch_end], metadata[batch_start:batch_end],
            )
        writer.finalize()
        chroma_build_s = time.monotonic() - t0

        from retrieval.vector_store import get_vector_reader

        # Each build writes its own generation (see retrieval/vector_store.py);
        # open the one this writer just built.
        chroma_reader = get_vector_reader(chroma_cfg, writer.generation)

        chroma_results = {}
        chroma_query_times = []
        for probe in PROBES:
            q_emb = get_embedding(probe, config_path_str)
            t0 = time.monotonic()
            hits = chroma_reader.query(q_emb, args.k)
            chroma_query_times.append(time.monotonic() - t0)
            chroma_results[probe] = hits
        chroma_reader.close()
        writer.close()

    # --- sqlite-vec prototype ---
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "vec.db")
        t0 = time.monotonic()
        svwriter = _SqliteVecPrototype(db_path, dim)
        svwriter.add(ids, chunks, embeddings, metadata)
        sqlite_vec_build_s = time.monotonic() - t0

        sqlite_vec_results = {}
        sqlite_vec_query_times = []
        for probe in PROBES:
            q_emb = get_embedding(probe, config_path_str)
            t0 = time.monotonic()
            hits = svwriter.query(q_emb, args.k)
            sqlite_vec_query_times.append(time.monotonic() - t0)
            sqlite_vec_results[probe] = hits
        svwriter.close()

    # --- compare ---
    top1_agree = 0
    overlap_sum = 0.0
    per_query = []
    for probe in PROBES:
        c_hits = chroma_results[probe]
        s_hits = sqlite_vec_results[probe]
        c_sources_top1 = c_hits[0]["source"] if c_hits else None
        s_sources_top1 = s_hits[0]["source"] if s_hits else None
        agree = c_sources_top1 == s_sources_top1
        top1_agree += int(agree)
        # (source, chunk_id) -- the same unique identifiers both readers
        # already return -- not (source, text[:40]): two distinct chunks
        # from the same source sharing a 40-char prefix (a common boilerplate
        # header) would otherwise collapse into one set entry and falsely
        # inflate the reported overlap.
        c_set = {(h["source"], h["chunk_id"]) for h in c_hits}
        s_set = {(h["source"], h["chunk_id"]) for h in s_hits}
        # overlap@k = |intersection| / k, not Jaccard (|intersection| /
        # |union|) -- dividing by the union understates agreement whenever
        # the two top-k lists aren't identical (e.g. 4 shared hits out of
        # two 5-result lists is 4/5 = 0.8 overlap@5, not 4/6 = 0.667 Jaccard,
        # a Codex review finding that would otherwise distort the Phase D
        # agreement read).
        overlap = len(c_set & s_set) / max(args.k, 1)
        overlap_sum += overlap
        per_query.append({
            "probe": probe, "top1_agree": agree,
            "chroma_top1_score": c_hits[0]["score"] if c_hits else None,
            "sqlite_vec_top1_score": s_hits[0]["score"] if s_hits else None,
            "overlap_at_k": round(overlap, 3),
        })

    report = {
        "chunks": len(chunks),
        "k": args.k,
        "build_wall_clock_s": {"chroma": round(chroma_build_s, 3), "sqlite_vec": round(sqlite_vec_build_s, 3)},
        "query_wall_clock_s": {
            "chroma": {"p50": round(statistics.median(chroma_query_times), 5),
                       "p95": round(sorted(chroma_query_times)[int(len(chroma_query_times) * 0.95)], 5)},
            "sqlite_vec": {"p50": round(statistics.median(sqlite_vec_query_times), 5),
                           "p95": round(sorted(sqlite_vec_query_times)[int(len(sqlite_vec_query_times) * 0.95)], 5)},
        },
        "top1_agreement": f"{top1_agree}/{len(PROBES)}",
        "mean_overlap_at_k": round(overlap_sum / len(PROBES), 3),
        "per_query": per_query,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\nChunks indexed: {report['chunks']}")
        print(f"Build wall-clock: chroma={report['build_wall_clock_s']['chroma']}s "
              f"sqlite_vec={report['build_wall_clock_s']['sqlite_vec']}s")
        print(f"Query p50/p95: chroma={report['query_wall_clock_s']['chroma']} "
              f"sqlite_vec={report['query_wall_clock_s']['sqlite_vec']}")
        print(f"Top-1 source agreement: {report['top1_agreement']}")
        print(f"Mean overlap@{args.k}: {report['mean_overlap_at_k']}")
        for pq in per_query:
            print(f"  [{'=' if pq['top1_agree'] else '!'}] {pq['probe'][:60]!r} "
                  f"chroma={pq['chroma_top1_score']:.4f} sqlite_vec={pq['sqlite_vec_top1_score']:.4f} "
                  f"overlap={pq['overlap_at_k']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
