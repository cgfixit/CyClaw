---
name: CyClaw-Sandbox
description: >
  CyClaw Swarm Verification -- comprehensive test system for the CyClaw
  offline-first RAG project (github.com/CGFixIT/CyClaw). Verifies the
  12-node LangGraph pipeline (incl. pre-action hooks) across 5 queries and
  three local-LLM realism tiers, triple-gated online API fallback (Grok +
  Claude, connection-only, no API cost), the pre-action hook gate, API key
  redaction, all 14 due-diligence invariant classes, spend/Numbat/
  sequence-detection forensics, the memory/Telegram/OpenTweet/unslop
  subsystems, the auth subsystem (bootstrap/session+CSRF/RBAC/TLS), the MCP
  manifest drift pin, and OS scheduler glue. Covers the terminal console
  fully: its REST surface (/soul, /ops/sync, /ops/agentic, /ops/fsconnect,
  /ops/sqlconnect, /index/*, /memory/*, /auth/*) and all four of its slash
  commands. Not CyClaw's own session-memory docs (`docs/memories/`) — this
  tests the product's `/memory/*` REST API, a different thing entirely.
disable-model-invocation: true
---

# CyClaw Swarm Verification

**The contract, stated precisely.** A green run of this skill's full audit
means: the 12-node graph routes all 5 sample queries correctly at whichever
local-LLM realism tier was actually live; the Grok/Claude triple gate holds
end to end with zero real API spend; every terminal-console
REST endpoint and slash command this document lists is registered and
behaves per its documented contract; the 14 due-diligence invariant classes
and every row of the Guardrails table below hold; and the out-of-band
subsystems (spend ledger, Numbat, sequence detection, memory, Telegram,
OpenTweet, unslop, MCP manifest pin, OS scheduler glue) behave per their own
documented defaults. It does **not** mean live 27b-quality generation was
exercised, that a real Ollama daemon answered, that any browser JS ran, or
that a real GitHub-writing agentic run completed -- those are explicitly
out of scope everywhere they matter, called out inline.

Numbers below are marked one of two ways: a bare number next to a named
test or checker means that number is enforced somewhere and won't silently
drift (cite the enforcer, don't just trust this document); `(derive)` means
read it from the running code/tree at verification time, never copy it from
here. **Code, `config.yaml`, and the tests currently on disk always win over
this document.** Surface inventory below was last reconciled against main
@ `663a8bb` (2026-10-13) -- if it disagrees with what you see on
a fresh checkout, trust the checkout and treat the disagreement as this
document's own next drift-fix.

## Operator map -- which ladder proves what

Five ladders (B–F; there is no ladder A). They are complementary, not
substitutable -- a green run of one is **not** evidence the others would
also pass. Always invoke with `python3.12` (never bare `python3` -- see
Gotchas). Claude Code's own `/memory` and the repo's `docs/memories/` are not
this skill either -- this ladder tests CyClaw's `/memory/*` REST API.

| Ladder | Command | Proves | Does **not** prove |
|---|---|---|---|
| **B. In-process swarm** | `python3.12 .claude/skills/CyClaw-Sandbox/run_full_verification.py` | 9 phases through the real LangGraph runtime with deterministic Chroma/embedding doubles -- prints its own totals, never hand-count them | Live HTTP servers, browser JS, Windows installer, real Chroma persistence |
| **C. CI lifecycle** | `bash .claude/skills/CyClaw-Sandbox/verify.sh` | 3.12 venv, full pytest, RAG smoke, live `gate.py`, terminal emulation | Browser `/loop auto`, real 27b-class model, Auth beyond the shipped default, live NeMo rail |
| **D. Surface smoke** | `bash .claude/skills/CyClaw-Sandbox/smoke.sh` (a.k.a. `/run`, Quick Mode) | Sections A-G against a live server it starts itself -- prints its own PASS/FAIL totals to `.claude/sandbox-test.txt`, never a fixed count | Due-diligence classes, the full Ladder F sweep below |
| **E. Live API bomb** | `windows-smoke.ps1` / `macos-smoke.sh` | Matching live-HTTP checks against an already-running gate -- see the scripts' own numbered comments for the current count | Broader fsconnect/sqlconnect/guardrails/Postgres (that's ladder D); `/ops/sync`, `/ops/agentic`, `/ops/sqlconnect` (documented gap in both scripts' headers) |
| **F. Full sandbox clone audit** | Steps section below | Everything in B-D plus spend/Numbat/sequence-detection, the full auth lifecycle (bootstrap through RBAC and TLS), memory/Telegram/OpenTweet/unslop, MCP manifest pin, OS scheduler glue, and the groundedness evaluator -- the "verify everything" ladder | Nothing it doesn't say it skips (opt-in stages are marked SKIP, not silently passed) |

### `verify.sh` stage numbers (historical -- do not renumber)

Labels are **not** sequential in source order. CI logs and comments cite
them; do not "fix" the numbers.

| Label | Source order | What runs |
|---|---|---|
| Stage 1 | 1st | Python 3.12 venv + deps |
| Stage 2 | 2nd | `pytest tests/` |
| Stage 3 | 3rd | emulated RAG (`tests/ci_rag_smoke.py`) |
| Stage 5 | 4th | `gate_runtime_check.py` |
| Stage 4 | 5th | live `gate.py` API smoke |
| Stage 7 | 6th | `terminal_emulation.py` |
| Stage 6 | last | write `/tmp/cyclaw-verify-report.md` |

Stage 1's hard failure on a missing/wrong `python3.12` is deliberate, not a
gap against this repo's usual "skip cleanly without deps" skill convention
(CLAUDE.md §6): the Python-3.12 runtime gate is this script's own
advertised feature (CLAUDE.md §7 routes "suspected config drift" reports
here specifically because bare `python3`/`pytest` silently run the wrong
interpreter and fail the `test_agentic_*` files in a way that looks like a
red `main`, CLAUDE.md §4). Every other stage degrades gracefully; this one
is supposed to stop you.

## Where the surfaces live

One row per surface. "Pinned by" names a test or checker that would catch
regression on its own, independent of this skill.

| Surface | File(s) | What to verify | Pinned by |
|---|---|---|---|
| Gate core routes | `gate.py` | `/`, `/health`, `/query`, `/soul*`, `/audit/summary`, `/index/build`, `/index/status`, `GET`/`POST /console/session`, `POST /console/session/end`; `POST /query` rejects cross-site browser requests (403 `CROSS_SITE_BLOCKED`, from `Origin`/`Sec-Fetch-Site`) **regardless of `auth.enabled`** -- a request carrying neither header is allowed; `GET /index/status` is unauthenticated and **not** rate-limited (the console polls it every 1.5s, same posture as `/health`) | `gate_runtime_check.py` (a route *subset*: it does not pin `/audit/summary`, `/soul/restore` or the console-session routes; `tests/test_gate.py` does) |
| Ops routes | `gate_ops.py` | `POST /ops/{sync,agentic,fsconnect,sqlconnect}`; every `action` field is a closed `Literal` (`schemas/api.py`) -- an unrecognized value is a **422**, not a handler-level 400 | `test_terminal_consoles.py` |
| Auth routes | `gate_auth.py` | 13 paths (`/auth/setup-status`, `/bootstrap-password`, `/login`, `/logout`, `/whoami`, `/users` GET+POST, `/password`, `/users/{u}/password`, `/users/{u}/role`, `/users/{u}/disable`, `/users/{u}/enable`, `/users/{u}` DELETE, `/audit/summary`); every route exists and answers **503** (not 404) when `auth.enabled` is false (the shipped default); identity attaches to `POST /query` only when an `AuthManager` exists; `audit` role is forbidden from `/query`; account lockout answers **423**; a raced duplicate username or device-token label is a typed conflict (`AuthUserExists`/`AuthTokenLabelExists` -> **409**) | `test_auth_admin_contract.py`, `tests/test_due_diligence_invariants.py` |
| Memory routes | `gate_memory.py` | `/memory/status` is always 200 (probeable when the subsystem is off); `/memory/{facts,episodes,proposals,propose,apply,reject}` and `/query/export/html` are **404** when their toggle is off (all ship false); flag resolution goes through `memory/flags.py` -- the fact-retrieval switch is `memory.facts.retrieval_enabled` (legacy `memory.facts.enabled` honored with a one-time warning), the status payload reports `facts_retrieval_enabled`, and every flag echo is a strict boolean (`is True` -- a YAML `"false"` string reports off) | `test_memory_isolation.py`-style isolation + live probe |
| Terminal console | `static/terminal.html` + `static/terminal.js` + `static/auth_admin.js` (CSP forces `script-src 'self'`, so the console's JS logic lives in the sibling files -- read all three together) | 7 toolbar panels (Soul/Sync/Agentic/FS/SQL, plus Users and Audit, which stay hidden until `auth.enabled`); the confirm dialog's generic `handleConfirm(confirmed, entryId, onlineProvider)`; the four slash commands `/users /admin /audit /help` (everything else is a toolbar button or a RAG query, not a command) | `tests/test_terminal_contract.py` (reads the HTML and JS combined; its `_POST_PATHS` pins every POST-only path -- derive the count from the file, it grows) |
| MCP | `mcp_hybrid_server.py` | Single tool `hybrid_search`; `sampling: None`; `check_input` runs before retrieval; `mcp_manifest.json` SHA-256 drift pin | `tests/test_mcp_server.py`, `tests/test_mcp_manifest.py` |
| Graph | `graph.py` | 12 nodes (`retrieve`, `route_by_score`, `guardrail_input`, `guardrail_output`, `local_llm`, `user_gate`, `pre_action_hook_grok`, `pre_action_hook_claude`, `grok_fallback`, `claude_fallback`, `offline_best_effort`, `audit_logger`); 4 routers (`score_router`, `guardrail_router`, `pre_action_hook_router`, `user_gate_router`) | `tests/test_operator_docs_node_count.py` (`>=12`), `tests/test_graph.py` |
| CLIs | `sync/cli.py`, `agentic/cli.py`, `agentic/fsconnect/cli.py`, `agentic/sqlconnect/cli.py`, `agentic/netconnect/cli.py`, `telegram/cli.py`, `opentweet/cli.py`, `guardrails/cli.py`, `utils/authn_cli.py`, `utils/gen_cert.py`, `retrieval/indexer.py`, `retrieval/clear_cache.py`, `metrics.py`, `utils/telemetry_kill.py --export` | Name + exit-code contract only (`--help` for the current subcommand set -- never hardcode a subcommand count in this document, it drifts every time a CLI grows one) | `tests/test_*_cli.py` per connector |
| Telemetry contract | `utils/telemetry_kill.py`, `utils/onnx_telemetry.py` | Owned by the `otel-hardening` skill, not this one -- run `python3 .claude/skills/otel-hardening/check_otel.py --strict --as-of $(date +%F)` for the full contract. This skill only spot-checks that the canonical maps (`TELEMETRY_KILL`/`UPDATE_CHECK_OPT_OUT`/`SCRUBBED_ENV_KEYS`) are wired at import time | `otel-hardening/check_otel.py` |
| Invocable checker skills | `.claude/skills/{invariant-guard,config-guard,dep-guard,verify-deps,otel-hardening,doc-sync,index-doctor,injection-redteam}/` | Each has its own `check_*.py`/`verify.sh` -- run the ones relevant to what changed, not all of them on every pass | see each skill's own `SKILL.md` |

## Steps -- the full audit (Ladder F)

The single procedure absorbing the in-process swarm's 9 phases and every
live/out-of-band surface into one ordered run. Record PASS / FAIL / SKIP
per numbered item; an opt-in item you didn't exercise is SKIP, never a
silent pass.

### 1. Clone & inspect

```bash
git clone https://github.com/CGFixIT/CyClaw.git
cd CyClaw && git checkout main && git pull
git log -1 --format='%H %cs'          # record sha/date for the sign-off
python3.12 --version                  # must be 3.12.x
grep '^version' pyproject.toml        # (derive) record it
```

Read `config.yaml` and confirm the shipped contract (all `(derive)` --
compare against the file, don't trust a number written here): `app.mode`,
`api.host`/`api.port`, `models.grok.enabled`/`models.claude.enabled`,
`retrieval.min_score`, `policy.prompt_filter.banned_patterns` length
(floor, not exact -- injection-redteam legitimately grows this list),
`fsconnect`/`sqlconnect`/`sync`/`agentic`/`auth`/`numbat`/`unslop`/
`netconnect`/`telegram`/`opentweet`/`guardrails` blocks present with their
shipped `enabled` values, `policy.fallback.require_user_confirm` present
but unwired (hardcoded in `user_gate_router`), `policy.fallback.
{grok,claude}_max_prompt_chars`, `policy.privacy.redact_secrets_like`
includes an `sk-ant-*` pattern, `policy.fallback.pre_action_hook.enabled`
(shipped false), `security.api_key_optional` (shipped false).

Verify module isolation (I6): `agentic/` (including `agentic/netconnect/`),
`sync/`, `guardrails/`, `telegram/`, and `opentweet/` are never imported by
the core six (`gate.py`, `gate_ops.py`, `gate_auth.py`, `gate_memory.py`,
`graph.py`, `mcp_hybrid_server.py`), and vice versa; the `agentic.*.cli`
modules run only via subprocess from `utils/ops_runner.py`.

Verify code structure: `graph.py` has `_external_fallback_node(state,
client, cfg, *, provider, label)`; `grok_fallback_node`/`claude_fallback_node`
are thin wrappers over it (shared prompt assembly, cost-guard truncation,
audit-log truncation events, and -- since the `served_model` audit field
landed -- the vendor-echoed model id forwarded onto the audit record).

### 2. Environment

Requirements: Python 3.12 exactly, `rank-bm25`, PyYAML, numpy, httpx, and
(full mode) chromadb/sentence-transformers/langgraph/fastapi/uvicorn.

Install per CLAUDE.md §8 (the hashed `locks/`, torch lock first). **In a
Claude Code cloud sandbox** bare `python3`/`pytest` are never 3.12 and carry
none of CyClaw's deps (CLAUDE.md §4), so build the venv with
`bash .claude/skills/cyclaw-gotchas/driver.sh venv` -- it is the documented
§8 install plus the plain-torch fallback for a proxy that denies the PyTorch
CPU index, and the cloud SessionStart hook already starts it in the
background. The venv does not survive session end; always invoke
`/root/.venv-cyclaw-312/bin/python`, never bare `python3`. Note the sandbox
proxy also denies `huggingface.co`, so the real index (ladders C–F) cannot
be built there; ladder B's deterministic doubles still run.

`GROK_API_KEY=dummy` (any non-empty value) is sufficient for these tests.
Startup does not require `GROK_API_KEY`; Grok reports unavailable without it.

**Editable install with extras** (when network allows and you need the
console scripts): `pip install -e ".[test,full]" -c constraints.txt`.

**In-process swarm dependencies**: `run_full_verification.py` uses the real
installed LangGraph runtime and deterministic in-memory doubles for ChromaDB
and the embedding model. Run it from the CyClaw venv; `verify.sh` owns clean
dependency installation and the full lifecycle lane.

Generate a session key rather than a hand-picked one for any live-gate
work in this Steps section: `python3 -c 'import secrets;
print(secrets.token_urlsafe(32))'`. Never log the full value -- truncate to
the first 6 characters in notes.

### 3. Static gates (no server)

Ladder F is the owner's full audit, so the whole suite runs here on purpose;
outside this ladder CLAUDE.md §5 leaves that run to GitHub Actions.

```bash
GROK_API_KEY=dummy python3.12 -m pytest tests/ -o addopts="" -q --tb=short   # (derive) record N passed / N total
python3 .claude/skills/invariant-guard/check_invariants.py     # (derive) record N/N
GROK_API_KEY=dummy python3.12 -m pytest tests/test_due_diligence_invariants.py -q  # 14 classes
python3 .claude/skills/doc-sync/doc_sync.py
python3 .claude/skills/config-guard/check_config.py
```

### 4. In-process swarm

```bash
GROK_API_KEY=dummy python3.12 .claude/skills/CyClaw-Sandbox/run_full_verification.py
```
Expect `total_passed == total_checks` in `verification_report.json`;
pointing `CYCLAW_REPO` at a working tree (rather than a scratch clone)
makes this write mock corpus/index/report files into it -- the script
warns loudly when you do this on purpose.

### 5. Live gate (:8787)

```bash
CYCLAW_API_KEY=$CYCLAW_API_KEY GROK_API_KEY=dummy nohup python3.12 -m uvicorn gate:app --host 127.0.0.1 --port 8787 --no-proxy-headers \
  >/tmp/gate.log 2>&1 &
for i in $(seq 1 40); do curl -sf 127.0.0.1:8787/health >/dev/null && break; sleep 0.5; done
python3.12 .claude/skills/CyClaw-Sandbox/gate_runtime_check.py
python3.12 .claude/skills/CyClaw-Sandbox/terminal_emulation.py http://127.0.0.1:8787
CYCLAW_API_KEY=$CYCLAW_API_KEY python3.12 .claude/skills/CyClaw-Sandbox/test_terminal_consoles.py
```
Verify: `/health` 200 unauthenticated; `/` serves `terminal.html`; auto-docs
off (`/docs`/`/openapi.json` 404); every `/soul/*` and `/ops/*` route 401s
without the key, 429 under rate-limit exhaustion, and carries the security
headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
`Permissions-Policy`, `Content-Security-Policy`); `/auth/*` returns 503 (not
404) while `auth.enabled` is false; all four terminal slash commands
respond; `POST /query` rejects cross-site requests (403 `CROSS_SITE_BLOCKED`)
even with auth off; `/index/build` is loopback+same-origin gated and, once
`CYCLAW_API_KEY` is set (as it is in this step), also key-gated -- it is
deliberately NOT key-gated while the key is unset so a first-run build cannot
be bricked; `/index/status` is open and un-rate-limited (poll target). Enabling auth in a scratch config additionally exercises: bootstrap
from loopback only, session cookie + CSRF on `/query`, RBAC (`audit` role
403s on `/query`), and TLS via `cyclaw-gen-cert` (session cookie gains
`secure` once `api.tls.enabled: true`).

### 6. Out-of-band subsystems

- **Spend** (`utils/spend.py`, `logs/spend.jsonl`): append-only; each real
  external generate appends one record, including the vendor-served model
  string (which also reaches the audit record); `cyclaw-metrics` splits
  spend by source (`query` vs `agentic`) and prints a vendor-cost
  comparison; a price staleness warning surfaces (non-fatal) on the
  recording path once the pricing table's own `PRICED_AS_OF` date is old
  enough -- read the actual threshold from `utils/spend.py`, don't hardcode
  it here.
- **Numbat** (`utils/numbat_emitter.py`, ships `enabled: true`): activity
  appends NDJSON lines to `logs/numbat-events.ndjsonl`; fail-soft (make the
  emitter raise -- e.g. read-only logs dir in a scratch copy -- and confirm
  the request still succeeds); the documented skip-set event types never
  double-emit through the mainline projection; the stream rolls over at
  `numbat.max_bytes` (50 MiB shipped -- read the value from `config.yaml`)
  while `logs/audit.jsonl` stays authoritative and unrotated.
- **Sequence detection** (`utils/sequence_detect.py`, forensic-only): CLI
  or `cyclaw-metrics`-joined surface lists its rule set; craft synthetic
  audit+spend fixtures and confirm a suspicious pattern is flagged and a
  clean log is not; `grep -rn sequence_detect gate*.py graph.py mcp*.py`
  returns nothing (I6-style isolation, even though it isn't in the formal
  out-of-band package set).
- **Memory** (`gate_memory.py` + package `memory/`, ships every switch
  false): `/memory/status` 200 with flags off; `/memory/{facts,episodes,
  proposals}` and `/memory/{propose,apply,reject}` 404 while their toggles
  are off; enabling in a scratch config exercises propose -> apply ->
  queryable facts, and an injection payload in a proposal triggers the
  documented block event. Use the current flag spelling
  (`memory.facts.retrieval_enabled`, resolved via `memory/flags.py`) in
  scratch configs; echoes are strict booleans, so a quoted `"true"` stays
  off.
- **Telegram** (`telegram/`, ships `enabled: false`): CLI disabled-state
  report; a mocked-Bot-API integration (stub `getMe`/`sendMessage`/
  `getUpdates`) drives `poll_once`/`send_notify`; the `/online on <grok|
  claude>` hybrid-confirm command works only in an allowlisted private
  chat with the exact syntax.
- **OpenTweet** (`opentweet/`, ships `enabled: false`): CLI disabled-state
  exit; enabled in a scratch config, the runner's generation call is
  loopback `/query` with `user_confirmed_online: false` and a draft is the
  default outcome -- it never escalates online or posts by itself.
- **Unslop** (`agentic/unslop_bridge.py`, ships `enabled: false`): zero
  effect when off; enabled, forcing the vendored bridge to raise must not
  block the agentic run it's attached to (log-only, non-blocking).
- **netconnect** (`agentic/netconnect/`, ships `enabled: false`): passive
  LAN inventory only -- no ping/probe/sweep; every returned address must
  fall inside an explicitly configured RFC1918/loopback CIDR; an empty or
  overly broad scope fails closed rather than defaulting open.

### 7. MCP + OS glue

- `mcp_manifest.json`'s SHA-256 drift pin: flip a byte in a scratch copy
  and confirm drift is reported and fails closed. `hybrid_search` works
  with no LLM booted; `check_input` runs before retrieval.
- Platform generators refuse cross-platform on the wrong host (a Darwin
  generator run on Linux, or vice versa, errors before its own governance
  gate even evaluates `--confirm`/`--reason`); secrets never appear in
  argv for either platform's credential wrapper.
- `sync/scheduler.py::get_scheduler`: the configured backend selects the
  matching implementation; an unsupported backend/platform pairing (e.g.
  `launchd` requested on non-Darwin) is a clean `SchedulerError`, never a
  silent fallback to a different backend; cron-line ownership stays scoped
  to CyClaw-managed lines only.

### 8. Groundedness evaluator (opt-in)

`CYCLAW_EVAL_LIVE=1 ANTHROPIC_API_KEY=... python3.12 tests/judge_eval.py`
against a loopback LLM: exit 0 pass / 1 fail / 2 infra. Without live keys,
verify the gate refuses cleanly (exit 2) rather than silently skipping.

### 9. Report

End with a sign-off naming: the repo sha/date and Python/pyproject
versions actually used; which local-LLM realism tier was live (0 = no responding
HTTP backend, 1 = `mock_ollama.py`, 2 = real Ollama daemon --
`run_full_verification.py` auto-detects and reports this; `verify.sh` does
not probe for a daemon, so state the tier for its stages yourself);
per-item PASS/FAIL/SKIP for every numbered item above; the due-diligence
and Guardrails pass counts (report the actual `N/14` and `N/<rows>` from the
run, never copy last time's numbers); and any Known Residual (below) that
changed since it was last confirmed.

## Quick Mode (`/run`)

`bash .claude/skills/CyClaw-Sandbox/smoke.sh` -- a fast, live-server pass
covering sections A-G (core API, fsconnect, sqlconnect, NeMo soft-import,
Postgres-backend skip-cleanly, the full pytest suite as section F, and the
summary report as G). It builds its own index if one is missing, starts and stops its
own `gate.py`, and writes `.claude/sandbox-test.txt`. It does **not** build
the mock RAG corpus or walk the due-diligence invariant classes -- a green Quick Mode
is not evidence the full Ladder F audit would also pass, and the reverse
holds too.

## Bundled resources

All scripts below live flat in this skill directory
(`.claude/skills/CyClaw-Sandbox/`), not under a `scripts/`/`references/`
subdirectory -- invoke them by that path.

- **`run_full_verification.py`** -- the in-process swarm (Ladder B, 9
  phases). Env: `CYCLAW_REPO=/path` to use an existing checkout instead of
  cloning fresh (warns before writing mock corpus/index/report files into
  it). Unset `CYCLAW_REPO` clones into a unique temp directory, copies
  `verification_report.json` and `query_results.json` to the invoking cwd,
  then deletes that temp directory. This script auto-detects the live
  Ollama realism tier; `verify.sh` does not.
- **`gate_runtime_check.py`** -- independent, import-time-only checks: app
  builds and is a FastAPI instance, telemetry-kill maps are active, the
  expected route subset registers, `main` is callable.
- **`terminal_emulation.py`** -- exercises the exact HTTP fetch lifecycle
  the console's own JS performs, against an already-running server. Wired
  into `verify.sh` (stage 7); also runnable standalone.
- **`test_terminal_consoles.py`** -- stdlib-`urllib` integration test
  against a running `gate.py` with `CYCLAW_API_KEY` set. Asserts the auth
  gate on `/soul`, `/soul/propose` and the four `/ops/*` routes (the
  remaining `/soul/*` routes are covered by `tests/test_gate.py`), an
  unknown `action` 422s at the schema boundary (closed `Literal` fields, not
  a handler-level 400), and the security-header/DROP-rejection contracts.
- **`mock_ollama.py`** -- stdlib-only mock Ollama/OpenAI-compatible server
  (`/api/tags`, `/api/chat`, `/api/generate`, `/v1/models`,
  `/v1/chat/completions`) for deterministic offline chat testing. This is
  realism **Tier 1** of three: Tier 0 is no responding HTTP backend at all
  (the pytest suite's in-process `MockLocalLLM` stub never touches HTTP),
  Tier 2 is a real Ollama daemon.
- **`verify.sh`** -- the CI-wired, full Linux lifecycle: Python 3.12
  provisioning, the pytest suite, an emulated RAG query, the runtime check,
  then the terminal console launched live and emulated end to end.
  Non-sequential stage labels, see the table above -- never renumber.
- **`smoke.sh`** -- Quick Mode, see above.
- **`windows-smoke.ps1`** / **`macos-smoke.sh`** -- the platform live-API
  bombs against already-running servers (they start nothing themselves).
  `windows-latest` CI runs the PowerShell script; `macos-latest` CI runs
  the bash one. Neither is discovered by the `verify-skills` matrix (that
  job only globs `verify.sh`/`smoke.sh`); both run as dedicated, blocking
  CI steps instead. `macos-smoke.sh` is Darwin-first (bash 3.2, no jq) and
  also the POSIX twin a Linux operator can run by hand.
- **`test-specifications.md`** -- detailed test-case inventory (query
  prompts, per-provider triple-gate cases, redaction cases, the
  due-diligence classes, console endpoint tests, macOS realism coverage
  table). Read when implementing new tests or debugging a failure.

## Known residuals

Track as KNOWN -- confirm they still exist at each full audit; never
report one of these as a new finding.

1. `check_jailbreak` is listed in the guardrails config but has no rail of
   its own: the offline floor implements only `check_injection` and
   `check_soul_mutation` on input, the NeMo flow `check cyclaw jailbreak`
   runs the same injection markers, and no LLM-backed rail is active, so a
   persona prompt worded off those markers passes. `topical_rails` is
   display-only. `guardrail_output` runs `check_soul_leak` and
   `check_grounding`, but on the `local_llm` answer only. The generation
   broker also checks soul-leak markers on all four answer routes through
   NeMo `check()` or deterministic fallback when a live check is unavailable.
   Grounding remains scoped to retrieved local answers.
2. Telegram's T4 media handling is partial and POSIX-only.
3. Episode-to-fact consolidation is not implemented (the former
   `memory/consolidation.py` stub was removed).
4. `terminal.html` has no memory console (REST-only). The auth UI
   (`static/auth_admin.js`: Users and Audit panels -- list/create users,
   change roles, reset passwords, delete; `.toolbar-auth` is the setup/login
   box) lacks only disable/enable and self-service password change.
5. `embeddings_local`'s health-check entry is static by design (it does
   not depend on whether the model has actually loaded) -- not a finding.
6. Hand-run `uvicorn gate:app` (bypassing the shipped launcher or Docker
   CMD) still gets the canonical telemetry/update-check env only at module
   import, not before the interpreter starts -- documented in
   `docs/THREAT_MODEL.md`, accepted.

## Guardrails

Restates the security invariants this skill verifies (see `CLAUDE.md` §3
for the six canonical ones plus supporting guards this table extends). Row
numbers are historical labels (18–21 were retired); count the rows you
report, never assume.

| # | Invariant | Check |
|---|---|---|
| 1 | RAG-First | `retrieve` is always the unconditional graph entry point |
| 2 | Topology = Policy | Routing via the named routers, never a prompt or ad-hoc branch |
| 3 | Triple-Gated External | `app.mode=="hybrid"` AND `<provider>.enabled` AND per-request `user_confirmed_online`, all three, for whichever provider is selected |
| 4 | Audit Convergence | Every path -- including `hook-denied`, `external-unavailable`, `guardrail-blocked` -- reaches `audit_logger` exactly once before END |
| 5 | Soul Governance | Evolution requires a non-empty human `reason` string; write is atomic |
| 6 | Telemetry Contract | Owned by `otel-hardening`, not this skill: canonical maps in `utils/telemetry_kill.py` applied at import (G1 anchor); `python3 .claude/skills/otel-hardening/check_otel.py --strict` is the authority, not a count copied into this document |
| 7 | Loopback Only | `api.host == "127.0.0.1"` |
| 8 | FsConnect Read-Only Default | `fsconnect.writes_enabled=false`, `follow_symlinks=false` |
| 9 | FsConnect Pathsafe | All paths resolve through `ScopedRoots` with `O_NOFOLLOW` |
| 10 | FsConnect Op Whitelist | Capability list is closed (derive the current set from `config.yaml`'s `fsconnect.allowed_fs_ops` -- it grows over time, e.g. `fs_largest`) |
| 11 | SQL Read-Only Default | `sqlconnect.read_only=true`, `allow_write=false` |
| 12 | SQL Query Guard | Only SELECT/WITH; comments and `;` rejected |
| 13 | Module Isolation (I6) | `agentic` (including `agentic/netconnect`), `sync`, `guardrails`, `telegram`, and `opentweet` never imported by the core six (`gate*.py`, `graph.py`, `mcp_hybrid_server.py`), and vice versa |
| 14 | Soul Privacy | Soul preamble never forwarded to Grok/Claude (off-box) |
| 15 | API Key Gate | Every `/soul/*`, `/ops/*`, `/memory/*`, `/audit/summary` and `/query/export/html` route requires `CYCLAW_API_KEY` (or the console/admin cookie) and fails closed on an unset key; `/index/build` joins once the key is set; `/query` and `/auth/*` use session/same-origin gates instead (CLAUDE.md §2 route table) |
| 16 | Rate Limit | Every route shares the per-IP `RateLimiter` except `GET /health` and `GET /index/status`, which are deliberately open poll targets |
| 17 | Key Redaction Parity | `redact_sensitive` (`utils/logger.py`) redacts every `os.environ` value, so `ANTHROPIC_API_KEY` and `GROK_API_KEY` are treated alike; the `sk-ant-*` shape is in both `_MINIMUM_SECRET_PATTERNS` and `config.yaml` `policy.privacy.redact_secrets_like` |
| 22 | Auth Disabled By Default | `auth.enabled=false` ships default, matching every other opt-in subsystem |
| 23 | Auth Route Presence Doesn't Disclose State | Every `/auth/*` route always returns 503, never 404, while `auth.enabled` is false |
| 24 | Auth Stage 3 Enforced | The identity dependency (`require_session_or_token`) attaches to `POST /query` whenever an `AuthManager` exists; the `audit` role is forbidden from `/query`; the 503-when-disabled contract is unchanged when auth stays off |
| 25 | Pre-Action Hook Fail-Closed | A non-zero/non-2 exit or a timeout on `policy.fallback.pre_action_hook`'s command denies (`answer_model="hook-denied"`); the hook's stdin payload carries no query text or soul content |
| 26 | API-Key Bypass Hygiene | `security.api_key_optional`'s bypass (when turned on) requires a loopback socket peer AND zero reverse-proxy forwarding headers; the bind guard separately refuses a non-loopback `api.host` while that flag is set |

## Gotchas

- **`python3` may not be 3.12.** See Step 2 above -- point explicitly at
  `python3.12` (or the session venv's `bin/python`) rather than trusting
  the default.
- **Quick Mode and the full audit test different things.** See the
  Operator map's Ladder D row -- treat them as complementary, never
  substitutable in either direction.
- **Three local-LLM realism tiers, not one.** In the in-process swarm, Tier 0
  means no responding HTTP backend; Tier 1 = `mock_ollama.py`; Tier 2 = a real daemon.
  `run_full_verification.py` auto-detects which one is live and reports it;
  `verify.sh` does not -- state the tier honestly in your own sign-off
  rather than assuming Tier 2 realism from a Tier 0/1 run.
- **`run_full_verification.py` writes into whatever `CYCLAW_REPO` points
  at** from Phase 3 onward (mock corpus, BM25 index, two JSON report
  files). Point it at a scratch clone, not a working tree, unless those
  writes are what you want -- the script warns loudly either way. A default
  run (no `CYCLAW_REPO`) owns its temp clone and removes it at process end;
  look for the reports in the directory you launched from, not under `/tmp`.
- **`pkill -f` can match your own invoking command line.** Use a distinct
  marker or kill by PID rather than a broad process-name pattern,
  especially when a prior command in the same session already started a
  server under a similar name.

## Mock embedding and Chroma doubles

Ladder B's deterministic doubles live in `run_full_verification.py`:
`MockSentenceTransformer` (sparse SHA-256 keyword hashing into 384 dims,
L2-normalized) and `MockChromaClient`/`MockCollection` (cosine search over a
singleton collection registry carrying the fingerprint metadata contract).
Read the script for the current shapes; they track `retrieval/` and drift
if copied here.
