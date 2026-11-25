---
name: cyclaw-advisor
description: "Advise on CyClaw architecture, operations and platform behavior from the current checkout and effective config. Read-only unless the user requests implementation."
---

# Advise on CyClaw

Record the inspected SHA and deployment. Refresh main for upstream advice and identify the running checkout for troubleshooting. Use `AGENTS.md`, `CLAUDE.md` and `INVARIANTS.md` for contracts, then trace the owning source.

| Question | Start here |
| --- | --- |
| Retrieval and routing | `graph.py`, `retrieval/hybrid_search.py`, `retrieval/rerank.py`, `config.yaml` |
| Destination trust and consent | `utils/endpoint_trust.py`, `llm/client.py`, gateway clients and graph routers |
| Auth, origin and CSRF | `gate.py`, `gate_auth.py`, `utils/authn_manager.py`, `utils/console_session.py` |
| Soul and memory | `utils/personality.py`, `utils/personality_db.py`, `gate_memory.py`, `docs/memory/README.md` |
| Audit and metrics | `utils/logger.py`, `utils/numbat_emitter.py`, `metrics.py` |
| Governed tools | `utils/ops_runner.py`, `agentic/fsconnect/`, `agentic/netconnect/`, `docs/agentic/AGENTIC_README.md` |
| MCP | `mcp_hybrid_server.py` |
| Install and platform | [Environment source map](CyClaw-environment.md) |

Check the separate cosine, RRF and reranker gates. Distinguish shipped switches from effective operator opt-ins, local destination trust from external consent, and connector enablement from writer arming. I6 governs imports. Check subprocess and in-process bridges independently. Audit JSONL is synchronous and authoritative. Numbat is a fail-soft projection.

For PR advice, inspect exact-head diff, overlap and CI. Label static, mock, native and live evidence and name any material gap.
