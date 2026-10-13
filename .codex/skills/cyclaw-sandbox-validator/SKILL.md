---
name: cyclaw-sandbox-validator
description: >
  Grok-sandbox-adapted CyClaw validator. Evidence-backed static and mock verification of origin/main against the Claude CyClaw-Sandbox baseline, limited to what pure Python in the code_execution REPL can test (no internet, no long-running servers, no OS confinement, no external installs, no real models). Verifies AST invariants (I1-I6, G1-G5), shipped config contract, mock Tier-0 12-node graph routing for the 5 sample queries, sanitizer/banned-phrase coverage, soul write-path governance, triple-gate external logic, audit convergence, API-key fail-closed, query hashing. Explicitly SKIPs everything requiring live HTTP, browser JS, real Chroma/embeddings, Ollama/NeMo runtime, platform installers, Docker/bwrap, OS scheduler glue, or network.
disable-model-invocation: true
---

# CyClaw Sandbox Validator (Grok)

**The contract, stated precisely.** A green run means the static AST invariants hold, the shipped `config.yaml` matches the hybrid + enabled triple-gate posture, mock routing produces the expected paths for the five sample queries at Tier 0, the sanitizer covers the banned-phrase floor, soul writes require a non-empty reason plus injection scan (reload does not), and core isolation (I6) is intact for the pinned SHA. It does **not** mean live generation, real retrieval persistence, browser surfaces, installers, NeMo engine, or any out-of-band runtime was exercised. Code and `config.yaml` always win over this document.

Pinned to origin/main @ `29f639a4cc683bddfea399b8a0f88039f1366518` (2026-10-13). Refresh the source before each run; this is evidence, not a permanent pin. Baseline adapted from `.claude/skills/CyClaw-Sandbox/SKILL.md` (reconciled ~`663a8bb` same day) with everything untestable in the Grok REPL removed.

## Operator map — Grok-executable ladders only

Complementary to the full Claude ladders B–F. These prove only what the code_execution sandbox can execute.

| Ladder | What it proves | How (code_execution) | Does **not** prove |
|--------|----------------|----------------------|--------------------|
| Static invariants | I1–I6, G1–G5 (RAG-first entry, topology, triple-gate construction, audit convergence, soul governance, module isolation, telemetry kill order, auth fail-closed, sanitizer phrase coverage, BM25 JSON, MCP no-sampling) | Fetch raw `check_invariants.py` + key modules (`graph.py`, `gate.py`, `config.yaml`, `mcp_hybrid_server.py`); exec AST/string checks | Runtime behavior, live servers |
| Config contract | Shipped defaults: `app.mode: hybrid`, `models.grok.enabled`/`claude.enabled: true`, `auth.enabled: false`, `agentic.enabled: false`, `memory.enabled: false`, `guardrails.enabled: true`, `retrieval.min_score: 0.028`, `min_semantic_score: 0.30`, `security.api_key_optional: false`, `policy.fallback.pre_action_hook.enabled: false`, banned_patterns floor, loopback bind | Parse `config.yaml` (text or yaml if available) | Dynamic overrides, runtime enforcement |
| Mock routing (Tier 0) | 5-query expected paths: vault hits → `local_llm`; misses → `user_gate`; online only after triple gates + user confirm + available client; all paths → `guardrail_output` → `audit_logger` → END | Pure-Python simulation extracted from `graph.py` routers | Real LLM output, live Chroma, embeddings |
| Sanitizer / soul / redaction | Phrase coverage, `apply_evolution` requires reason + scan, reload unscanned, query hashing when enabled, API-key fail-closed patterns, `sk-ant-*` redaction | String/AST scans on sanitizer + personality modules | Live injection success rate, real corpus |

## Explicit SKIP list (Grok cannot test)

- Live `uvicorn` / `gate.py` startup, `/health`, `/query` HTTP probes, rate limits, CORS, loopback bind enforcement at runtime
- `verify.sh`, `smoke.sh`, `gate_runtime_check.py`, `terminal_emulation.py`, platform smokes (`windows-smoke.ps1`, `macos-smoke.sh`)
- Browser JS / `browser_render_check.py` / terminal console rendering
- Real Ollama daemon, Tier 1/2 realism, real sentence-transformers / Chroma persistence
- NeMo Guardrails engine runtime (config presence only)
- Docker, bubblewrap, Seatbelt, AppArmor, OS scheduler glue (launchd, Task Scheduler)
- Full auth lifecycle (bootstrap, session cookie, CSRF, TLS cert generation, RBAC at runtime)
- Telegram / OpenTweet media or live channel runs
- Agentic real-repo writes, GitHub publication, fsconnect/sqlconnect live
- Any network call, paid API, real credentials

## Steps (for the code_execution tool)

1. Record the target SHA (`29f639a...` or fresher HEAD via GitHub tools). Use dummy keys only (`GROK_API_KEY=dummy`).
2. Fetch raw sources needed (graph.py, gate.py, config.yaml, utils/sanitizer.py, personality modules, check_invariants.py, mcp_hybrid_server.py) via GitHub raw or get_file_contents. Load into the REPL as strings.
3. Run static invariant checks (adapt or exec the AST logic from check_invariants.py). Assert node count == 12, entry == "retrieve", audit_logger → END, I6 no cross-imports, G2/G3/G5.
4. Assert config contract values listed above.
5. Simulate the five query routes with pure logic (vault-hit local, miss → user_gate, confirm-only fallback). Confirm triple-gate conditions are required.
6. Scan for soul write-path scan, query-hash default, redaction patterns.
7. Emit a report: SHA, PASS/FAIL/SKIP per lane, evidence snippets (no secrets, no private corpus). A SKIP is not a pass.

## Gotchas

- The REPL has no internet; do not attempt `git clone`, `pip install`, or live server starts. Fetch via the host tools first.
- Available libraries are limited (numpy, torch, sympy, etc.); do not rely on chromadb, sentence-transformers, fastapi, or NeMo.
- Numbers and node lists are derived from the live tree; if they disagree with this document, trust the tree.
- Recent post-663a8bb changes (memory.store import consistency, fsconnect depth bounds, agentic NaN score gates, bwrap version selection, egress classification) are covered by the static isolation and config checks where they touch invariants; otherwise marked SKIP.

## Strategic note

These checks pin the evolutionary stable strategies (RAG-first entry, triple-gate, audit convergence, I6 isolation) that history and game theory show separate contained local RAG from repeated injection/exfil failures in agentic tools. The trusted-operator loopback threat model remains the operating assumption; this skill does not expand the blast radius.
