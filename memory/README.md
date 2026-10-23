# `memory/` — optional facts + episodes store

Default-off SQLite+FTS5 store for facts and query episodes, with propose/apply
governance (non-empty human `reason` + injection scan on apply). Soul
(`data/personality/soul.md`) stays identity; this package is not soul mutation.

**Not** [`docs/memories/`](../docs/memories/) (sandbox session notes).
This package is the optional facts/episodes store on the RAG path.

Every `memory:` switch in `config.yaml` ships `false`. With defaults, `/query`
behavior matches pre-memory CyClaw. Optional hooks catch memory failures so
they do not fail `/query`; operator routes can still report store errors.

## Isolation

The seven modules in `tests/test_memory_isolation.py`, including all six core
modules and `retrieval/hybrid_search.py`, do not import `memory` at module load.
Routes live in `gate_memory.py` and lazy-import this package.

## Package map

| Module | Role |
|---|---|
| `store.py` | SQLite + FTS5, WAL, private file permissions, parameterized SQL; schema versioning, active-fact limits, transactional proposal application, and episode retention |
| `models.py` | `Fact`, `Episode`, `MemoryProposal` |
| `policy.py` | Reason required, size/tag limits, normalized injection scan; malformed regexes warn and are skipped |
| `retrieval_adapter.py` | Optional FTS fusion into hybrid search |
| `mirror.py` | `/memory/status` dict + `GET /query/export/html` builder |
| `flags.py` | Resolves `memory.facts.retrieval_enabled`; honors the legacy `facts.enabled` name with a one-time warning |
| `selftest.py` | `python -m memory.selftest` |

Episodes keep keyed query fingerprints by default, but also keep redacted
answer summaries. `episodes.store_raw_query` separately enables redacted raw
query storage. Fact retrieval needs all three switches: the memory master,
`facts.retrieval_enabled`, and `retrieval_fusion.enabled`. Disabling retrieval
does not erase stored facts or prevent governed proposal application.

## Operator contract

Enablement steps, HTTP table (`/memory/*`, `/query/export/html`), and
invariants: [`docs/memory/README.md`](../docs/memory/README.md).
Design: [`docs/memory/IMPLEMENTATION_PLAN.md`](../docs/memory/IMPLEMENTATION_PLAN.md).
