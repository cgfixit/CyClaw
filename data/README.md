# `data/` — runtime state (mostly governed, partly generated)

Operator data and runtime state. Follow each artifact's write rules.

| Path | What it is | Write rules |
|---|---|---|
| `corpus/` | Markdown/text knowledge base for `python -m retrieval.indexer`. Reindex after edits; changes are not loaded automatically. | Operator-managed content; never add credentials or unrelated private files. Chunks are sanitized at ingestion. The indexer uses overlapping embedder-token windows with the shipped config, not Markdown section boundaries. |
| `personality/soul.md` | The soul file — CyClaw's persona/behavior contract, capped at `personality.soul_max_chars` (8000). | Use `/soul/propose` then `/soul/apply`; apply requires a human `reason`, scans for injection, and writes atomically. Restore re-applies the vetted `.bak` with an advisory scan. Startup drift recovery and `/soul/reload` adopt on-disk content without scanning (see `INVARIANTS.md` Rule 5). A missing soul self-initializes at boot. |
| `personality/cyclaw_soul.db` | Soul history and SHA-256 baseline (newest `soul_versions` row; SQLite or Postgres via `CYCLAW_DB_URL`). | Managed by `utils/personality_db.py`; don't edit. |
| `agentic/` (legacy) | Removed October 2026: skills registry, `workspaces/` clones/run records, harness-optimizer runs. Unused by current code; absent in fresh clones. | **Old `workspaces/` may contain repository secrets.** Delete when no longer needed; never ingest into the corpus. |
| `auth/cyclaw_auth.db` | Per-user auth store: accounts, sessions, device tokens (SQLite; Postgres via `CYCLAW_AUTH_DB_URL`). Created only when `auth.enabled` is turned on. | **Holds scrypt password hashes and hashed session/CSRF/device tokens.** Never commit it, copy it off-box, or hand-edit it. Manage accounts through `cyclaw-user` or the `/auth/*` routes. |
| `memory/cyclaw_memory.db` | Optional facts/episodes store (SQLite + FTS5) for the default-off memory subsystem. Absent until `memory.enabled` is turned on. | Managed by `memory/store.py`: facts through governed proposals, episodes automatically when enabled. It can contain fact text and redacted answer summaries; don't commit or hand-edit it. |
| `fsconnect_rate.db` | Per-root write-rate limiter state for the filesystem connector. Deliberately separate from the gateway limiter's database. | Managed by `agentic/fsconnect/`; don't edit. |
| `budget/external-calls.db` | Persistent UTC daily/monthly attempt counts shared by Grok and Claude, including retries. | Managed by `utils/external_budget.py`; deleting or editing it would reset the spending guard's accounting. |
| `privacy/query-hmac.key` | Private key used for persistent HMAC-SHA256 query fingerprints when `CYCLAW_QUERY_FINGERPRINT_KEY` is not supplied. Created on first use, not merely at gateway boot. | Managed by `utils/logger.py`; never commit or expose it. Replacing it changes fingerprints and breaks joins with historical query records. |

Related state: retrieval indices in
`index/` (regenerable — rebuild with `python -m retrieval.indexer`), the
embedding and reranker model cache in `.emb_cache/` (regenerable —
`python -m retrieval.clear_cache`), and the audit log at
`logs/audit.jsonl` (append-only JSONL; query text stored as keyed HMAC-SHA256
fingerprints by default; disabling `logging.audit_fields.include_query_hash` retains
raw query text subject to redaction). Launcher state (venv, `.env`) lives under `~/.CyClaw` / `%USERPROFILE%\.CyClaw`.

## Related

- Retrieval/index mechanics: [`retrieval/README.md`](../retrieval/README.md)
- Soul governance invariant (I5): repo-root `INVARIANTS.md`
- Dropbox sync of `corpus/`: [`docs/SYNC_README.md`](../docs/SYNC_README.md)
