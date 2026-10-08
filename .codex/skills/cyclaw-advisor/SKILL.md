---
name: cyclaw-advisor
description: >-
  Read-only CyClaw architecture and operations advisor for origin/main
  cb9a0128 (2026-10-08). High-signal since eb5a855 (2026-09-11, #1367):
  local-only githooks via ensure-githooks.sh (no global hooksPath),
  pre-push tag-chain secret scan and non-commit ref rewrite gate,
  agent_identity driver-prefix allowlist, PowerShell information-stream
  operator messages (#1582), script-lint CI (#1575). Graph still 12 nodes.
  Six invariants and I6 unchanged (INVARIANTS.md resynced 2026-10-03;
  no rule change since 2026-09-28). Inspect current code before describing
  routing, auth, retrieval, local models, or optional layers.
metadata:
  short-description: Current-main CyClaw architecture and operations advice
  recorded-head: cb9a0128fee1feb012d320932ef5e51bf4ce20f1
  recorded-date: "2026-10-08"
  prior-skill-refresh: eb5a855fba2ef072854d4f8b4c7117c91acf6776
---

# CyClaw Advisor

Use `$cyclaw-project-guidance` and the affected source files. Advice alone does
not authorize implementation or publication. If the user requests fixes, carry
out that authorized work using the relevant implementation workflow.

Record the inspected base/head SHA. Fetch current main for repository/PR advice;
for runtime troubleshooting distinguish the running checkout and operator config
from upstream defaults. List open PRs before recommending overlapping work.
This file records origin/main `cb9a0128fee1feb012d320932ef5e51bf4ce20f1`
(2026-10-08). It is a routing aid, not an authority snapshot. Code and
`config.yaml` still win. Never weaken the 6 invariants, I6, or the
out-of-band subprocess-shim contract.

## Latest merges into origin/main

Most recent first. Only high-signal items since the 2026-09-11 skill rewrite
(`eb5a855`, #1367). Docs polish and dependabot noise omitted.

- `cb9a0128` (2026-10-08, follow-up to #1587): `scripts/ensure-githooks.sh` is the primary install line; `install-githooks.sh` is the manual alternative. I2 docstring lists all four routers (`score_router`, `guardrail_router`, `user_gate_router`, `pre_action_hook_router`). Docs/comments only.
- `ae498a24` (2026-10-08): Copilot setup no longer sets a global `core.hooksPath`. A relative global hooksPath applied to every repo on the runner. Local checkout path only. Session-start sync-check does set an unset `core.hooksPath` and removes the old identity pin.
- `203a6653` (2026-10-08): pre-push secret gate peels tag chains one level at a time and scans each tag object; a ref force-moved onto a blob or tree is a rewrite and must hit the non-fast-forward check. Byte-identical with the CG-agent-harness copy.
- `230f255c` (#1583): security gate strips the TAB git appends to spaced `---/+++` paths so binary globs and bidi findings match.
- `4ed98358` (#1582): PowerShell operator messages go through `Write-Host` information stream so `*>`, `6>&1`, and `Start-Transcript` capture them. Six identical copies.
- #1573: agent-neutral secrets/privacy gate in pre-commit and pre-push (`.githooks/_security.sh`). Credential-shaped strings, blocked filenames, protected-path ack, fail-closed regex. Later commits closed textconv/merge/tag bypasses.
- #1575: fail-closed `script-lint.yml` (ShellCheck v0.11.0, PSScriptAnalyzer 1.23.0). No rule exclusions. macOS dotenv helpers must still receive `$1`.
- #1470: Claude Code commits as the session runtime identity, not a pinned CyClaw Agent author.
- Branch prefixes remain hook-enforced via `utils/agent_identity.py`: `claude/`, `codex/`, `grok/`, `kimi/`, `CyClaw/` or `cyclaw/`, else `agent/`. Do not default to `agent/` when the driver is known. Also allowed: `main`, `dependabot/*`, `renovate/*`, `release/*`, `hotfix/*`.

## Recent activity summary

Since #1367 removed the in-repo Python coding-harness console, origin/main has not changed graph topology or the six invariants. The load-bearing deltas are hook and harness-path contracts: hooks stay local to the checkout, the pre-push gate scans tag chains and treats a non-commit ref move as a rewrite, agent branches must match the driver allowlist, and Windows installer messages must stay on the information stream. INVARIANTS.md was resynced 2026-10-03 with no rule change since 2026-09-28. Verification policy (#1580) says agents run the changed code, then lint, then let GitHub Actions run the suites; CI still owns the full suite and the 80% coverage gate.

## Request path

`gate.py` validates the request and constructs clients; `graph.py` retrieves,
routes, generates, and converges on audit. The current graph has 12 nodes,
including the two provider pre-action hooks. Validate the node/edge sets with
`.claude/skills/invariant-guard/check_invariants.py`; a copied count is not a
substitute for reviewing routing. Count live `add_node` calls if main changes.
Current nodes: `retrieve`, `route_by_score`, `guardrail_input`, `guardrail_output`,
`local_llm`, `user_gate`, `pre_action_hook_grok`, `pre_action_hook_claude`,
`grok_fallback`, `claude_fallback`, `offline_best_effort`, `audit_logger`.
Guardrail input covers local and declined paths when enabled. Output rail applies
to local answers; generated answers still pass `guardrail_output` before audit.
External providers remain gated by hybrid+enabled client construction and
confirmation+selection+availability in the graph. `user_gate_router` does not
recheck mode/enabled. Pre-action hooks ship `enabled: false`; a deny routes to
audit with `answer_model: hook-denied`.

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

The ToolBroker in `utils/tool_broker.py` gates tool names; empty allowlists
deny, and broker approval does not replace reason/confirm. Agentic execution
travels through `ops_runner`, not direct core imports. I6 still forbids the six
core modules from importing `agentic`, `sync`, `guardrails`, `telegram`, or
`opentweet`. The graph reaches guardrails only through `utils/guardrail_bridge.py`.

Real-repo approval uses acceptance manifests bound to run/base/path hashes and
a disposable-copy verification before finalize. Read `agentic/executor/` and
its tests before claiming a platform sandbox guarantee. Job Objects control
process trees; they are not a network namespace. See
[environment notes](CyClaw-environment.md) for the platform source map.

Agent-opened branches must match the driver prefix allowlist in
`utils/agent_identity.py` and the githooks. A wrong prefix is a hook failure,
not a style nit.

## Advice and verification

Cite symbols and exact inspected paths. Separate implemented behavior, shipped
config, operator opt-ins, tests, and unverified live services. For PR advice,
include validity of findings, base/head state, overlap, CI, and any required
merge dependency. Do not treat bot task summaries or old merge lists as proof
that a fix reached the remote head.

## Core invariants (do not weaken)

Authority: running code, then `config.yaml`, then docs. `INVARIANTS.md` at this
HEAD still states the contract. Do not describe a comment as enforcement.

1. `retrieve` is the only entry. No pre-retrieval answer path.
2. External Grok/Claude calls need hybrid mode, literal `enabled: true`, and confirmation, plus an available client. Mode and enabled live in `gate.py` construction, not in `user_gate_router`.
3. Every path converges at `audit_logger` before END. The four answer nodes go through `guardrail_output`.
4. Soul HTTP mutation requires a non-empty reason and the injection scan before write.
5. Soul injection scan is write-path only. Reload and drift adopt `soul.md` unscanned.
6. API-key routes fail closed. The optional bypass needs the flag, loopback peer, no forwarding headers, and same-origin. Scanner path resolution is repo-root anchored.

I6: core six never import the five out-of-band packages; `/ops` uses the `ops_runner` subprocess shim. Rules 7-9 (query hash default, MCP has no LLM path, same isolation) still hold. Pre-action hooks and `require_user_confirm` are not substitutes for these gates.
