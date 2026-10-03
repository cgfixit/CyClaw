# CyClaw memory subsystem

Optional, **default-off** facts + episodes store with propose/apply governance and optional retrieval fusion.

> **Not** `docs/memories/` (sandbox notes). This feature lives under `docs/memory/` and package `memory/`.

## Defaults

Every switch in `config.yaml` → `memory:` is **false**. With defaults, behavior is identical to pre-memory CyClaw.

`memory.facts.max_active` limits new active facts. Before #1523 merged,
updating an inactive fact reactivated it without checking that limit. Merged PR
[#1523](https://github.com/cgfixit/CyClaw/pull/1523) (shipped 2026-10-03) closes that gap for direct
updates and proposal application.

## Enable progressively

1. `memory.enabled: true` + `episodes.enabled: true` — stage query episodes (hashed query by default).
2. `propose_apply.enabled: true` + establish [operator access](../../README.md#api-key-setup-soul-mutations) — use `/memory/propose` then `/memory/apply`.
3. `facts.retrieval_enabled: true` + `retrieval_fusion.enabled: true` — FTS fact hits fuse into `hybrid_search` as `retrieval_mode="memory"`.
4. `export_html.enabled: true` — `GET /query/export/html` (auth-gated).

`consolidation.enabled` is a **stub** and must stay false in v1.

Step 3 comes after step 2 on purpose: facts are proposed, applied and verified
**before** they are exposed to retrieval. `facts.retrieval_enabled` gates only
that last exposure — it is deliberately not a master switch for facts, and
turning it off does not stop persistence. **No switch gates fact persistence at
all**: `memory.enabled` + `propose_apply.enabled` is the whole story, so a fact
that has been applied stays stored and readable via `GET /memory/facts`
regardless. (This is why the flag was renamed from `facts.enabled`, which read
as a master switch that never existed. The old name still works and logs a
one-time warning — see `memory/flags.py`.)

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
| GET | `/memory/facts` | 404 if master off |
| GET | `/memory/episodes` | 404 if master off |
| GET | `/memory/proposals` | propose_apply gate |
| POST | `/memory/propose` | body: action, content/fact_id, reason |
| POST | `/memory/apply` | body: proposal_id, reason |
| POST | `/memory/reject` | body: proposal_id, reason |
| GET | `/query/export/html` | export_html gate |

## Selftest

```bash
python -m memory.selftest
```

## Design authority

See [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md).
