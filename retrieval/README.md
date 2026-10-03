# `retrieval/` — hybrid search and indexing

The RAG layer: local CPU embeddings + ChromaDB semantic search fused with
BM25 keyword search via Reciprocal Rank Fusion. Retrieval is the
**unconditional first step** of every query (invariant I1) — no LLM call
precedes it.

## Modules

| Module | Role |
|---|---|
| `results.py` | `SearchResult` dataclass. Imported by the retriever and by optional memory fusion so the memory package does not pull in Chroma/BM25. Re-exported from `hybrid_search.py`. |
| `hybrid_search.py` | `HybridRetriever`: ChromaDB semantic leg + BM25Okapi keyword leg → RRF fusion (`retrieval.rrf_k`, shipped 60). Uses normalized per-leg scores to settle exact RRF ties. Keeps semantic retrieval available when the corpus has no BM25 vocabulary and degrades to one leg when the other fails. |
| `indexer.py` | Corpus ingestion from `data/corpus/` (walked recursively; file types from `corpus.extensions`, shipped `[".md", ".txt"]`, matched case-insensitively): chunking (`indexing.chunk_size`/`chunk_overlap`, counted in the embedding model's own tokens when `indexing.chunk_unit` is `tokens`, as shipped, so no chunk runs past the model's window), chunk sanitization via the prompt filter, writes both indices. Run `python -m retrieval.indexer` (or `cyclaw-index`) explicitly — the server never builds the index on startup or on a query — the only in-process build is the operator-triggered `POST /index/build` route (loopback peer + same-origin, refused when proxied, plus the API key once `CYCLAW_API_KEY` is set, background thread, progress via `GET /index/status`); a missing index is fail-soft (503 `INDEX_NOT_FOUND`). |
| `embeddings.py` | Local sentence-transformers embeddings, device hardcoded to CPU (`EMBED_DEVICE` — cross-platform ranking determinism; see the constant's own comment). Triple `lru_cache`; `embedding_fingerprint()` detects index staleness. HF offline flags are set conditionally, never blanket (see `utils/telemetry_kill.py`'s exclusion note). |
| `rerank.py` | Local cross-encoder (`models.reranker`, shipped `cross-encoder/ms-marco-MiniLM-L6-v2`, CPU) behind the vault-hit gate's veto. `graph.retrieve_node` scores the chunks the model will see via `HybridRetriever.rerank_scores`; `hybrid_search` never calls it, so MCP never pays for it. Loads like the embedder (shared `cache_dir`, offline once cached, `offline_after_index` honoured), in float32, and is fail-soft: off or unavailable, the cosine rule decides alone. |
| `vector_store.py` | Pluggable semantic backend: embedded ChromaDB `PersistentClient` (default, offline-first) or pgvector (`indexing.vector_backend: "pgvector"` + Postgres DSN). The sole ChromaDB chokepoint — it applies the telemetry kill itself. Every `PersistentClient(...)` call here must pass `Settings(anonymized_telemetry=False)`; `gate.py` calls `utils.telemetry_kill.verify_telemetry_contract()` at boot, which AST-parses this file and fails closed if any site is missing it. RRF and BM25 are backend-agnostic. |
| `stemmer.py` | Porter-based stemmer with custom AI/DevOps/CyClaw vocabulary; avoids NLTK punkt (CVE surface). Pins `nltk==3.10.3` (closes a `PorterStemmer` DoS cluster) and caps every token at 256 chars before stemming as defense in depth (CVE-2026-81722). |
| `clear_cache.py` | Dry-run-by-default embedding-cache cleaner (`--apply` to delete). The cache is a regenerable artifact; index/audit/soul are untouched. |

Before #1522 merged, a corpus made only of empty or whitespace-only files
produced zero chunks after `load_corpus` succeeded. `build_index` then reset
the vector store and replaced BM25 with an empty index. Merged PR
[#1522](https://github.com/cgfixit/CyClaw/pull/1522) (shipped 2026-10-03) adds a zero-chunk check
before the writer is created.

## Numbers that trip people

- `retrieval.min_score` (shipped **0.028**) is on the **RRF scale**, not
  cosine. Ranks are zero-based: dual rank-0 with `rrf_k=60` is
  `2/60 ≈ 0.0333` (the two-leg hybrid ceiling).
  It only gates when no hit carries a cosine (the keyword-only degrade).
  Hybrid queries are decided by `retrieval.min_semantic_score` (shipped
  **0.30**, cosine on the **best** semantic hit within the first
  `LOCAL_CONTEXT_CHUNKS` fused results that the local answer node uses).
- `retrieval.min_rerank_score` (shipped **null**: shadow mode, logits are
  audited and nothing is vetoed) is a cross-encoder **logit** when set, not a
  cosine or a probability (0.0 is sigmoid 0.5). A number is a veto on a
  cosine vault hit: the best logit among the context-window chunks must reach
  it, and it can never turn a miss into a hit. The pre-registered 0.0 was
  rejected when measured (PR #1463): it also vetoed answerable questions. A
  five-model bake-off (PR #1464) found no model and threshold that passed its
  held-out probes either; see `docs/audits/2026-09-26-reranker-bakeoff.md`.
- `indexing.chunk_overlap` must stay `< chunk_size`. With `chunk_unit:
  tokens` (shipped: 256/32) both count the embedder's word pieces, and
  `chunk_size` includes its 2 special tokens, so 256 is exactly
  all-MiniLM-L6-v2's window; a larger value is capped to it. Without the key,
  both count whitespace words, and a 512-word chunk can exceed the model's
  window. Changing the unit or window size requires a rebuild. In token mode,
  overlap must be less than the content window after special tokens are
  reserved, which is 254 tokens for the shipped embedder.
- The BM25 store is **JSON** (`index/bm25.json`), never pickle. Each build
  writes a new Chroma collection or pgvector table and records its name as
  `vector_collection` in the atomically replaced BM25 file. Each retriever
  therefore pairs keyword data with its own vector generation. A gateway
  rebuild keeps the old retriever serving until the new one is ready;
  standalone indexing requires a server restart to load the new index.
- All values live in `config.yaml`, with one deliberate exception: the
  query-embedding LRU cache size is fixed at import time by `functools.lru_cache`
  (default `2048` in `embeddings.py`), so it is overridable only via the
  `CYCLAW_EMBED_CACHE_SIZE` env var, not `config.yaml`.

## Answer grounding

After retrieval and generation, the default-enabled guardrails compare a
retrieved local answer against its `answer_sources` using token overlap
(`guardrails.hallucination_threshold: 0.18`). This is a separate output check
from the retrieval scores above. It can replace an answer with the refusal
message even when retrieval cleared the vault-hit gate. Best-effort and
external answers skip grounding but retain input and soul-leak checks. MCP
remains retrieval-only. See the [NeMo reference](../docs/NeMo/README.md).

## Related

- Corpus location and rules: [`data/README.md`](../data/README.md)
- Retrieval-only MCP surface: `mcp_hybrid_server.py` (no LLM path,
  `sampling: None`). Live search stays on `POST /query` or a Claude Desktop
  MCP client.
- Index health tooling: `.claude/skills/index-doctor/`
