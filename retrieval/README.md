# `retrieval/` — hybrid search and indexing

Local CPU embeddings and ChromaDB semantic search fuse with BM25 keyword
search via Reciprocal Rank Fusion. Retrieval precedes every LLM call (I1).

## Modules

| Module | Role |
|---|---|
| `results.py` | `SearchResult` shared by retrieval/memory fusion without importing Chroma/BM25 into memory. Re-exported from `hybrid_search.py`. |
| `hybrid_search.py` | `HybridRetriever`: ChromaDB semantic leg + BM25Okapi keyword leg → RRF fusion (`retrieval.rrf_k`, shipped 60). Uses normalized per-leg scores to settle exact RRF ties. Keeps semantic retrieval available when the corpus has no BM25 vocabulary and degrades to one leg when the other fails. |
| `indexer.py` | Recursively ingests `data/corpus/`; `corpus.extensions` defaults to case-insensitive `.md`/`.txt`. Chunks by embedder tokens (`indexing.chunk_size`/`chunk_overlap`, shipped `chunk_unit: tokens`), sanitizes, and writes both indices. Run `python -m retrieval.indexer` or `cyclaw-index`. Startup and queries never build automatically; a missing index gives 503 `INDEX_NOT_FOUND`. `POST /index/build` runs a background build with progress at `GET /index/status`; it requires loopback, same origin, no forwarding headers, and operator credentials once `CYCLAW_API_KEY` exists. |
| `embeddings.py` | Local sentence-transformers embeddings, device hardcoded to CPU (`EMBED_DEVICE` — cross-platform ranking determinism; see the constant's own comment). Triple `lru_cache`; `embedding_fingerprint()` detects index staleness. HF offline flags are set conditionally, never blanket (see `utils/telemetry_kill.py`'s exclusion note). |
| `rerank.py` | Local cross-encoder (`models.reranker`, shipped `cross-encoder/ms-marco-MiniLM-L6-v2`, CPU) behind the vault-hit gate's veto. `graph.retrieve_node` scores the chunks the model will see via `HybridRetriever.rerank_scores`; `hybrid_search` never calls it, so MCP never pays for it. Loads like the embedder (shared `cache_dir`, offline once cached, `offline_after_index` honoured), in float32, and is fail-soft: off or unavailable, the cosine rule decides alone. |
| `vector_store.py` | Pluggable semantic backend: embedded ChromaDB `PersistentClient` (default, offline-first) or pgvector (`indexing.vector_backend: "pgvector"` + Postgres DSN). Applies the telemetry kill. Boot's `verify_telemetry_contract()` AST check refuses any `PersistentClient(...)` site missing `Settings(anonymized_telemetry=False)`. RRF and BM25 are backend-agnostic. |
| `stemmer.py` | Porter-based stemmer with custom AI/DevOps/CyClaw vocabulary; avoids NLTK punkt (CVE surface). Pins `nltk==3.10.4` (3.10.3 closed a `PorterStemmer` DoS cluster) and caps every token at 256 chars before stemming as defense in depth (CVE-2026-81722). |
| `clear_cache.py` | Dry-run-by-default embedding-cache cleaner (`--apply` to delete). The cache is a regenerable artifact; index/audit/soul are untouched. |

Corpus reads accept regular UTF-8 files within the corpus root and enforce
`corpus.max_file_bytes` before and during each read. Escaping links,
unreadable/undecodable files, and oversized files are skipped with warnings.
An empty chunk set raises `CorpusEmptyError` before vector-writer creation,
preserving the existing index. Non-ASCII chunks retain semantic indexing
when the ASCII BM25 tokenizer finds no tokens; the build warns about missing
keyword signal.

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
