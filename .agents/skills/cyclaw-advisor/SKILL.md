---
name: cyclaw-advisor
description: "Give read-only CyClaw architecture, operations or design advice from the inspected checkout and current configuration (origin/main HEAD a27cff0b 2026-10-31: fsync durability for soul/spend ledger, pillow/fastembed security pins, native installer dep consistency verification, service port exact-match fail-closed). Use for routing, retrieval, auth, model or platform questions; fixes require an implementation request."
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

- a27cff0b / 703dee21 / d30ee753 / 92b16514 (2026-10-31): dependabot/CI action and Falco bumps + cooldown/contract test; low-signal for advisor except CI surface hygiene.
- 5487be9d (#1789, 2026-10-30): shellcheck every tracked shell script; fixes warnings. Script hygiene, not core contract.
- a5b5212b (#1788, 2026-10-30): 120s budget for node-spawning workflow contract tests after Windows runner stall.
- 5b65bf2b (#1787, 2026-10-30): verify native installer dependency consistency before success. Fail-closed on mismatch.
- 26443ba2 (#1785, 2026-10-30): fsync before atomic renames, clean failed temps, harden spend ledger file mode. Durability for ledger.
- c005d796 (#1784, 2026-10-29): bump pillow to 13.0.0 and fastembed to 0.9.1; drop pillow pip-audit ignores; classify in telemetry inventory.
- dcfd3b99 (#1773, 2026-10-29): both service generators read api.port exactly as gate.py binds it; non-int/absent/YAMLError exit 3. Fail-closed port contract.
- be9b7acc (#1772, 2026-10-29): share one DB opener between auth and personality stores (open_db in personality_db).
- 368d5e5f (#1774, 2026-10-29): fsync soul temp file before atomic rename; Windows CRLF size assertion fix. Soul durability.

## Recent activity summary

No changes to graph topology (still ~12 nodes: retrieve entry, route_by_score, guardrail_input/output, local_llm, user_gate + provider hooks/fallbacks, offline_best_effort, audit_logger), I1–I6, or out-of-band isolation. Harness/executor remains removed (2026-10-18). High-signal is durability (fsync soul.md and spend ledger before rename), security dependency pins (pillow 13.0.0 / fastembed 0.9.1), native installer consistency checks, and exact service port matching that fails closed. Agent identity enforcement remains via githooks; no new multi-vendor prefix changes. Advisor posture unchanged: never weaken the 6 invariants / I6 / subprocess-shim contract; revalidate against live source.
