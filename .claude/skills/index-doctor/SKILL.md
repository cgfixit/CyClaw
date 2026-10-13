---
name: index-doctor
description: Rebuild and validate the CyClaw hybrid retrieval index (ChromaDB semantic + BM25 keyword + RRF fusion), then run a fixed query probe set to confirm min_score gating, source correctness, RRF provenance, and both retrieval legs contributing. Use when asked to rebuild or validate the index, when retrieval quality degrades, or after any change to data/corpus/, the indexer, embeddings, stemmer, or retrieval config.
disable-model-invocation: true
---

# Index Doctor

**Persona:** You own retrieval health for CyClaw. The index is two artifacts
built from one corpus in a single pass: `index/chroma_db` (semantic, cosine over
`all-MiniLM-L6-v2`) and `index/bm25.json` (keyword). A query is answered by RRF
fusion (`k=60`) over both legs. In production the vault-hit decision is
`retrieval.min_semantic_score` (cosine 0.30 on the best semantic hit) plus the
optional cross-encoder veto `min_rerank_score` (shipped `null`); the RRF floor
`retrieval.min_score` (0.028, hybrid ceiling 2/60 ≈ 0.033) gates only the
keyword-only degrade (CLAUDE.md §4 "Retrieval & config"). When retrieval
"feels off," the cause is almost always here: a stale index, a corpus change
not reindexed, an empty or duplicated chunk, or a leg that silently stopped
contributing.

**What "healthy" means, concretely:** ChromaDB and BM25 chunk counts agree; no
empty or duplicate chunks; every corpus-answerable probe clears the RRF floor,
lands on the right source, carries RRF provenance, and both legs contribute
across the set. `doctor.py` compares each probe's fused score with
`min_score`; it does not evaluate the cosine gate or the reranker veto, so a
probe that passes here can still miss in `graph.py` — `tests/ci_rag_smoke.py`
is the check that walks the production gate. This skill wraps into one command
what `/run` (`smoke.sh`) and `ci_rag_smoke` do partially. See
`docs/work/PROPOSED_SKILLS.md` #4.

---

## Run

### Step 0 — Ensure the venv is present

The retrieval stack (torch CPU + chromadb + sentence-transformers) must be
installed. In a fresh container it is not — build it with
`bash .claude/skills/cyclaw-gotchas/driver.sh venv` (the hashed `locks/`
install from CLAUDE.md §8, torch first). The embedding model must also be
fetchable or cached: the cloud sandbox's proxy denies `huggingface.co`, so
the index cannot be built there at all (`cyclaw-gotchas`). `doctor.py` exits 3
with a clear message if deps are missing.

### Step 1 — Run the doctor

Read-only check against the current index:

```bash
python3 .claude/skills/index-doctor/doctor.py
```

Rebuild first, then check (use after a corpus change):

```bash
GROK_API_KEY=dummy python3 .claude/skills/index-doctor/doctor.py --rebuild
```

It runs six stages and prints `ok` / `WARN` / `FAIL` per line:

1. **Preflight** — corpus dir exists, has `.md`/`.txt` files, `chunk_overlap < chunk_size`.
2. **Rebuild** (with `--rebuild`) — `retrieval.indexer.build_index()`.
3. **Count parity** — ChromaDB collection count must equal the BM25 chunk count. A mismatch means a half-written or corrupted index.
4. **Chunk hygiene** — flags empty/whitespace chunks (FAIL) and exact-duplicate chunks (WARN).
5. **Probe set** — five committed-corpus queries (including the "Describe CyClaw in one sentence" vault-hit probe `smoke.sh` also runs) through the real `HybridRetriever`. Each must clear the RRF floor `min_score`, hit the expected source, and populate `rrf_score`. Across the set, BOTH `semantic` and `keyword` legs must contribute, and semantic-only / keyword-only searches must each return hits.
6. **Baseline delta** (with `--baseline report.json`) — warns on chunk-count or top-score drift vs a saved run.

Exit `0` healthy · `2` a check/probe failed · `3` env/config error.

