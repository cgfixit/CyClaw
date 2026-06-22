# CyClaw Python 3.12 Runtime Verification Report

**Date:** 2026-06-21
**Tested by:** Claude Code (automated sandbox + live server)
**Branches tested:** `main` @ a2fe40f and `!CyClaw-Agent` @ 7f24b64
**Python runtime:** 3.12.3 (`/usr/bin/python3.12`)
**Platform:** Linux 6.18.5 x86_64

---

## Executive Summary

**OVERALL STATUS: PASS — both branches fully verified on Python 3.12.**

Two independent verification methods were applied:

1. **Sandbox Runtime Verification** — fresh-venv, all 6 automated stages (deps, tests, RAG, gate.py check, API smoke bomb, terminal emulation)
2. **Live Server Smoke Test** — real uvicorn server, 6 endpoint checks exercising every major API path

Both `main` and `!CyClaw-Agent` passed every stage with zero failures.

---

## Test 1: Sandbox Runtime Verification

**Script:** `.claude/skills/sandbox-runtime-verification/verify.sh`
**Isolation:** Fresh `/tmp/cyclaw-verify-venv` (no carry-over state)
**Entry point:** `bash .claude/skills/sandbox-runtime-verification/verify.sh`

### Stage Results

| Stage | main @ a2fe40f | !CyClaw-Agent @ 7f24b64 |
|-------|:-:|:-:|
| **1 — 3.12 dependency install** | PASS | PASS |
| **2 — Unit + integration tests** | 322 passed | 318 passed |
| **3 — Emulated RAG query** | PASS | PASS |
| **4 — gate.py independent runtime check** | PASS | PASS |
| **5 — API smoke bomb (6 endpoints)** | 6/6 PASS | 6/6 PASS |
| **6 — terminal.html API emulation** | PASS | PASS |

### Stage 1 — Dependency Install

Installation order (CVE-2025-32434 mitigation):

```bash
pip install torch==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt --ignore-installed PyYAML
```

- **Conflicts:** 0 on both branches
- **constraints.txt:** full transitive tree respected
- **torch:** 2.6.0+cpu (CVE-2025-32434 mitigated — `weights_only=True` bypass patched)
- **ChromaDB:** 1.5.6 embedded (CVE-2026-45829 accepted per threat model: PersistentClient only)

### Stage 2 — Unit + Integration Tests

```bash
GROK_API_KEY=dummy python -m pytest tests/ -q --tb=short --continue-on-collection-errors
```

| Branch | Passed | Failed | Errors |
|--------|--------|--------|--------|
| `main` | **322** | 0 | 0 |
| `!CyClaw-Agent` | **318** | 0 | 0 |

The 4-test difference reflects agentic test modules present on `main` but not yet
on `!CyClaw-Agent` — both counts are fully green with zero failures.

Test modules covered:
`test_gate`, `test_graph`, `test_hybrid_search`, `test_personality`,
`test_personality_changes`, `test_sanitizer`, `test_audit`, `test_rate_limit`,
`test_mcp_server`, `test_security`, `test_telemetry_kill`, `test_stemmer`,
`test_embeddings`, `test_health`, `test_indexer`, `test_metrics`, `test_client`,
`test_rag_integration`, `test_agentic_*` (7 modules), `test_sync_*` (5 modules),
`test_conftest_fixtures`

### Stage 3 — Emulated RAG Query (ChromaDB + BM25, no LLM)

```bash
GROK_API_KEY=dummy python tests/ci_rag_smoke.py
```

- **Query:** "What fusion method does CyClaw use?"
- **Corpus:** `data/corpus/cyclaw_overview.md` + `data/corpus/CustomDataFiles.MD`
- **Result:** Vault hit — top RRF score >= `retrieval.min_score` (0.028)
- **Confirms:** ChromaDB semantic + BM25Okapi keyword + RRF fusion (k=60) pipeline operational
- **LLM required:** No — retrieval-only assertion

### Stage 4 — gate.py Independent Runtime Check

```bash
GROK_API_KEY=dummy python .claude/skills/sandbox-runtime-verification/gate_runtime_check.py
```

Assertions verified on both branches:

| Check | Result |
|-------|--------|
| `gate.py` imports cleanly (no missing deps) | PASS |
| `gate.app` is a FastAPI instance | PASS |
| Telemetry-kill env vars set pre-import | PASS |
| `/health` endpoint registered | PASS |
| `/query` endpoint registered | PASS |
| `/soul` endpoint registered | PASS |
| `/soul/propose` endpoint registered | PASS |
| `/soul/apply` endpoint registered | PASS |
| `/soul/reload` endpoint registered | PASS |
| `/` (root) endpoint registered | PASS |
| `gate.main()` is callable | PASS |

No LM Studio or live server required for this stage.

### Stage 5 — API Smoke Bomb (6 Endpoints)

Live server started via `uvicorn gate:app --host 127.0.0.1 --port 8787`, then:

| # | Endpoint + Scenario | Expected | Result |
|---|---------------------|----------|--------|
| 1 | `GET /health` | HTTP 200, `index_ready: true`, `graph_ready: true` | PASS |
| 2 | `POST /query` vault-hit query | HTTP 200, RRF retrieval results | PASS |
| 3 | `POST /query` offline path (`user_confirmed_online: false`) | HTTP 200, `offline_best_effort` routing | PASS |
| 4 | `POST /query` prompt injection attempt | HTTP 400 (31-pattern filter blocks) | PASS |
| 5 | `GET /soul` | HTTP 200, soul content + version returned | PASS |
| 6 | `GET /static/terminal.html` | HTTP 200, valid HTML, 30 KB | PASS |

