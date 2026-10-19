---
name: cyclaw-advisor
description: "Give read-only CyClaw architecture, operations or design advice from the inspected checkout and current configuration. Use for routing, retrieval, auth, model or platform questions; fixes require an implementation request."
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
