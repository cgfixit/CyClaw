---
name: cyclaw-advisor
description: "Give read-only CyClaw architecture, operations or design advice from the inspected checkout and current configuration. Current main HEAD ae767ed9c6ecd64112993462370433c81e03707c (2026-10-23): agent identity module deleted (#1755, hooks now enforce multi-vendor branch prefixes), security floors carried into conda lane + Apple Silicon leg (#1759), scoped Pillow acceptance (#1743), githooks aligned (#1741), bot patch refuse for CI/hooks/agent (#1734). Use for routing, retrieval, auth, model or platform questions; fixes require an implementation request."
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

## Latest merges into origin/main (high-signal since last skill refresh ~2026-10-19)

- 2026-10-23 #1759: Carry constraints.txt security floors into the conda lane (certifi/opentelemetry-api floors, aiohttp exact pin), add Apple Silicon conda leg, fix stale install docs (SYNC_README Torch omission, POSTGRES_BACKEND extras).
- 2026-10-23 #1755: Delete utils/agent_identity.py (obsolete after agentic loop removal); tracked .githooks/pre-commit and pre-push now enforce the canonical multi-vendor branch-prefix case list (grok/*, claude/*, CyClaw/*, etc.).
- 2026-10-23 #1743: Refresh audited dependencies; scoped acceptance of Pillow 12.3.0 image-codec advisories (fixed in 13, blocked by fastembed/nemoguardrails) until allowed — no CyClaw path decodes images.
- 2026-10-23 #1741: Align Git hooks with staged and published changes.
- 2026-10-20 #1734: Refuse bot patches that touch CI, hooks, agent config, locks or protected files (expanded path deny list).
- 2026-10-20 #1735: Gate zizmor at medium severity (prior medium/low findings cleared).

Recent activity summary: Dependency pins refreshed and security floors extended into the conda lane (with Apple Silicon coverage); agentic-system remnants cleaned (identity module deleted, hooks own branch-prefix and identity enforcement); CI surface hardened against automated patches on sensitive paths; install documentation corrected for platform Torch and constraints. Graph topology, 6 invariants / I6 import isolation, and out-of-band subprocess-shim contract remain unchanged. Never weaken the 6 invariants or I6.
