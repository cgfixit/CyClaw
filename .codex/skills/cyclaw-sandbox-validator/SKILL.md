---
name: cyclaw-sandbox-validator
description: >
  Grok-sandbox-adapted CyClaw validator. Evidence-backed static and mock verification of origin/main against the Claude CyClaw-Sandbox baseline, limited to what pure Python in the code_execution REPL can test (no internet after fetch, no long-running servers, no OS confinement, no external installs, no real models, limited third-party libs). Verifies AST invariants (I1-I6, G1-G5), shipped config contract, mock Tier-0 12-node graph routing for the 5 sample queries, sanitizer/banned-phrase coverage, soul write-path governance, triple-gate external logic, audit convergence, API-key fail-closed, query hashing. Explicitly SKIPs everything requiring live HTTP, browser JS, real Chroma/embeddings, Ollama/NeMo runtime, platform installers, Docker/bwrap, OS scheduler glue, or network.
disable-model-invocation: true
---

# CyClaw Sandbox Validator (Grok)

**The contract, stated precisely.** A green run means the static AST invariants hold (I1–I6 + G1–G5), the shipped `config.yaml` matches the hybrid + enabled triple-gate posture (app.mode: hybrid, grok/claude.enabled: true, auth/memory/agentic off), mock routing produces the expected paths for the five sample queries at Tier 0, the sanitizer covers the banned-phrase floor, soul writes require a non-empty reason plus injection scan (reload does not), and core isolation (I6) is intact for the pinned SHA. It does **not** mean live generation, real retrieval persistence, browser surfaces, installers, NeMo engine, or any out-of-band runtime was exercised. Code, `config.yaml` and the tests on disk always win over this document.

Pinned to origin/main @ `522b3f721bbbf330329d2a49f7a687ce41d4c90f` (2026-10-13). Refresh the source before each run; this is evidence, not a permanent pin. Baseline adapted from `.claude/skills/CyClaw-Sandbox/SKILL.md` (Ladder L stages that are static or pure-Python mockable) with everything untestable in the Grok code_execution REPL removed. Surfaces reconciled against current main by fetching key files.

## Operator map — Grok-executable ladders only

Complementary to the full Claude ladders L/B–F. These prove only what the code_execution sandbox can execute after host-tool fetches.

| Ladder | What it proves | How (code_execution) | Does **not** prove |
|--------|----------------|----------------------|--------------------|
| Static invariants | I1–I6, G1–G5 (RAG-first entry, topology=policy via 4 routers, triple-gate construction, audit convergence, soul governance, module isolation of agentic/sync/guardrails/telegram/opentweet, telemetry kill order, auth fail-closed, sanitizer phrase coverage, BM25 JSON, MCP no-sampling) | Fetch raw `check_invariants.py` + key modules (`graph.py`, `gate.py`, `config.yaml`, `mcp_hybrid_server.py`, personality modules); exec AST/string checks or adapt the checker logic | Runtime behavior, live servers, real enforcement |
| Config contract | Shipped defaults: `app.mode: hybrid`, `models.grok.enabled`/`claude.enabled: true`, `auth.enabled: false`, `agentic.enabled: false`, `memory.enabled: false`, `guardrails.enabled: true`, `retrieval.min_score: 0.028`, `min_semantic_score: 0.30`, `min_rerank_score: null` (shadow), `security.api_key_optional: false`, `policy.fallback.pre_action_hook.enabled: false`, banned_patterns floor (~40), loopback bind, models.local_llm.model: qwen3.8:27b-mlx | Parse `config.yaml` (text or PyYAML if available) | Dynamic overrides, runtime enforcement, live client availability |
| Mock routing (Tier 0) | 5-query expected paths: vault hits → local_llm (via guardrail_input); misses → user_gate; online only after triple gates (hybrid + enabled + user_confirmed_online) + available client + pre_action_hook allow; all paths → guardrail_output → audit_logger → END; 12 nodes exact | Pure-Python simulation extracted from `graph.py` routers + path_maps (EXPECTED_NODES / edges from invariant checker) | Real LLM output, live Chroma, embeddings, generation quality |
| Sanitizer / soul / redaction | Phrase coverage (CONTRACT_PHRASES), `apply_evolution` requires reason + scan, reload unscanned, query hashing when enabled (HMAC default), API-key fail-closed patterns, `sk-ant-*` redaction | String/AST scans on sanitizer + personality modules | Live injection success rate, real corpus, browser console |

