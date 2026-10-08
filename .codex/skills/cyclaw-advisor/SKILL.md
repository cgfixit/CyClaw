---
name: cyclaw-advisor
description: Read-only CyClaw architecture and operations advisor for origin/main c7cb5e47 (2026-10-08). High-signal since d9b0f8cd — Windows Job Object backend removed (#1593; production_sandbox refuses win32), #1597 executor result convergence + cooperative copy-budget, consolidation stub removed (#1595, behavior unchanged), githook gate gaps closed (#1589). Graph still 12 nodes. Give source-backed advice; inspect current code before describing routing, auth, retrieval, local models, or optional layers.
metadata:
  short-description: Current-main CyClaw architecture and operations advisor
  recorded-head: c7cb5e47e32b71ea25f96ea8c8924ffb1d49c198
  recorded-date: "2026-10-08"
---

# CyClaw Advisor

Advisory and study-oriented. Do not change code, configuration, soul content, branches, or pull requests unless the user explicitly changes the request to an implementation task. Re-verify mutable claims against `origin/main` and live code; this file is a routing aid, not an authority snapshot.

Recorded HEAD for this refresh — `c7cb5e47e32b71ea25f96ea8c8924ffb1d49c198` (2026-10-08). If live `origin/main` moves and no high-signal merge landed, say the skill is already current.

Use `$cyclaw-project-guidance` and the affected source files. Advice alone does
not authorize implementation or publication. If the user requests fixes, carry
out that authorized work using the relevant implementation workflow.

Record the inspected base/head SHA. Fetch current main for repository/PR advice;
for runtime troubleshooting distinguish the running checkout and operator config
from upstream defaults. List open PRs before recommending overlapping work.

Hardware / install / harness-path facts that affect environment references live in the sibling `CyClaw-environment.md`. Code and `config.yaml` still win.

## Activation

1. Fetch and state the current `origin/main` SHA.
2. Read `AGENTS.md`, `CLAUDE.md`, `INVARIANTS.md`, `config.yaml`, and affected code before answering.
3. Re-list open PRs before advising a change or merge order.
4. Use `README.md`, `docs/THREAT_MODEL.md`, and subsystem docs only for context; code and configuration win when they disagree.

## Request path

`gate.py` validates the request and constructs clients; `graph.py` retrieves,
routes, generates, and converges on audit. The current graph has 12 nodes,
including the two provider pre-action hooks. Validate the node/edge sets with
`.claude/skills/invariant-guard/check_invariants.py`; a copied count is not a
substitute for reviewing routing. Current nodes to re-count on this HEAD — `retrieve`, `route_by_score`, `guardrail_input`, `guardrail_output`, `local_llm`, `user_gate`, `pre_action_hook_grok`, `pre_action_hook_claude`, `grok_fallback`, `claude_fallback`, `offline_best_effort`, `audit_logger`. Policy routers and conditional edges must remain in the graph, and all paths must converge on `audit_logger`. A 13th node is forbidden.

The six invariants are the decision frame — RAG-first, topology-as-policy, triple-gated external fallback, audit convergence, soul governance, and module isolation. Never weaken those or the I6 / out-of-band contract. The optional `agentic`, `sync`, `guardrails`, `harness`, and `telegram` layers remain out of the core request path (`gate.py` / `graph.py` / `mcp_hybrid_server.py` must not import them).

Guardrail input covers local and declined
paths when enabled. External providers remain gated by hybrid+enabled client
construction and confirmation+selection+availability in the graph.

Both local answer nodes call `assert_local_destination` before generation.
Loopback is accepted; exact `models.local_llm.trusted_hosts` entries support
operator-owned container/LAN model servers. Default is `[]`. Invalid URL syntax
becomes `ENDPOINT_TRUST`. Grok/Claude use `assert_online_destination`; the local
allowlist never grants provider consent. See `docs/DOCKER.md` for the host-model
opt-in and its local-context/soul exposure. That is a destination allowlist, not a new graph node.

`generate_guard` can wrap synchronous generation through the maintained
`utils/guardrail_bridge.py`. Keep optional guardrails out of direct core imports.
MCP stays retrieval-only, sanitized, and without a generation/sampling path.
Do not wire `generate_async` onto `/query`.

## Auth, state, and observation

Stage 3 attaches session/device-token authentication to `/query` when
`auth.enabled` is true. Same-origin checking is unconditional. Do not describe
Stage 3 as merely planned or claim all query requests require a credential.
The separate API-key surface fails closed unless the configured optional-key
bypass passes all peer, forwarding-header, and origin checks. RBAC is separate.
An enabled admin login is the documented exception to fail-closed-on-unset-key for key-based credentials.

Read master switches before describing memory, auth, agentic, or guardrails as
active. The writer code flag, mode, and writes flag are armed, but the agentic
master switch defaults off. Keep the full reason/confirm/write chain intact.
`agentic/writer.py` still ships `EXECUTION_ENABLED = True` (armed 2026-08-07). `CYCLAW_AGENTIC_WRITE_DISABLE=1` is disable-only (AND-ed, never OR-ed). Do not describe the write path as live just because the code flag is armed.
Audit JSONL is authoritative; Numbat is a derived, fail-soft stream, enabled by
default. Read `utils/logger.py` and `utils/numbat_emitter.py` for redaction and
producer deduplication before changing observation behavior.

Episode-to-fact consolidation was never implemented. #1595 removed the `memory/consolidation.py` stub that always returned "disabled", the `memory.consolidation.enabled` flag, and the status echo. Behavior is unchanged. Do not describe a consolidation path as present.

## Out-of-band execution

The ToolBroker in `utils/tool_broker.py` gates tool names; empty allowlists
deny, and broker approval does not replace reason/confirm. Agentic execution
travels through `ops_runner`, not direct core imports. Canonical name-gate lives in utils so harness can call it without importing `guardrails` (I6). Audit stores tool name + argv digest only — never raw argv, URLs, instruction, or reason.

Real-repo approval uses acceptance manifests bound to run/base/path hashes and
a disposable-copy verification before finalize. Read `agentic/executor/` and
its tests before claiming a platform sandbox guarantee. Windows has no
backend: `production_sandbox()` refuses it, because Job Objects control
process trees but confine neither filesystem nor network. `WindowsJobObjectSandbox` was removed in #1593 (no production callers). Darwin Seatbelt and Linux bubblewrap (`--unshare-all`, PID namespace) are the production backends. Missing binary or failed capability probe raises `HardSandboxUnavailable` — fail closed, no software fallback to `ArgvListSandbox` (tests only). See
[environment notes](CyClaw-environment.md) for the platform source map.

#1597 (issue 1557 follow-up) does not change graph, gateway, routing, provider, soul, or import boundaries. Mirror-copy `OSError` and `TimeoutError` now converge once on `agentic_executor_check_result` plus one Numbat command projection, retaining mirror detail. Copy evidence is metadata-only (file/symlink count, regular-file bytes, sorted relative-path SHA-256, skipped special paths). Copy deadlines are cooperative: a stalled individual copy/metadata operation cannot be interrupted and there is no byte quota. Linux timeout/setsid-descendant acceptance must use real bubblewrap, not `ArgvListSandbox`.

## Latest merges into origin/main (high-signal only)

Most recent first. Ignore docs polish, screenshot uploads, dependabot noise, and dead-code housekeeping unless they touch the list in the update procedure. Prior list stopped at recorded HEAD `d9b0f8cd` (2026-08-27).

- #1597 — execution-boundary follow-ups for issue 1557. Mirror-copy failures emit one canonical result + Numbat projection; cooperative copy-budget stated in threat model; Codex Skills bubblewrap pin `0.9.0-1ubuntu0.3` on Ubuntu 24.04; real Linux timeout/setsid probe. I1–I6 unchanged.
- #1595 — remove the memory consolidation stub and `memory.consolidation.enabled`. Episode-to-fact consolidation was never implemented; behavior unchanged.
- #1593 — remove dead `WindowsJobObjectSandbox` (and other unused symbols). Production Windows verification refuses; do not cite a Job Object backend.
- #1589 — close githook gate gaps shared with CG-agent-harness: `.gitignore` rename detection (`--no-renames`), bidi findings kept when iconv is absent, blocked-name filters ACMRT (symlink swap), oversized files size-checked first, tag rewrites require acknowledgement, gitleaks on tag messages/trees.
- #1587 — root-doc resync. Tracked `.githooks` + `scripts/ensure-githooks.sh`; commit subjects are `[prefix] - subject`; agent identity stays with CLAUDE.md section 10 (do not tell Claude Code sessions to commit as CyClaw Agent); 1 MiB request-body cap; I6 names the core six and five out-of-band packages. No invariant rule change.
- #1367 (2026-09-11) — Python coding-harness console removed; CG-agent-harness owns that role. Do not describe a loopback harness console inside this repo.

## Recent activity summary

8 Oct 2026 on `c7cb5e47` is an out-of-band executor and docs/hooks day, not a core-topology rewrite. The 12-node graph and I1–I6 edges are intact. Advisor-relevant deltas since `d9b0f8cd`: Windows hard-sandbox backend is gone and `production_sandbox()` fails closed on win32; local destination trust is `assert_local_destination` plus exact `trusted_hosts` (default empty), not a blanket loopback-only check; Stage 3 session/device-token auth attaches to `/query` only when `auth.enabled`; the consolidation stub is gone; githooks fail closed on the #1589 gaps; #1597 makes mirror-copy failures observable on the canonical result channel and states the cooperative copy-budget limit. Writer six-gate posture is unchanged (armed code flag, master switch off, env disable-only). Do not treat bot task summaries or this merge list as proof a fix reached a newer remote head.

## Advice and verification

Cite symbols and exact inspected paths. Separate implemented behavior, shipped
config, operator opt-ins, tests, and unverified live services. For PR advice,
include validity of findings, base/head state, overlap, CI, and any required
merge dependency. Do not treat bot task summaries or old merge lists as proof
that a fix reached the remote head.

Before citing values, inspect `config.yaml` and relevant code for the loopback host/port, retrieval RRF settings and threshold, model IDs, auth/memory/agentic/harness/Telegram/sync switches, telemetry-kill ordering, and API-key enforcement. Do not infer cosine similarity from an RRF threshold, claim `/query` is always authenticated when auth is disabled, or claim memory is on when its master switch is false. Do not treat `EXECUTION_ENABLED = True` as "writes are on" while `agentic.enabled` is false. Do not treat ToolBroker allow as permission to skip confirm/reason. Do not claim Windows verification is sandboxed, and do not claim Darwin/Linux verification can run unconstrained if `sandbox-exec` / `bwrap` is missing — that path is `HARD_SANDBOX_UNAVAILABLE`.

Give the direct answer first, then cite paths and symbols, identify the relevant invariant or risk, distinguish confirmed facts from inference, and state what was not verified. Never expose private corpus contents, raw audit records, secrets, or credentials.
