---
name: cyclaw-advisor
description: Read-only, source-backed CyClaw architecture and operations advisor for origin/main 6519135e (2026-10-13). High-signal since 3fe8217 (2026-10-12, #1619) — real-repo origin pinning + Git helper process reaping (#1630), lock contract validation and patch publication conditioning (#1631), scheduled rclone credentials retrieved at execution time (#1632), public cookie/path/TLS key boundaries (#1635), optional derived Ollama tag docs (#1625). Graph still 12 nodes. Six invariants and I6 unchanged.
metadata:
  short-description: Current CyClaw architecture and operations advice
  recorded-head: 6519135e8f94b7e4bb4932704efbb92003d7b6e0
  recorded-date: "2026-10-13"
---

# CyClaw Advisor

Use `$cyclaw-project-guidance` and the affected source files. Advice alone does
not authorize implementation or publication. If the user requests fixes, carry
out that authorized work using the relevant implementation workflow.

Record the inspected base/head SHA. Fetch current main for repository/PR advice;
for runtime troubleshooting distinguish the running checkout and operator config
from upstream defaults. List open PRs before recommending overlapping work.

This file was refreshed against `origin/main` `6519135e` on 2026-10-13. It is a
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

Recent real-repo hardening: origin is pinned and Git helper processes are reaped (#1630); scheduled rclone credentials are retrieved at execution time rather than earlier (#1632).

## Latest merges into origin/main (high-signal only, most recent first)

- 6519135e (2026-10-13, #1625): docs for optional derived Ollama tag (qwen3.8:27b-mlx-cg) and bake-off record; keep tags distinct, scope setup hints.
- b85100df (2026-10-13, #1631): validate lock contracts; condition patch publication; seed refreshes from tracked locks; hash only requires-python + dependency tables.
- 9c04fc25 (2026-10-13, #1635): complete public cookie, path and TLS key boundaries; normalize slash-rooted citations on Windows; strict path redaction; symlink alias labels; TLS backup permissions.
- 96ef12eb (2026-10-13, #1632): retrieve scheduled rclone credentials at execution time; preserve Windows path meaning; accept retained discovery paths; verify configured remote.
- 7e7c51e8 (2026-10-13, #1630): pin real-repo origin; reap Git helper processes; refuse .git file/commondir/legacy remotes; GIT_DIR/COMMON_DIR/WORK_TREE pinning; process-group kill only on timeout/failure.
- 3fe82170 (2026-10-12, #1619): remove uncalled tool name-gate (utils/tool_broker.py) and related dead code; update skill accordingly.

## Recent activity summary

Since the prior skill record (implicitly around #1619 / 3fe8217), high-signal merges have focused on security boundaries (public cookie/path/TLS, lock contracts, rclone credential timing), real-repo Git containment (origin pin + process reaping), and minor docs for optional local Ollama derived tags. No changes to graph topology (still 12 nodes), invariant count, or I6 out-of-band isolation. Agentic master switch remains default-off; six-gate real-repo posture unchanged.

## Advice and verification

Cite symbols and exact inspected paths. Separate implemented behavior, shipped
config, operator opt-ins, tests, and unverified live services. For PR advice,
include validity of findings, base/head state, overlap, CI, and any required
merge dependency. Do not treat bot task summaries or old merge lists as proof
that a fix reached the remote head.