## Explicit SKIP list (Grok cannot test in sandbox)

- Live `uvicorn` / `gate.py` startup, `/health`, `/query` HTTP probes, rate limits (60/min), CORS, loopback bind enforcement at runtime, body-size 413, cross-site 403
- `local_audit.py` full stages 2–4 (run-the-code CLIs/selftests beyond import, swarm with doubles, live gate route contract)
- `verify.sh`, `smoke.sh`, `gate_runtime_check.py`, `terminal_emulation.py`, platform smokes (`windows-smoke.ps1`, `macos-smoke.sh`), browser_render_check
- Browser JS / terminal console rendering / auth_admin.js
- Real Ollama daemon, Tier 1 (`mock_ollama.py` HTTP) / Tier 2 realism, real sentence-transformers / Chroma persistence / indexer
- NeMo Guardrails engine runtime (config presence + enabled only)
- Docker, bubblewrap, Seatbelt, AppArmor, OS scheduler glue (launchd, Task Scheduler), agentic hard_sandbox
- Full auth lifecycle (bootstrap, session cookie, CSRF, TLS cert generation, RBAC at runtime, 503 while disabled)
- Telegram / OpenTweet media or live channel runs, fsconnect/sqlconnect live ops
- Agentic real-repo writes, GitHub publication
- Any network call, paid API, real credentials, model downloads
- Full pytest suites, coverage gate, CI jobs

## Steps (for the code_execution tool)

1. Record the target SHA (`522b3f7...` or fresher HEAD via GitHub tools). Use dummy keys only (`GROK_API_KEY=dummy`, `ANTHROPIC_API_KEY=dummy`).
2. Fetch raw sources needed (graph.py, gate.py, config.yaml, utils/sanitizer.py, utils/personality.py, .claude/skills/invariant-guard/check_invariants.py, mcp_hybrid_server.py) via github___get_file_contents or raw URLs. Load into the REPL as strings.
3. Run static invariant checks (adapt or exec the AST logic from check_invariants.py: EXPECTED_NODES == 12, entry == "retrieve", audit_logger → END, I6 no cross-imports of OUT_OF_BAND_PKGS, G1 kill order, G2/G3/G4/G5). Assert exact conditional targets via path_maps.
4. Assert config contract values listed above (hybrid mode, providers enabled, subsystems off, thresholds).
5. Simulate the five query routes with pure logic (vault-hit local via score_router → guardrail_input → local_llm; miss → user_gate; confirm-only fallback after triple gate + pre_action_hook). Confirm all paths converge at audit_logger.
6. Scan for soul write-path (reason + scan on apply, not reload), query-hash default, redaction patterns, banned phrase coverage.
7. Emit a report: SHA, PASS/FAIL/SKIP per lane, evidence snippets (no secrets, no private corpus). A SKIP is not a pass. Link to Claude Ladder L for full evidence.

## Gotchas

- The REPL has no internet after the host fetch; do not attempt `git clone`, `pip install`, or live server starts. Fetch via the host tools first.
- Available libraries are limited (numpy, torch, sympy, pandas, etc.); do not rely on chromadb, sentence-transformers, fastapi, langchain, NeMo, or yaml (fall back to text parse).
- Numbers and node lists are derived from the live tree; if they disagree with this document, trust the tree and re-fetch.
- Recent changes on main (memory import consistency, fsconnect depth, agentic score gates, bwrap selection, egress, reranker shadow mode, soul max chars, rate limit, etc.) are covered by the static isolation and config checks where they touch invariants; otherwise marked SKIP.
- Current main emits hybrid-posture notes; record them, do not suppress real failures.

## Strategic note

These checks pin the evolutionary stable strategies (RAG-first entry, topology=policy, triple-gate, audit convergence, I6 isolation, fail-closed keys) that history and game theory show separate contained local RAG from repeated injection/exfil failures in agentic tools. The trusted-operator loopback threat model remains the operating assumption; this skill does not expand the blast radius or claim microVM isolation.
