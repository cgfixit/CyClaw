# CyClaw memory subsystem

Optional, **default-off** facts + episodes store with propose/apply governance and optional retrieval fusion.

> **Not** `docs/memories/` (sandbox notes). This feature lives under `docs/memory/` and package `memory/`.

## Defaults

Every `config.yaml` → `memory:` switch ships **false**.

`memory.facts.max_active` limits active facts, including reactivation of an
inactive fact by an update or proposal application.

## Enable progressively

1. `memory.enabled: true` + `episodes.enabled: true` — stage query episodes (keyed HMAC-SHA256 query fingerprints by default, plus redacted answer summaries and retrieval/model metadata).
2. `propose_apply.enabled: true` + establish [operator access](../../README.md#api-key-setup-soul-mutations) — use `/memory/propose` then `/memory/apply`.
3. `facts.retrieval_enabled: true` + `retrieval_fusion.enabled: true` — FTS fact hits fuse into `hybrid_search` as `retrieval_mode="memory"`.
4. `export_html.enabled: true` — `GET /query/export/html` (auth-gated).

Propose, apply, and verify facts before enabling retrieval.
`facts.retrieval_enabled` controls retrieval exposure only; disabling it does
not erase applied facts or prevent persistence and `GET /memory/facts` reads
while the memory master is on. Proposals additionally require
`propose_apply.enabled`. The legacy `facts.enabled` alias still works with a
one-time warning (`memory/flags.py`).

`episodes.store_raw_query` is a separate opt-in to store redacted query text.
Answer summaries are stored whenever episodes are enabled, even when raw
queries are off; the memory database and HTML export therefore remain
potentially sensitive. Episode retention uses `episodes.ttl_days`, pruned
every `episodes.prune_every` staged episodes, rather than a background timer.

## Invariants

- No top-level `import memory` in the seven modules listed by
  `tests/test_memory_isolation.py`, including all six core modules and
  `retrieval/hybrid_search.py`.
- Memory failures never fail `/query` (non-fatal hooks).
- Mutating routes must pass `require_api_key` and include a non-empty reason.
  Cookie-based credentials also require their CSRF header.
- Apply scans normalized text against the enforced soul patterns plus configured
  `policy.prompt_filter.banned_patterns` before fact write. Invalid regexes are
  skipped with a warning; config-pattern warnings identify the original list
  index. A successful apply does not prove malformed patterns ran.
- Soul (`personality`) remains identity, not memory.

## Operator API

| Method | Path | Notes |
|--------|------|--------|
| GET | `/memory/status` | Always 200 + flags with operator access |
| GET | `/memory/facts` | Active facts; 404 if master off; `limit`/`offset` pagination |
| GET | `/memory/episodes` | Recent episodes; 404 if master off; `limit`/`offset` pagination |
| GET | `/memory/proposals` | propose_apply gate |
| POST | `/memory/propose` | body: action, content/fact_id, reason |
| POST | `/memory/apply` | body: proposal_id, reason |
| POST | `/memory/reject` | body: proposal_id, reason |
| GET | `/query/export/html` | Master + export_html gates; escaped HTML of recent episodes and active facts, not a complete database backup |

## Selftest

```bash
python -m memory.selftest
```

## Implementation and design

Current behavior is implemented in [`gate_memory.py`](../../gate_memory.py)
and [`memory/`](../../memory/README.md). See
[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) for the design history.
