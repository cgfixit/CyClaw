---
name: cyclaw-advisor
description: Read-only CyClaw architecture and operations advisor for origin/main cb9a0128 (2026-10-08). High-signal since eb5a855 (2026-09-11) — local-only githooks via ensure-githooks.sh (#1577), pre-push tag-chain scan and non-commit rewrite gate, agent_identity vendor branch allowlist, PowerShell information-stream operator logs (#1582), Linux API key in libsecret or 0600 (#1561), credential/request limits (#1547), script-lint CI (#1575), Numbat Track A acceptance (#1539). Graph still 12 nodes. Six invariants and I6 unchanged (INVARIANTS.md resynced 2026-10-03; no rule change since 2026-09-28).
metadata:
  short-description: Current CyClaw architecture and operations advice
  recorded-head: cb9a0128fee1feb012d320932ef5e51bf4ce20f1
  recorded-date: "2026-10-08"
---

# CyClaw Advisor

Use `$cyclaw-project-guidance` and the affected source files. Advice alone does
not authorize implementation or publication. If the user requests fixes, carry
out that authorized work using the relevant implementation workflow.

Record the inspected base/head SHA. Fetch current main for repository/PR advice;
for runtime troubleshooting distinguish the running checkout and operator config
from upstream defaults. List open PRs before recommending overlapping work.

This file was refreshed against `origin/main` `cb9a0128` on 2026-10-08. It is a
routing aid, not an authority snapshot. Code and `config.yaml` still win.

## Request path

`gate.py` validates the request and constructs clients; `graph.py` retrieves,
routes, generates, and converges on audit. The current graph has 12 nodes,
including the two provider pre-action hooks. Validate the node/edge sets with
`.claude/skills/invariant-guard/check_invariants.py`; a copied count is not a
substitute for reviewing routing. Guardrail input covers local and declined
paths when enabled. External providers remain gated by hybrid+enabled client
construction and confirmation+selection+availability in the graph.

Live `add_node` set at `cb9a0128`: `retrieve`, `route_by_score`,
`guardrail_input`, `guardrail_output`, `local_llm`, `user_gate`,
`pre_action_hook_grok`, `pre_action_hook_claude`, `grok_fallback`,
`claude_fallback`, `offline_best_effort`, `audit_logger`. Entry is `retrieve`.
Routers named by the I2 check are `score_router`, `guardrail_router`,
`user_gate_router`, and `pre_action_hook_router`. Do not add a pre-retrieval
node or an edge out of `audit_logger`.

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
producer deduplication before changing observation behavior. Numbat Track A
operational acceptance (#1539) does not make Numbat the system of record.

## Out-of-band execution

The ToolBroker in `utils/tool_broker.py` gates tool names; empty allowlists
deny, and broker approval does not replace reason/confirm. Agentic execution
travels through `ops_runner`, not direct core imports. I6 still forbids the core
six (`gate.py`, `gate_ops.py`, `gate_auth.py`, `gate_memory.py`, `graph.py`,
`mcp_hybrid_server.py`) from importing `agentic`, `sync`, `guardrails`,
`telegram`, or `opentweet`. Do not weaken that subprocess-shim contract.

`utils/agent_identity.py` is the branch-namespace allowlist:
`claude/`, `codex/`, `grok/`, `kimi/`, `CyClaw/`, `cyclaw/`, `agent/`.
`CYCLAW_AGENT_BRANCH_PREFIX` adds a preferred prefix; it does not revoke the
allowlist. Committer default is `CyClaw Agent` / `cyclaw-agent@users.noreply.github.com`.

Real-repo approval uses acceptance manifests bound to run/base/path hashes and
a disposable-copy verification before finalize. Read `agentic/executor/` and
its tests before claiming a platform sandbox guarantee. Job Objects control
process trees; they are not a network namespace. An agentic atomic write that
fails must remove its temp file (#1543). See
[environment notes](CyClaw-environment.md) for the platform source map.

## Latest merges into origin/main

High-signal only, since the skill content commit `eb5a855` (2026-09-11, #1367).
Most recent first. Docs polish and dependabot bumps omitted.

- `cb9a0128` (2026-10-08): `scripts/ensure-githooks.sh` is the primary install;
  `install-githooks.sh` is manual. I2 docstring lists all four routers. Docs only.
- `ae498a24` (2026-10-08): Copilot setup must not set a global `core.hooksPath`.
  Relative global hooksPath runs the wrong repo's hooks. Local checkout only.
- `203a6653` (2026-10-08): pre-push peels a tag chain and scans each tag object;
  a ref force-moved onto a blob or tree is a rewrite and must hit
  `ALLOW_FORCE_WITH_LEASE`. Byte-identical with CG-agent-harness #380.
- #1583: strip the TAB git appends to a spaced `---/+++` path so
  `SEC_BINARY_GLOBS` match and bidi findings are not false positives.
- #1582: PowerShell operator messages go through the information stream so
  `6>&1` and `Start-Transcript` capture them.
- #1575: fail-closed `script-lint.yml` (ShellCheck 0.11.0, PSScriptAnalyzer
  1.23.0). macOS secret-scan helpers must keep the dotenv path argument.
- #1570 / #1548: remaining constraints-only and platform runtime pip installs
  require hashes.
- #1561: Linux `CYCLAW_API_KEY` is generated into libsecret or a mode-0600 file;
  pairing URL prints only on a TTY.
- #1547: core credential input and request limits hardened.
- #1546: agentic CI patch publication isolated (untrusted-checkout residual
  recorded for the candidate checkout).
- #1543: failed agentic atomic write deletes its temp file.
- #1539: Numbat Track A operational acceptance. Audit JSONL stays authoritative.
- #1554: prove bwrap on Ubuntu 24.04 with a bwrap-scoped AppArmor profile, not
  a global sysctl.
- #1537: Docker bind directories must be prepared before use.

## Recent activity summary

From 2026-09-11 to 2026-10-08 the graph stayed at 12 nodes and
`INVARIANTS.md` (resynced 2026-10-03) records no rule change since 2026-09-28.
The load-bearing movement is out-of-band and install-path: githooks are local
and scan tag chains, agent branch prefixes are an allowlist not a single vendor,
Windows and macOS install scripts gained stream/lint contracts, and Linux key
material moved to libsecret or a 0600 file. None of that authorizes weakening
RAG-first entry, audit convergence, the triple external-call gate, write-path
soul scan, or the I6 subprocess shim.

## Advice and verification

Cite symbols and exact inspected paths. Separate implemented behavior, shipped
config, operator opt-ins, tests, and unverified live services. For PR advice,
include validity of findings, base/head state, overlap, CI, and any required
merge dependency. Do not treat bot task summaries or old merge lists as proof
that a fix reached the remote head. Owner verification policy (#1580) is to run
the changed code, then lint/static checks, then let GitHub Actions run the
suites; CI still enforces the full suites and the coverage gate. That policy
does not relax invariant checks on core paths.
