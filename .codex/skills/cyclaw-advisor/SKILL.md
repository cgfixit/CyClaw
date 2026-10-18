---
name: cyclaw-advisor
description: Read-only CyClaw architecture and operations advisor for origin/main e73c434f (2026-10-18). High-signal since prior simplified form — ops_runner _write_body unlinks temp file on flush failure (disk-full orphan fix, #1686), Grok /health probe rstrip('/') (#1686), CYCLAW_PYTHON fail-closed exit 3 if not runnable file/command (#1687). Graph still 12 nodes. Six invariants and I6 unchanged (ops_runner subprocess-shim contract intact; unreachable real-repo-run dispatch removed earlier #1678).
metadata:
  short-description: Current CyClaw architecture and operations advice
  recorded-head: e73c434f36c93c264a58dae5a685fb7bcbce92c9
  recorded-date: "2026-10-18"
---

# CyClaw Advisor

Use `$cyclaw-project-guidance` and the affected source files. Advice alone does
not authorize implementation or publication. If the user requests fixes, carry
out that authorized work using the relevant implementation workflow.

Record the inspected base/head SHA. Fetch current main for repository/PR advice;
for runtime troubleshooting distinguish the running checkout and operator config
from upstream defaults. List open PRs before recommending overlapping work.

This file was refreshed against `origin/main` `e73c434f` on 2026-10-18. It is a
routing aid, not an authority snapshot. Code and `config.yaml` still win.

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

## Latest merges into origin/main (high-signal only)

- **e73c434f / #1687** (2026-10-18): CYCLAW_PYTHON fail-closed — `utils/launchd_plist.py` now raises RuntimeError (exit 3) if explicit CYCLAW_PYTHON is not a runnable file or PATH command; absolute path recorded. No invariant impact.
- **f287f888 / #1686** (2026-10-18): ops_runner `_write_body` moves close() into try so disk-full flush failure unlinks temp file (no orphan of skill text); Grok `/health` probe rstrip('/') on base_url; dead branches dropped in memory/policy, store, opentweet. Touches subprocess-shim cleanup only. Invariants 46/0 unchanged.
- Earlier: #1678 removed unreachable real-repo-run dispatch from ops_runner (allowlist matches schema's five actions).

## Recent activity summary

Main tip is e73c434f (2026-10-18). High-signal activity is confined to out-of-band ops_runner cleanup (temp-file orphan on flush failure) and macOS launcher interpreter resolution (CYCLAW_PYTHON exit 3). Graph topology remains 12 nodes with audit convergence through guardrail_output; six invariants and I6 isolation unchanged. No new core contracts, NeMo changes, or EXECUTION_ENABLED posture shifts. Prefer live code and config.yaml over this routing aid.

## Advice and verification

Cite symbols and exact inspected paths. Separate implemented behavior, shipped
config, operator opt-ins, tests, and unverified live services. For PR advice,
include validity of findings, base/head state, overlap, CI, and any required
merge dependency. Do not treat bot task summaries or old merge lists as proof
that a fix reached the remote head.