### Step 2 — Diagnose failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Count mismatch (stage 3) | Interrupted build; stale chroma dir alongside new bm25.json | `--rebuild` from a clean `index/` (delete `index/chroma_db` + `index/bm25.json`, rebuild) |
| Probe below `min_score` (stage 5) | Stale embedding cache, or `min_score` retuned above the 2/60 hybrid ceiling | Clear cache: `python -m retrieval.clear_cache --apply`; confirm `min_score` is still RRF-scale (0.028 ≤ value ≤ ~0.033), not a cosine value |
| Only one leg contributes (stage 5) | BM25 file missing/empty, or semantic reader failing | Check `index/bm25.json` exists and is non-empty; rebuild; check chroma dir |
| Wrong source on a probe | Corpus content changed; probe phrasing drifted from headings | Update the corpus, or update `PROBES` in `doctor.py` if the corpus legitimately changed |
| Empty chunks (stage 4) | Corpus file with blank sections; chunker over-splitting | Inspect the offending source; adjust `chunk_size`/`chunk_overlap` in config |
| Duplicate chunks (WARN) | Repeated content across corpus files | Deduplicate the corpus; not fatal but hurts ranking |

### Step 3 — Save a baseline (optional)

After a known-good run, snapshot it so future runs can flag drift:

```bash
python3 .claude/skills/index-doctor/doctor.py --json > /tmp/index_baseline.json
# later:
python3 .claude/skills/index-doctor/doctor.py --baseline /tmp/index_baseline.json
```

---

## Verify

```bash
bash .claude/skills/index-doctor/verify.sh
```

Rebuilds the index from every file under the committed `data/corpus/` and
runs the full probe set — a richer index-health superset of
`tests/ci_rag_smoke.py` (which, unlike this, walks the production gate).
Skips cleanly (exit 0) when retrieval deps aren't installed; the CI
`verify-skills` leg installs the full env and runs it for real.

---

## Guardrails

- **This skill rebuilds an artifact, not source.** The index (`index/`) and the
  embedding cache (`.emb_cache/`) are regenerable — safe to delete and rebuild.
  It never touches `data/corpus/` content, `data/personality/soul.md`, or config
  values.
- **`min_score` is RRF-scale.** If a probe fails the floor, do NOT "fix" it by
  moving `min_score`; above ~0.033 nothing can pass and the keyword-only
  degrade always misses. Diagnose the retrieval, not the threshold. The same
  goes for `min_semantic_score`: no cosine floor separates look-alikes from
  real paraphrases (CLAUDE.md §4).
- **Do not change probe expectations to make a run pass** unless the corpus
  genuinely changed, or the probe's wording was a paraphrase a chunking change
  made unstable (the DoS gotcha below). A failing probe whose wording still
  matches the corpus is a real regression.
- Rebuilding respects the configured `vector_backend`. For `pgvector`, count
  parity is skipped (WARN) — validate that backend against its own store.

## Gotchas

- **First run with no index does not auto-build at boot.** `/query` returns
  503 `INDEX_NOT_FOUND` until the index exists; build it with the indexer,
  `--rebuild` here, or the console's `POST /index/build` (loopback +
  same-origin, builds in place and reloads retrieval without a restart).
- **Stale `.emb_cache`.** Embeddings are cached; after model or corpus changes,
  clear it (`python -m retrieval.clear_cache --apply`; without `--apply` it
  is a dry run) before trusting scores.
- **`chunk_overlap >= chunk_size` raises ValueError** in the indexer — preflight
  catches this before the rebuild wastes time.
- **Hermetic dirs.** The probe path needs `data/personality/soul.md` and
  writable `index/`, `logs/` — `verify.sh` creates them non-destructively, same
  as the CI hermetic prep.
- **Score magnitudes are small.** A hit ranked first in both legs scores
  exactly 2/60 ≈ 0.0333, so every passing top score sits between 0.028 and
  0.0333; that is a strong hit, not a weak one.
- **The DoS probe is near-verbatim.** `doctor.py` asks what CyClaw uses for
  rate limiting to protect against DoS attacks — the overview bullet, and the
  same sentence `tests/ci_rag_smoke.py` asserts. A "request-flood denial of
  service" paraphrase ranks `AI-insights-.md`'s Cloudflare DDoS passage first
  once chunks are sized in embedder tokens (that passage used to fall past
  the model's 254-token window). `ci_rag_smoke` records that paraphrase class
  as a known gap; do not point this probe back at it.