### Stage 6 — terminal.html API Emulation

Emulates the full JS fetch lifecycle of the terminal UI against the live server.
Verified endpoint flows: `health`, `vault-hit`, `vault-miss to offline_best_effort`, `soul`.
All flows matched expected responses.

---

## Test 2: Live Server Smoke Test (/run-cyclaw)

**Entry point:** `bash .claude/skills/run-cyclaw/smoke.sh` (Python 3.12 venv activated)
**Server:** `uvicorn gate:app --host 127.0.0.1 --port 8787`
**API tested with:** Python `requests` library, full assertion suite

### Results — main @ a2fe40f

| # | Check | HTTP Code | Result | Notes |
|---|-------|-----------|--------|-------|
| 1 | `GET /health` | 200 | PASS | `status: degraded` (expected: LM Studio absent), `index_ready: true`, `graph_ready: true`, `embeddings_local: healthy` |
| 2 | `POST /query` — vault hit | 200 | PASS | Query: "What fusion method does CyClaw use?" — RRF retrieval executed |
| 3 | `POST /query` — alternate query | 200 | PASS | Query: "Tell me about CyClaw's architecture" — routed correctly |
| 4 | `POST /query` — injection filter | 400 | PASS | Jailbreak attempt blocked by 31-pattern sanitizer |
| 5 | `GET /soul` | 200 | PASS | Soul **v5**, 2,252 chars, `source: data/personality/soul.md` |
| 6 | `GET /static/terminal.html` | 200 | PASS | 30,735 bytes, valid HTML5 |

**Live server summary: 6/6 PASS**

### Results — !CyClaw-Agent @ 7f24b64

| # | Check | HTTP Code | Result | Notes |
|---|-------|-----------|--------|-------|
| 1 | `GET /health` | 200 | PASS | `status: degraded`, `index_ready: true`, `graph_ready: true` |
| 2 | `POST /query` — vault hit | 200 | PASS | RRF retrieval executed |
| 3 | `POST /query` — alternate query | 200 | PASS | Correct routing |
| 4 | `POST /query` — injection filter | 400 | PASS | Jailbreak blocked |
| 5 | `GET /soul` | 200 | PASS | Soul **v3**, 2,252 chars |
| 6 | `GET /static/terminal.html` | 200 | PASS | 30,735 bytes, valid HTML5 |

**Live server summary: 6/6 PASS**

---

## Branch Comparison

| Metric | `main` | `!CyClaw-Agent` |
|--------|--------|-----------------|
| Commit | a2fe40f | 7f24b64 |
| Latest change | eBPF/seccomp profiles + hardening docs | CLAUDE.md development workflow enhancements |
| Tests passing | 322 | 318 |
| Soul version | v5 | v3 |
| Dependency conflicts | 0 | 0 |
| Sandbox stages passed | 6/6 | 6/6 |
| Live endpoints passed | 6/6 | 6/6 |
| Regressions from CLAUDE.md change | — | 0 |

---

## Key Findings

### 1. Zero Regressions from CLAUDE.md Enhancements

`!CyClaw-Agent` added comprehensive development workflow documentation to `CLAUDE.md`
(setup, build/lint commands, test commands, entry points, telemetry kill switch,
configuration checklist). All 318 tests remain green — no breakage.

### 2. Hybrid Retrieval Pipeline Confirmed Operational

ChromaDB (semantic, `all-MiniLM-L6-v2`, 384d) + BM25Okapi (keyword, Porter stemming)
+ RRF fusion (k=60) is fully functional. A minimal 2-file sandbox corpus is sufficient
to generate a vault hit above the 0.028 min_score threshold.

### 3. Security Gates Active

- 31-pattern prompt injection filter in `utils/sanitizer.py` blocks jailbreak attempts (HTTP 400)
- Rate limiting (60 req/min per IP) compiled and ready
- Audit convergence path writes to `audit.jsonl`
- Telemetry kill vars set at gate.py import time — no phone-home

### 4. Graceful Degradation Without LM Studio

`/health` returns `status: degraded` (not `down`) when LM Studio is absent.
`index_ready: true` and `graph_ready: true` confirm the system is operational.
Queries route to `offline_best_effort` as designed. LM Studio is optional.

### 5. Soul Governance Intact

Both branches load `data/personality/soul.md` cleanly. Soul version differs
(v3 on `!CyClaw-Agent`, v5 on `main`) due to commit history, not mutation.
No autonomous modifications were made during testing.

### 6. CVE Posture Unchanged

- `torch==2.6.0+cpu` — CVE-2025-32434 mitigated (minimum safe version post-patch)
- `chromadb==1.5.6` — CVE-2026-45829 accepted (PersistentClient only, no HTTP client)
- Both consistent with the documented threat model in `pyproject.toml`

---

## Environment Notes

- `status: degraded` in `/health` is expected and normal without LM Studio running.
- `TELEMETRY KILL` messages on startup are intentional — `gate.py` blocks LangChain,
  Chroma, and OTel phone-home hooks before any SDK import.
- `GROK_API_KEY=dummy` satisfies startup env check in `mode: offline`; the key is
  never validated unless Grok is actually called.

---

## Verification Artifacts

| Artifact | Path |
|----------|------|
| Verify script | `.claude/skills/sandbox-runtime-verification/verify.sh` |
| gate.py check script | `.claude/skills/sandbox-runtime-verification/gate_runtime_check.py` |
| RAG smoke script | `tests/ci_rag_smoke.py` |
| This report | `tests/VERIFICATION_REPORT_3.12.md` |

---

*Generated by Claude Code — 2026-06-21*
