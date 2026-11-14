---
name: cyclaw-advisor
description: "Give read-only CyClaw architecture, operations or design advice from the inspected checkout and current configuration (verified against origin/main HEAD 0f9c83dc84a054b5ec066ea451fdde1be1a51a65 on 2026-11-14; high-signal: otel-api 1.45.2 CVE pin #1834, fsconnect quota corrupt non-int/neg #1832, rate-limit wrongly-shaped row as corrupt #1823, OpenTweet vault-hit only #1822, atomic_write for telegram/rclone writers #1830, ponytail audit #1827). Use for routing, retrieval, auth, model or platform questions; fixes require an implementation request."
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
fsconnect/netconnect masters remain distinct from armed writer flags.

I6 is direct import isolation, not process isolation: guardrail and memory bridges
can run in process; ops uses subprocesses. Audit JSONL is authoritative and
synchronous; Numbat is a derived fail-soft projection. Inspect actual source
before claiming network confinement, denial on degradation or durable audit.

For PR advice inspect the actual diff, current head/base, relevant open overlaps
and CI/skips. Separate implemented behavior, shipped defaults, operator opt-ins,
static evidence, mocks and native/live evidence. Recommend a smallest next check
when evidence is missing; do not implement or publish from an advice request.

## Latest merges into origin/main

- **0f9c83d** (2026-11-14, #1834): [security] Bump opentelemetry-api to 1.45.2 for CVE-2026-126360. Constraints/locks/env.yml pin raised; conda pip list adjusted. Telemetry dependency posture. No topology/invariant change.
- **318a3a5** (2026-11-14, #1832): [security] Treat fsconnect quota ledger with negative or non-int counts as corrupt. load() rejects, forces recompute. Tightens OOB writer path against crafted ledger. No I6 import change.
- **b840d9e** (2026-11-10, #1823): [fix] Treat wrongly-shaped persisted rate-limit row as corrupt instead of crashing. _load_from_db validates list-of-finite-numbers; else reset window. Request-path robustness. No invariant impact.
- **a39cda7** (2026-11-10, #1822): [security] Refuse OpenTweet posts whose answer did not come from a vault hit. Model gate now allowlist of local; offline-best-effort blocked. Strengthens local-only for OpenTweet. 
- **f90c88d** (2026-11-14, #1830): [fix] Route Telegram state and rclone filter writers through write_atomic. Shared durability/cleanup. Affects telegram/sync paths.
- **401a5a1** (2026-11-14, #1827): [docs] Add the 2026-11-10 ponytail audit. Read-only dead-code/duplication review. No code change.

## Recent activity summary

As of 2026-11-14 HEAD 0f9c83dc: graph remains 12 nodes (retrieve entry, audit_logger convergence via guardrail_output, pre-action hooks); 6 core invariants + I6 import isolation unchanged (no new OOB packages). High-signal activity: dependency pin for otel CVE, fsconnect quota robustness against corrupt ledger, rate-limit persistence shape validation to prevent crash, OpenTweet vault-hit enforcement, atomic writes for telegram/rclone, and ponytail audit docs. No EXECUTION_ENABLED, candidate-diff, or agent_identity topology changes. Re-inspect live source for any claim.

Graph node count: 12. Core invariants: 6 + I6. Topology stable.
