---
name: CyClaw-Sandbox
description: >
  CyClaw local verification -- the operator's audit of a checkout on their own
  machine (or a cloud sandbox). One command (`local_audit.py`, Ladder L) runs
  the stdlib checkers, ruff, the changed code itself (every CLI, every
  subsystem's own selftest, gate import), the in-process LangGraph swarm, and a live gate.py
  probed against the CLAUDE.md route contract, all in scratch copies that never
  touch your working tree. Opt-in manual steps cover what no script can
  (auth-enabled config, a real Ollama, MCP stdio, the out-of-band
  subsystems). The pytest suites, the coverage gate and the
  macOS/Windows smoke steps belong to GitHub Actions; this skill only
  reproduces them when a CI job is red. Not CyClaw's session-memory docs
  (`docs/memories/`) -- it tests the product's `/memory/*` REST API.
disable-model-invocation: true
---

# CyClaw Local Verification

**The contract, stated precisely.** A green Ladder L run means, for the
checkout you ran it on: every stdlib checker and the ruff gate pass; every
CLI starts, every shipped-off subsystem reports itself off, and every
subsystem passes its own offline pre-flight (`<pkg>.cli test`); the 12-node graph routes the five
swarm queries and holds the Grok/Claude triple gate with zero API spend; and a
live `gate.py`, booted from the real `config.yaml`, answers every route in
CLAUDE.md §2 with the status that table promises (401/403/404/413/422/429/503
included). It does **not** mean the pytest suites or the 80% coverage gate
pass (Actions runs those on the PR), that a 27B-class model answered well,
that browser JS ran, or that the auth-enabled, memory-enabled or fsconnect
write paths work: those are the opt-in steps below, SKIP until you do them.

**Verification order** is CLAUDE.md §5's, applied to a whole checkout: run the
code, then lint and the checkers, then let GitHub Actions run the suites. Run
one targeted test file only when the first three cannot reach a path. Never
run `pytest tests/` or a `--cov` run as a routine local step.

Numbers marked `(derive)` come from the running code or tree at verification
time; never copy them from here. **Code, `config.yaml` and the tests on disk
always win over this document.** Surfaces below were reconciled against main
@ `29f639a` (2026-10-13) by running every command in this file; a
disagreement on a fresh checkout is this document's next drift-fix.

## Operator map -- which ladder proves what

Ladder letters B–F are historical (dated audits in `docs/audits/` cite them);
L is the local default. Always use the CyClaw **3.12** venv's interpreter
(written `<venv>/bin/python` below), never bare `python3` (Gotchas).

| Ladder | Command | Where it belongs | Proves | Does **not** prove |
|---|---|---|---|---|
| **L. Local audit** (default) | `<venv>/bin/python .claude/skills/CyClaw-Sandbox/local_audit.py` | **Local** | Stages 0–4 below in about a minute (measured, cloud sandbox, warm venv): checkers + ruff, run-the-code, swarm, live route contract, rate limit | pytest, coverage, browser JS, opt-in subsystems |
| **B. In-process swarm** | `run_full_verification.py` | Local (Ladder L stage 3 runs it) | 9 phases through the real LangGraph runtime with deterministic Chroma/embedding doubles; prints its own totals | Live HTTP, real Chroma persistence |
| **D. Quick Mode** (`/run`) | `SMOKE_SKIP_PYTEST=1 PYTHON=<venv>/bin/python bash .claude/skills/CyClaw-Sandbox/smoke.sh` | Local, in place | Sections A, B, D, E against a gate it starts on :8787 in **your** tree (soul.md backed up and restored); fsconnect/NeMo probes Ladder L lacks | The route-contract sweep, the swarm |
| **C. CI lifecycle** | `verify.sh` | **GitHub Actions** (`verify-skills`, conda lane) | Clean venv + full pytest + RAG smoke + live gate | Run locally only to reproduce a red job |
| **E. Live API bomb** | `macos-smoke.sh` / `windows-smoke.ps1` | **GitHub Actions** (macOS/Windows live-smoke steps) | Matching live-HTTP checks against an already-running gate | Run by hand only to reproduce; `macos-smoke.sh` is also a quick by-hand pass on a Mac |
| **F. Full local audit** | Steps section below | Local, owner-run | Ladder L plus every opt-in step you mark PASS | Anything marked SKIP |

### What GitHub Actions owns (don't reproduce it routinely)

The full `pytest tests/` suite on four OS legs, the `--cov` run and its 80%
`fail_under`, `ci_rag_smoke.py`, `verify.sh`, `smoke.sh` section F, the
macOS/Windows live smokes, lint.yml's ruff
gate, CodeQL/DevSkim, dep and lock contracts, and the PR-template check. Read
the PR's check results instead. Reproduce one only when it is red and the log
alone doesn't explain it, and then run that job's own command (verify.sh
stage labels are historical and non-sequential: 1, 2, 3, 5, 4, 7, 6; never
renumber them, CI logs cite them).

## Where the surfaces live

"Pinned by" names what catches a regression on its own, independent of this
skill (mostly in CI).

| Surface | File(s) | What Ladder L checks live | Pinned by |
|---|---|---|---|
| Gate core | `gate.py` | `/health` open; `/` serves the console; `/docs` `/redoc` `/openapi.json` 404; five security headers on every response; `/index/status` open and not rate-limited; `/soul*` and `/audit/summary` 401 without the key, 200 with it; body over `security.max_request_body_bytes` is 413; cross-site `POST /query` 403 `CROSS_SITE_BLOCKED` with auth off (no `Origin`/`Sec-Fetch-Site` at all is allowed); `POST /index/build` 401 without the key and 403 `INDEX_BUILD_LOOPBACK_ONLY` behind a forwarding header (both refusals precede any build) | `tests/test_gate*.py`, `gate_runtime_check.py` (route subset) |
| Ops | `gate_ops.py` | `POST /ops/{sync,fsconnect}` 401 without the key; an unknown `action` is 422 at the schema boundary (closed `Literal`, `schemas/api.py`), never a handler 400; `/ops/agentic` and `/ops/sqlconnect` (removed 2026-10-18) are 404 even with the key | `test_terminal_consoles.py`, `tests/test_gate_ops*.py` |
| Auth | `gate_auth.py` | `/auth/setup-status`, `/auth/whoami`, `/auth/users`, `POST /auth/login` all **503** (never 404) while `auth.enabled` ships false. A malformed login body is 422 first: validation runs before the 503 | `tests/test_auth_admin_contract.py`, `tests/test_due_diligence_invariants.py` |
| Memory | `gate_memory.py`, `memory/` | `/memory/status` 401 without the key, 200 with it, every `*enabled` flag a strict bool; `/memory/{facts,episodes,proposals}` and `/query/export/html` 404 while their toggles ship off. `python -m memory.selftest` drives the store, policy, fusion and export offline | `tests/test_memory_*.py` |
| Query path | `gate.py` → `graph.py` | Only with a built `index/`: vault hit (`needs_confirm` false, hits > 0), injection 400, declined-online stays `offline-best-effort` or `local`. Without an index every `/query` is 503 `INDEX_NOT_FOUND` **before** the injection filter, so those three are SKIP, not FAIL | `tests/test_graph.py`, `tests/ci_rag_smoke.py` (CI) |
| Rate limit | `utils/ratelimit.py` | 60/min per IP (derive from `api.rate_limit`): the 61st `GET /soul` is 429, and `/health` + `/index/status` still answer 200 | `tests/test_ratelimit*.py` |
| Console | `static/terminal.html` + `terminal.js` + `auth_admin.js` (CSP forces `script-src 'self'`; read all three) | `test_terminal_consoles.py` (3 panels, 26 checks at last run, derive) and, with an index, `terminal_emulation.py` (the console's own fetch lifecycle, with its graph-timeout-derived read deadline) | `tests/test_terminal_contract.py` (its `_POST_PATHS` pins every POST route; derive the count) |
| Graph | `graph.py` | Via the swarm: 12 nodes, 4 routers (`score_router`, `guardrail_router`, `pre_action_hook_router`, `user_gate_router`), all paths through `audit_logger` | `invariant-guard`, `tests/test_graph.py` |
| CLIs | `sync/cli.py`, `agentic/{fsconnect,netconnect}/cli.py`, `telegram/cli.py`, `opentweet/cli.py`, `guardrails/cli.py`, `utils/authn_cli.py`, `utils/gen_cert.py`, `retrieval/indexer.py`, `retrieval/clear_cache.py`, `metrics.py`, `utils/telemetry_kill.py` | `--help` exits 0 for all; `status` for telegram/opentweet/netconnect/fsconnect reports shipped-off with exit 0; `clear_cache` with no `--apply` deletes nothing; `telemetry_kill --export shell` prints. Exit codes are an API (CLAUDE.md §4); never hardcode a subcommand count here | `tests/test_*_cli.py` |
| Telemetry | `utils/telemetry_kill.py`, `utils/onnx_telemetry.py` | Owned by `otel-hardening`; Ladder L runs `check_otel.py --strict --as-of <today>` and `gate_runtime_check.py` confirms the kill env is live at import | `otel-hardening/check_otel.py`, `tests/test_telemetry_kill.py` |
| MCP | `mcp_hybrid_server.py`, `mcp_manifest.json` | Not live in Ladder L (stdio, no HTTP); see step 7 | `tests/test_mcp_server.py`, `tests/test_mcp_manifest.py` |

## Steps -- the full local audit (Ladder F)

Record PASS / FAIL / SKIP per numbered item. An opt-in item you didn't
exercise is SKIP, never a silent pass.

### 1. Sync and inspect

```bash
git fetch origin main && git status -sb      # ahead/behind origin/main
git log -1 --format='%h %cs %s'              # record sha/date for the sign-off
bash .claude/skills/cyclaw-gotchas/driver.sh inventory   # interpreters, venv, ruff, index, proxy
```

Read the `config.yaml` blocks your change touches and confirm their shipped
values against CLAUDE.md §2's load-bearing table (all derive). `config-guard`
(stage 1) already asserts the relational contract; read by hand only what it
can't judge, e.g. a new key's default.

### 2. Environment

- **Your machine:** install per CLAUDE.md §8 (hashed `locks/`, torch first;
  macOS uses plain `torch==2.14.1` and the macOS locks). For the `cyclaw-*`
  shims, use `pip install -e . -c constraints.txt` on Linux/Windows or
  `pip install -e . --no-deps` on macOS after the locked install.
- **Claude Code cloud sandbox:** bare `python3`/`pytest` are not 3.12 and
  carry no deps. `bash .claude/skills/cyclaw-gotchas/driver.sh venv` builds
  `/root/.venv-cyclaw-312` (the SessionStart hook starts it in the
  background; a second call waits for that build). Export
  `HF_HUB_DISABLE_XET=1` before anything that downloads a model (Gotchas).
- `GROK_API_KEY=dummy` is enough everywhere; Ladder L sets it for its children.
- Build the real index once if you want the query-path probes:
  `<venv>/bin/python -m retrieval.indexer` (264 chunks at last run, derive;
  `index/` is gitignored). Ladder L copies it into its scratch gate.

### 3. Ladder L -- the one command

```bash
<venv>/bin/python .claude/skills/CyClaw-Sandbox/local_audit.py              # all stages
<venv>/bin/python .claude/skills/CyClaw-Sandbox/local_audit.py --mock-ollama # Tier 1 local LLM
<venv>/bin/python .claude/skills/CyClaw-Sandbox/local_audit.py --skip-swarm --skip-live  # ~25 s static + run-code
```

| Stage | What runs |
|---|---|
| 0 preflight | 3.12 interpreter, checkout sha/branch, ahead/behind `origin/main`, uncommitted edits noted (they are audited too) |
| 1 static | `invariant-guard`, `dotenv-guard`, `doc-sync`, `config-guard`, `dep-guard`, `verify-deps/check_env_drift.py --strict`, `otel-hardening --strict`; `ruff check --select F,B,S .` (lint.yml's blocking gate) and the advisory `E,F,I,B,C4,UP,S --ignore E501` pass. Ruff missing is SKIP |
| 2 run the code | `gate_runtime_check.py`; each subsystem's operator pre-flight (`python -m {sync,agentic.fsconnect,agentic.netconnect,guardrails,telegram,opentweet}.cli test` and `python -m memory.selftest`), no network and no mocks; every CLI's `--help`; the shipped-off `status` reports; `clear_cache` dry-run; `telemetry_kill --export shell`. A selftest whose only failure is a missing external binary (rclone) is SKIP |
| 3 swarm | `run_full_verification.py` in a scratch copy (127/127 checks at last run, 2026-10-18, derive); reports the Ollama realism tier |
| 4 live gate | `uvicorn gate:app` from a scratch copy on :8791 (next free port if busy) with a random `CYCLAW_API_KEY`: the route-contract probes in the table above, `test_terminal_consoles.py`, and `terminal_emulation.py` when an index exists. That launch raises only the scratch copy's rate limit so the probes don't trip it; a second launch on the **shipped** limit then proves the 429 |

Output: per-check lines, then `report.md` plus every log in
`$TMPDIR/cyclaw-local-audit-<stamp>/` (`--out DIR` to choose). Exit 0 = no
FAIL, 1 = a FAIL, 3 = wrong interpreter or not a checkout. `--keep` keeps the
scratch copies for inspection.

The scratch copies take your working tree as-is (uncommitted edits
included) minus `index/`, `logs/`, caches and venvs; the repo-local model
cache `.emb_cache/` comes along, so nothing re-downloads. Your `soul.md`,
`logs/audit.jsonl` and `index/` are never written.

### 4. Opt-in: real local LLM (Tier 2)

On a machine with Ollama and the configured model (`models.local_llm.model`,
derive) pulled: `python3 scripts/measure_local_llm_throughput.py` (exit 0
measured, 2 unreachable), then run Ladder L **without** `--mock-ollama`; the
swarm detects the daemon on :11434 and reports Tier 2. Ask a corpus question
in the browser console at `http://127.0.0.1:8787/` and confirm a grounded
answer. A Tier 0/1 run is never evidence of Tier 2 quality.

### 5. Opt-in: auth, memory and the pre-action hook (scratch config)

Copy the checkout (`--keep` leaves one at the printed path), edit its
`config.yaml`, and launch a gate from it:

```bash
cd <scratch-copy> && CYCLAW_API_KEY=<random> GROK_API_KEY=dummy <venv>/bin/python -m uvicorn gate:app --host 127.0.0.1 --port 8792 --no-proxy-headers
```

- **Auth** (`auth.enabled: true`): `POST /auth/bootstrap-password` works from
  loopback only and 409s once set; `/auth/login` returns the session cookie
  and CSRF token; `POST /query` now needs the session (or a device token) and
  the `audit` role is 403 `AUTH_ROLE_DENIED`; a wrong-password burst locks the
  account, which still answers the uniform 401 (even for the right password);
  a disabled admin can't pass `require_api_key`. `cyclaw-user`
  (`python -m utils.authn_cli`) manages users locally. TLS: `cyclaw-gen-cert`
  then `api.tls.enabled: true` marks the cookie `secure`.
- **Memory** (`memory.enabled`, `memory.facts.retrieval_enabled`,
  `memory.propose_apply.enabled`): propose → apply (non-empty `reason`) →
  the fact shows in `/memory/facts`; an injection payload in a proposal is
  refused on apply. Flags are strict booleans: a quoted `"true"` stays off.
- **Pre-action hook** (`policy.fallback.pre_action_hook`, ships off): with a
  `command` engine that exits non-zero, or times out, a confirmed hybrid
  query ends `answer_model="hook-denied"`, and the hook's stdin carries no
  query text or soul content.

### 6. Opt-in: out-of-band subsystems (run the code)

- **Spend / metrics:** `python -m metrics` summarises `logs/audit.jsonl` and
  `logs/spend.jsonl`; a stale pricing table prints a non-fatal warning (read
  `PRICED_AS_OF` and the threshold from `utils/spend.py`).
- **Numbat** (`numbat.enabled` ships true): a few `/query` calls append NDJSON
  to `logs/numbat-events.ndjsonl`; a read-only `logs/` in a scratch copy must
  not fail the request.
- **Sequence detection** (`utils/sequence_detect.py`, forensic-only):
  `metrics` joins it; `grep -rn sequence_detect gate*.py graph.py mcp*.py`
  returns nothing.
- **Telegram / OpenTweet / netconnect** ship off; Ladder L already
  checks the off-state reports. Turning one on needs its own credentials and a
  scratch config; follow its README (`docs/channels/`, `agentic/netconnect/`)
  (netconnect's scope rules are in `agentic/netconnect/scope.py`) and confirm the off-box behaviour it documents (OpenTweet always sends
  `user_confirmed_online: false` and drafts by default; netconnect never
  probes actively and fails closed on an empty or over-broad scope).
- **fsconnect:** Quick Mode section B probes path safety, emulated reads
  and the dry-run/live write split in your tree.

### 7. Opt-in: MCP, OS glue

- **MCP:** `<venv>/bin/python mcp_hybrid_server.py` speaks stdio; point an
  MCP client at it and confirm a single `hybrid_search` tool, `sampling: None`,
  and that an injection query is refused before retrieval. Manifest drift: in
  a scratch copy flip a byte of `mcp_manifest.json` and confirm startup audits
  `mcp_manifest_drift` and exits 1 before the index opens.
- **Scheduler:** `sync/scheduler.py::get_scheduler` picks the configured
  backend; an unsupported pairing (e.g. `launchd` off Darwin) is a clean
  `SchedulerError`, never a silent fallback.

### 8. Opt-in: groundedness evaluator

`CYCLAW_EVAL_LIVE=1 ANTHROPIC_API_KEY=... <venv>/bin/python tests/judge_eval.py`
against a loopback LLM: exit 0 pass, 1 fail, 2 infra. This spends real API
money; without the keys, confirm it refuses with exit 2.

### 9. Report

Ladder L writes `report.md`; add to it: the sha/date, the realism tier that
was live (0 none, 1 `mock_ollama.py`, 2 real daemon), PASS/FAIL/SKIP for each
opt-in step 4–8, the PR's CI result if one exists (link it, don't re-run it),
and any Known Residual below that changed. This skill opens no PR.

## Quick Mode (`/run`)

```bash
SMOKE_SKIP_PYTEST=1 PYTHON=<venv>/bin/python bash .claude/skills/CyClaw-Sandbox/smoke.sh
```

Runs **in place**: builds an index if `index/bm25.json` is missing, starts its
own gate on :8787 (it waits for the port to be free), backs up and restores
`soul.md`, and writes `.claude/sandbox-test.txt` (gitignored). Sections: A core
API, B fsconnect, D NeMo soft-import, E Postgres (SKIP without
`CYCLAW_DB_URL`), F full pytest (SKIP when `SMOKE_SKIP_PYTEST` is set; CI leaves
it unset), G report. C (sqlconnect) was retired on 2026-10-18; the other
letters stay put because this file, `/run` and dated audits cite them.
Measured: 10 passed, 4 skipped, 33 s. A green Quick Mode is not evidence
Ladder L would pass, nor the reverse.

## Bundled resources

All flat in `.claude/skills/CyClaw-Sandbox/`. CI-wired files are marked; change
them knowing a workflow and its pinning tests read them.

- **`local_audit.py`** -- Ladder L (stdlib only; run with the venv
  interpreter). Never runs pytest; never writes the checkout.
- **`run_full_verification.py`** -- the swarm (Ladder B, 9 phases).
  `CYCLAW_REPO=/path` uses that tree **as-is and writes into it** (mock corpus,
  BM25 index, two JSON reports); unset, it clones `origin/main` from GitHub
  into a temp dir, so it tests main, not your edits. Ladder L points it at a
  scratch copy instead.
- **`gate_runtime_check.py`** -- import-only: app builds, telemetry kill
  live, the expected route subset registers, `main` callable. Logs a
  CRITICAL "index not found" without an index; that is fail-soft, not a FAIL.
- **`test_terminal_consoles.py`** -- stdlib integration test against a
  running gate (`CYCLAW_URL`, `CYCLAW_API_KEY`); needs no index.
- **`terminal_emulation.py`** -- the console's fetch lifecycle; needs an
  index and `CYCLAW_API_KEY` in the environment, or its `/query` and authed
  `/soul` checks fail.
- **`mock_ollama.py`** -- realism Tier 1, stdlib Ollama/OpenAI-compatible
  mock on :11434. Writes `mock_ollama.log` into its cwd.
- **`smoke.sh`** -- Quick Mode. *CI-wired* (`verify-skills`).
- **`verify.sh`** -- Ladder C. *CI-wired* (`verify-skills`, the conda lane).
- **`macos-smoke.sh`** / **`windows-smoke.ps1`** -- Ladder E against an
  already-running gate. *CI-wired* (macOS/Windows live-smoke steps).
- **`test-specifications.md`** -- the swarm's case inventory (queries,
  triple-gate, redaction, due-diligence classes, console endpoints). Read it
  when a swarm phase fails.

The Codex port lives at `.agents/skills/cyclaw-sandbox/`; this copy is canonical.

## Known residuals

Confirm each still holds at a full audit; never report one as a new finding.

1. `check_jailbreak` has no rail of its own: input rails are `check_injection`
   and `check_soul_mutation` (NeMo reuses the same markers) and no LLM-backed
   rail is active, so a persona prompt worded off those markers passes
   (`guardrails/README.md`). Output rails: soul-leak on all four answer
   routes, grounding only on retrieved local answers.
2. Telegram's T4 media handling is partial and POSIX-only.
3. Episode-to-fact consolidation is not implemented.
4. `terminal.html` has no memory console (REST-only); the auth UI
   (`static/auth_admin.js`) lacks disable/enable and self-service password
   change.
5. `embeddings_local`'s health entry is static by design.
6. A hand-run `uvicorn gate:app` gets the telemetry/update-check env only at
   module import, not before the interpreter starts (`docs/THREAT_MODEL.md`,
   accepted).

## Guardrails

The invariants this skill verifies. Row numbers are historical labels
(11–12 and 18–21 retired); count the rows you report.

| # | Invariant | Check |
|---|---|---|
| 1–5 | Graph invariants I1–I5 (CLAUDE.md §3) | `invariant-guard` + the swarm's triple-gate and audit-convergence phases |
| 6 | Telemetry contract | `otel-hardening --strict`; kill env live at import |
| 7 | Loopback only | `api.host == "127.0.0.1"` (`config-guard`) |
| 8 | FsConnect read-only default | `fsconnect.writes_enabled=false`, `follow_symlinks=false` |
| 9 | FsConnect pathsafe | Paths resolve through `ScopedRoots` with `O_NOFOLLOW` (Quick Mode B) |
| 10 | FsConnect op whitelist | Closed list; derive from `fsconnect.allowed_fs_ops` |
| 13 | Module isolation (I6) | `invariant-guard` I6 + Quick Mode's fsconnect `sys.modules` probe |
| 14 | Soul privacy | Soul preamble never forwarded to Grok/Claude (swarm triple-gate phase) |
| 15 | API key gate | Every `/soul*`, `/ops/*`, `/memory/*`, `/audit/summary`, `/query/export/html` 401s without the key and fails closed while it is unset; `/index/build` joins once the key is set (Ladder L stage 4) |
| 16 | Rate limit | Shared per-IP limiter everywhere except `GET /health` and `GET /index/status` (stage 4, second launch) |
| 17 | Key redaction parity | `redact_sensitive` redacts every `os.environ` value; `sk-ant-*` in `_MINIMUM_SECRET_PATTERNS` and `policy.privacy.redact_secrets_like` (swarm) |
| 22 | Auth off by default | `auth.enabled=false` ships |
| 23 | Auth routes don't disclose state | Every `/auth/*` route 503s, never 404s, while off (stage 4) |
| 24 | Auth Stage 3 | With auth on, `require_session_or_token` guards `POST /query` and `audit` is forbidden (step 5) |
| 25 | Pre-action hook fail-closed | Non-zero exit or timeout denies (`hook-denied`); stdin has no query or soul (step 5) |
| 26 | API-key bypass hygiene | `security.api_key_optional` needs loopback peer + no forwarding header + not cross-site; the bind guard refuses a non-loopback `api.host` while it is set (`config-guard`, `tests/test_gate*.py`) |

## Gotchas

- **Use the 3.12 venv interpreter.** Bare `python3` is often 3.11/3.13 and,
  in the cloud sandbox, has no deps; `local_audit.py` exits 3 on the wrong
  interpreter instead of reporting a fake red.
- **Hugging Face Xet in the cloud sandbox.** The proxy allows
  `huggingface.co` but denies `cas-server.xethub.hf.co`, so the first model
  download (the indexer's embedder, or the gate's reranker on the first
  `/query`) **hangs** at `model.safetensors` instead of failing. Export
  `HF_HUB_DISABLE_XET=1` and it downloads over plain HTTPS (measured: the
  index then built in under a minute). Not a CyClaw setting; never add it to `TELEMETRY_KILL`.
- **The reranker downloads lazily.** `models.reranker` ships on, so the first
  vault-hit `/query` on a fresh cache fetches the cross-encoder (~91 MB). A
  slow first query is that, not a hang in the graph.
- **No index changes the error you see.** Every `/query` is 503
  `INDEX_NOT_FOUND` before the injection filter runs, so an "injection → 400"
  probe reads 503 without an index. Ladder L marks those SKIP.
- **The rate limit is shared by every probe.** 60/min per IP; a long probe
  batch trips it partway and reads like random 429s. Ladder L raises the limit
  only in its scratch copy for the functional launch, then proves the shipped
  limit on a second launch.
- **`pkill -f` matches your own command line.** Kill servers by PID
  (`driver.sh stop`, or the pid you started). Ladder L turns SIGTERM into a
  clean exit so its gate and mock never outlive it.
- **`run_full_verification.py` with no `CYCLAW_REPO` tests GitHub main**, not
  your checkout, and needs network. With `CYCLAW_REPO` set it writes into that
  tree; point it at a copy.
- **Quick Mode writes in place.** It backs up and restores `soul.md`, but its
  gate appends to your `logs/` and builds `index/` if missing.
- **Three realism tiers.** Tier 0 = no HTTP backend, Tier 1 = `mock_ollama.py`,
  Tier 2 = a real daemon. `status: degraded` in `/health` is normal at Tier 0.
- **`sync.cli test` writes rclone's filter file** under `XDG_CONFIG_HOME`
  (default `~/.config/rclone/`). Ladder L points that at its scratch dir; run
  by hand, it writes your real one (the same file a real sync writes).

## Mock embedding and Chroma doubles

The swarm's doubles live in `run_full_verification.py`:
`MockSentenceTransformer` (sparse SHA-256 keyword hashing into 384 dims,
L2-normalized) and `MockChromaClient`/`MockCollection` (cosine search over a
singleton collection registry carrying the fingerprint metadata contract).
Read the script for the current shapes; they track `retrieval/` and drift if
copied here.
