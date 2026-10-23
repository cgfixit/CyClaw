---
name: cyclaw-advisor
description: "Give read-only CyClaw architecture, operations or design advice from the inspected checkout and current configuration. Use for routing, retrieval, auth, memory, MCP or platform questions; fixes require an implementation request. Agentic coding loop and sandbox were removed 2026-10-18."
---

# Advise on CyClaw

Record the inspected SHA and deployment/configuration. Fetch current origin/main for upstream advice; distinguish that from the running checkout for troubleshooting. Use `AGENTS.md`, relevant `CLAUDE.md` sections and `INVARIANTS.md` for policy, then trace actual callers. Do not infer behavior from old audits or feature names. Code and `config.yaml` always win.

Pinned awareness to origin/main @ `34b44e1197b24cace55194d0ac3ccc82a6815266` (2026-10-20). Refresh before use.

| Question | Primary source |
| --- | --- |
| Retrieval and answer routing | `graph.py`, `retrieval/hybrid_search.py`, `retrieval/rerank.py`, `config.yaml` |
| Model destinations and consent | `utils/endpoint_trust.py`, `llm/client.py`, gateway client construction and graph routers |
| Auth, peer/origin and CSRF | `gate.py`, `gate_auth.py`, `utils/authn_manager.py`, `utils/console_session.py` |
| Soul or memory | `utils/personality.py`, `utils/personality_db.py`, `gate_memory.py`, `docs/memory/README.md` |
| Audit and observation | `utils/logger.py`, `utils/numbat_emitter.py`, `metrics.py` |
| Out-of-band connectors | `agentic/fsconnect/`, `agentic/netconnect/` (shipped off); see `docs/agentic/AGENTIC_README.md`. Coding loop, sandbox, skills registry and sqlconnect removed 2026-10-18. |
| MCP | `mcp_hybrid_server.py`: sanitized retrieval; no generation/sampling |
| Installation/platforms | [Environment source map](CyClaw-environment.md) |

Revalidate consequential details: cosine, RRF and reranker logits have different gates; shipped reranker threshold is shadow mode. Both local answer nodes check destinations; operator host trust is separate from cloud consent. Shipped hybrid and enabled providers do not authorize an external answer. Auth, memory and remaining agentic masters remain distinct from any armed flags.

I6 is direct import isolation between core modules (`gate.py`, `graph.py`, etc.) and `agentic/`; guardrail and memory bridges can run in-process. No process sandbox exists after the 2026-10-18 removal. Audit JSONL is authoritative and synchronous; Numbat is a derived fail-soft projection. Inspect actual source before claiming network confinement, denial on degradation or durable audit. Bot patches that touch CI, hooks, agent config, locks or protected files are refused.

For PR advice inspect the actual diff, current head/base, relevant open overlaps and CI/skips. Separate implemented behavior, shipped defaults, operator opt-ins, static evidence, mocks and native/live evidence. Recommend a smallest next check when evidence is missing; do not implement or publish from an advice request.

## Trimmed / updated

- Removed claims of active agentic coding loop, real-repo writes, executor sandbox, or skills registry (deleted 2026-10-18).
- Clarified remaining out-of-band connectors ship disabled.
- Noted bot patch refusal security control.
- Enhanced with explicit post-removal I6 and no-sandbox statement.

## Enhanced scope

- Guidance on current memory governance (propose/apply with reason + scan) and MCP no-sampling.
- Distinction between core RAG surfaces and remaining optional connectors.
- Operator residual awareness for removed agentic surfaces.

Source always wins. Re-fetch origin/main before advising on upstream changes.
