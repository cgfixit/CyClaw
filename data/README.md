# `data/` — runtime state (mostly governed, partly generated)

Operator data and server state. Nothing here is code; several files are
**governed artifacts** with write rules — read this before editing anything
by hand.

Python wheels and source distributions exclude this entire directory, including
the example corpus and any operator-edited soul. A package install needs an
operator-supplied corpus before indexing; the gateway creates its default soul
when none exists. A Git checkout retains the committed examples.

| Path | What it is | Write rules |
|---|---|---|
| `corpus/` | The RAG knowledge base: Markdown/text documents ingested by `python -m retrieval.indexer`. Add/edit files here, then reindex — the server never picks up corpus changes on its own. | Operator-managed content; never add credentials or unrelated private files. Chunks are sanitized at ingestion. The indexer uses overlapping embedder-token windows with the shipped config, not Markdown section boundaries. |
| `personality/soul.md` | The soul file — CyClaw's persona/behavior contract, capped at `personality.soul_max_chars` (8000). | Use `/soul/propose` then `/soul/apply`; apply requires a human `reason`, scans for injection, and writes atomically. Restore re-applies the vetted `.bak` with an advisory scan. Startup drift recovery and `/soul/reload` adopt on-disk content without scanning (see `INVARIANTS.md` Rule 5). A missing soul self-initializes at boot. |
| `personality/cyclaw_soul.db` | Soul version history + SHA-256 drift baseline (SQLite; Postgres via `CYCLAW_DB_URL`). The newest `soul_versions` row is the drift baseline — there is no hash constant in code. | Managed by `utils/personality_db.py`; don't edit. |
| `agentic/` (legacy) | Left behind by the agentic coding layer removed in October 2026: the old skills registry, real-repo `workspaces/` clones and run records, and harness-optimizer runs. No current code reads or writes it; a fresh clone has none of it. | **Treat old `workspaces/` as secret-bearing** — a clone there holds whatever its target repository contained. Delete the directory once you no longer need its run records; never add anything under it to the corpus. |
| `auth/cyclaw_auth.db` | Per-user auth store: accounts, sessions, device tokens (SQLite; Postgres via `CYCLAW_AUTH_DB_URL`). Created only when `auth.enabled` is turned on. | **Holds scrypt password hashes and hashed session/CSRF/device tokens.** Never commit it, copy it off-box, or hand-edit it. Manage accounts through `cyclaw-user` or the `/auth/*` routes. |
| `memory/cyclaw_memory.db` | Optional facts/episodes store (SQLite + FTS5) for the default-off memory subsystem. Absent until `memory.enabled` is turned on. | Managed by `memory/store.py`: facts through governed proposals, episodes automatically when enabled. It can contain fact text and redacted answer summaries; don't commit or hand-edit it. |
| `fsconnect_rate.db` | Per-root write-rate limiter state for the filesystem connector. Deliberately separate from the gateway limiter's database. | Managed by `agentic/fsconnect/`; don't edit. |
| `budget/external-calls.db` | Persistent UTC daily/monthly attempt counts shared by Grok and Claude, including retries. | Managed by `utils/external_budget.py`; deleting or editing it would reset the spending guard's accounting. |
| `privacy/query-hmac.key` | Private key used for persistent HMAC-SHA256 query fingerprints when `CYCLAW_QUERY_FINGERPRINT_KEY` is not supplied. Created on first use, not merely at gateway boot. | Managed by `utils/logger.py`; never commit or expose it. Replacing it changes fingerprints and breaks joins with historical query records. |

Not in this directory but adjacent in spirit: the retrieval indices live in
`index/` (regenerable — rebuild with `python -m retrieval.indexer`), the
embedding and reranker model cache in `.emb_cache/` (regenerable —
`python -m retrieval.clear_cache`), and the audit log at
`logs/audit.jsonl` (append-only JSONL; query text stored as keyed HMAC-SHA256
fingerprints by default; disabling `logging.audit_fields.include_query_hash` retains
raw query text subject to redaction). The per-user launcher state (venv, `.env`)
is **not** here — it lives under `~/.CyClaw` / `%USERPROFILE%\.CyClaw`.

## Related

- Retrieval/index mechanics: [`retrieval/README.md`](../retrieval/README.md)
- Soul governance invariant (I5): repo-root `INVARIANTS.md`
- Dropbox sync of `corpus/`: [`docs/SYNC_README.md`](../docs/SYNC_README.md)
