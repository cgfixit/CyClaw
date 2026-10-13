---
name: cyclaw-advisor
description: Read-only CyClaw architecture and operations advisor for origin/main 6902d39a (2026-10-13). High-signal since 3fe82170 (2026-10-12 / #1619) — #1637 completed the telemetry/egress inventory: fail-closed on missing kill block, full spawn-site table covering PowerShell/pip/brew/git-remote (cat-3), agent-tooling boundary for .claude/, OLLAMA_HOST pinning, secret-env wrappers. Docs resyncs (#1643/#1645) corrected I6/harness drifts and checker skill claims. Graph still 12 nodes.
metadata:
  short-description: Current-main CyClaw architecture and operations advisor
  recorded-head: 6902d39a0277c2f8a3d226b7034823103b57383c
  recorded-date: "2026-10-13"
---

# CyClaw Advisor

Use `$cyclaw-project-guidance` and the affected source files. Advice alone does
not authorize implementation or publication. If the user requests fixes, carry
out that authorized work using the relevant implementation workflow.

Record the inspected base/head SHA. Fetch current main for repository/PR advice;
for runtime troubleshooting distinguish the running checkout and operator config
from upstream defaults. List open PRs before recommending overlapping work.

This file was refreshed against `origin/main` `6902d39a` on 2026-10-13. It is a
routing aid, not an authority snapshot. Code and `config.yaml` still win.

## Latest merges into origin/main

- 6902d39a (2026-10-13, #1645): Docs resync of knowledge/session skills; privacy verify.sh now checks shipped config.yaml posture; CyClaw-Sandbox reconciled (5 ladders, I6 core six, etc.).
- 659d9109 (2026-10-13, #1643): Checker skills resync (invariant-guard 46 assertions, dep-guard, config-guard, etc.); install hints point at hashed locks / driver.sh.
- ee7b6a34 et al. (2026-10-13, #1637 series): Telemetry inventory completion — fail-closed kill block, full spawn-site table (PowerShell probes, pip/brew/git-remote as category-3, secret-env wrappers, agent-tooling boundary excluding most .claude/), OLLAMA_HOST pin on all client calls, evidence path bounds.
- 3fe82170 (2026-10-12, #1619): Removed dead tool_broker name-gate, Phase 3+ stubs, tool-call metrics, and test-only executor exports.

## Request path

`gate.py` validates the request and constructs clients; `graph.py` retrieves,
routes, generates, and converges on audit. The current graph has 12 nodes,
including the two provider pre-action hooks. Validate the node/edge sets with
`.claude/skills/invariant-guard/check_invariants.py`; a copied count is not a
substitute for reviewing routing. Guardrail input covers local and declined
paths when enabled. External providers remain gated by hybrid+enabled client
construction and confirmation+selection+availability in the graph.

Both local answer nodes call `assert_local_destination` before generation.
Loopback is accepted; exact `models.local_llm.trusted_hosts` entries support
operator-owned container/LAN model servers. Default is `[]`. Invalid URL syntax
becomes `ENDPOINT_TRUST`. Grok/Claude use `assert_online_destination`; the local
allowlist never grants provider consent. See `docs/DOCKER.md` for the host-model
opt-in and its local-context/soul exposure.

`generate_guard` can wrap synchronous generation through the maintained
`utils/guardrail_bridge.py`. Keep optional guardrails out of direct core imports.
MCP stays retrieval-only, sanitized, and without a generation/sampling path.

## Auth, state, and observation

Stage 3 attaches session/device-token authentication to `/query` when
`auth.enabled` is true. Same-origin checking is unconditional. Do not describe
Stage 3 as merely planned or claim all query requests require a credential.
The separate API-key surface fails closed unless the configured optional-key
bypass passes all peer, forwarding-header, and origin checks. RBAC is separate.

Read master switches before describing memory, auth, agentic, or guardrails as
active. The writer code flag, mode, and writes flag are armed, but the agentic
master switch defaults off. Keep the full reason/confirm/write chain intact.
Audit JSONL is authoritative; Numbat is a derived, fail-soft stream, enabled by
default. Read `utils/logger.py` and `utils/numbat_emitter.py` for redaction and
producer deduplication before changing observation behavior.

## Out-of-band execution

No tool name-gate ships today: `utils/tool_broker.py` was removed on
2026-10-10 after it lost its last caller (PR #1367). Agentic execution
travels through `ops_runner`, not direct core imports.

Real-repo approval uses acceptance manifests bound to run/base/path hashes and
a disposable-copy verification before finalize. Read `agentic/executor/` and
its tests before claiming a platform sandbox guarantee. Windows has no
backend: `production_sandbox()` refuses it, because Job Objects control
process trees but confine neither filesystem nor network. See
[environment notes](CyClaw-environment.md) for the platform source map.

## Advice and verification

Cite symbols and exact inspected paths. Separate implemented behavior, shipped
config, operator opt-ins, tests, and unverified live services. For PR advice,
include validity of findings, base/head state, overlap, CI, and any required
merge dependency. Do not treat bot task summaries or old merge lists as proof
that a fix reached the remote head.
