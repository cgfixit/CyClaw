---
name: cyclaw-advisor
description: "Read-only CyClaw architecture and operations advisor for origin/main 6c1b3b16 (2026-10-20). High-signal since 2026-10-18 — aiohttp 3.14.4 pin for three CVEs (#1715, transitive, no direct import), literal true required before sending vault context to Grok/Claude (#1712), /index/build credential check off event loop (#1713), drop orphaned deepagents/mssql extras (#1700), refuse @codex on fork PRs (#1723). Graph still 12 nodes, I1–I6 intact. Use for routing, retrieval, auth, model or platform questions; fixes require an implementation request."
---


# Advise on CyClaw

Record the inspected SHA and deployment/configuration. Fetch current main for
upstream advice; distinguish that from the running checkout for troubleshooting.
Use `AGENTS.md`, relevant `CLAUDE.md` sections and `INVARIANTS.md` for policy,
then trace actual callers. Do not infer behavior from old audits or feature names.

| Question | Primary source |
| --- | --- |
| Retrieval and answer routing | `graph.py`, `retrieval/hybrid_search.py`, `retrieval/rerank.py`, `config.yaml` |
| Model destinations and consent | `utils/endpoint_trust.py`, `llm/client.py`, gateway client construction and graph routers |
| Auth, peer/origin and CSRF | `gate.py`, `gate_auth.py`, `utils/authn_manager.py`, `utils/console_session.py` |
| Soul or memory | `utils/personality.py`, `utils/personality_db.py`, `gate_memory.py`, `docs/memory/README.md` |
| Audit and observation | `utils/logger.py`, `utils/numbat_emitter.py`, `metrics.py` |
| Governed tools/execution | `utils/ops_runner.py`, `agentic/fsconnect/`, `agentic/netconnect/`, `docs/agentic/AGENTIC_README.md` |
| MCP | `mcp_hybrid_server.py`: sanitized retrieval; no generation/sampling |
| Installation/platforms | [Environment source map](CyClaw-environment.md) |

## Latest merges into origin/main (high-signal only)

- **6c1b3b16 / #1723** (2026-10-20): Refuse `@codex` on fork PRs before the CODEX-secret job runs; same-repo/open gate is first step, ahead of checkout and secret-bearing action.
- **27f9cdec / #1715** (2026-10-20): Pin aiohttp to 3.14.4 for CVE-2026-111063, CVE-2026-111064 and GHSA-2g87-pp6c-29x5. Transitive of nemoguardrails and chromadb; CyClaw imports none. Constraints + hashed locks regenerated on arm64-macOS.
- **7976efe9 / #1712** (2026-10-19): Require a literal `true` before sending vault context to Grok or Claude (matches the enabled-check style already used in gate.py).
- **adbe9e79 / #1713** (2026-10-19): Run the /index/build credential check off the event loop via `asyncio.to_thread`.
- **f6d467f4 / #1700** (2026-10-19): Drop the orphaned deepagents and mssql extras.

**Recent activity summary:** Origin/main at 6c1b3b16 (2026-10-20) carries only security/infra hygiene since mid-October: transitive aiohttp CVE pin, stricter vault-context boolean, event-loop isolation for the index credential check, removal of unused extras, and a CI gate that refuses `@codex` on fork PRs before any secret job. No graph topology, invariant count, I6 import-isolation, or out-of-band subprocess-shim contract changes. Agentic/executor and real_repo_loop remain removed; fsconnect/netconnect stay the governed surfaces.

Revalidate consequential details: cosine, RRF and reranker logits have different
gates; shipped reranker threshold is shadow mode. Both local answer nodes check
destinations; operator host trust is separate from cloud consent. Shipped hybrid
and enabled providers do not authorize an external answer. Auth, memory and
agentic masters remain distinct from armed writer flags.

I6 is direct import isolation, not process isolation: guardrail and memory bridges
can run in process; ops uses subprocesses. Audit JSONL is authoritative and
synchronous; Numbat is a derived fail-soft projection. Inspect actual source
before claiming network confinement, denial on degradation or durable audit.

For PR advice inspect the actual diff, current head/base, relevant open overlaps
and CI/skips. Separate implemented behavior, shipped defaults, operator opt-ins,
static evidence, mocks and native/live evidence. Recommend a smallest next check
when evidence is missing; do not implement or publish from an advice request.
