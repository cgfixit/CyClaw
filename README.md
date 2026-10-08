# CyClaw

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141.1-blue.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.11-blue.svg)](https://github.com/langchain-ai/langgraph)
[![CyClaw CI/CD testing](https://github.com/cgfixit/CyClaw/actions/workflows/ci.yml/badge.svg)](https://github.com/cgfixit/CyClaw/actions/workflows/ci.yml)

[![CyClaw console answering from the local library](https://github.com/cgfixit/CyClaw/blob/main/docs/screenshots/2026-10-05-console-answered-query-1440.png)](https://github.com/cgfixit/CyClaw/tree/main/docs/screenshots)

CyClaw answers questions from **your documents on your hardware**. Its
12-node LangGraph starts with retrieval, ends every path in the audit log,
and requires per-question consent for paid Grok or Claude fallback. The
server binds to `127.0.0.1:8787`.

- Embeddings, BM25, and the cross-encoder run locally on CPU; cache both
  retrieval models before going offline.
- Soul, ops, memory, and audit routes require [operator access](#api-key-setup-soul-mutations),
  which fails closed without `CYCLAW_API_KEY` (an enabled admin's login also
  works when per-user auth is on).
- Audit records hash questions by default; the spend ledger records billed
  tokens; `cyclaw-metrics` reads both offline.
- Guardrails (NeMo in every base install), the Numbat stream, and the spend
  ledger ship on. Auth, memory, connectors, the agentic loop, and Telegram/X
  channels ship off.

CyClaw serves one trusted operator, or a mutually trusted group with auth
enabled; it provides neither tenant isolation nor a microVM
([threat model](docs/THREAT_MODEL.md)).

Step-by-step installs and every REST call: [Full Setup Guide](setup-guide.md).
Contributor rules for people and agents: [`CLAUDE.md`](CLAUDE.md), [`AGENTS.md`](AGENTS.md),
and the tracked git-hook gate in [`docs/GITHOOKS.md`](docs/GITHOOKS.md).

---

## Quick Start

**macOS (Apple Silicon)** — install, keys, Ollama, index, and startup:

```bash
git clone https://github.com/cgfixit/CyClaw && cd CyClaw
bash macos/setup-cyclaw.sh
```

**Linux** — Ollama already running on `127.0.0.1:11434`:

```bash
git clone https://github.com/cgfixit/CyClaw && cd CyClaw
python3.12 -m venv .venv && source .venv/bin/activate
pip install --require-hashes --no-deps -r requirements-torch-lock-linux.txt --index-url https://download.pytorch.org/whl/cpu
pip install --require-hashes -r requirements-lock-linux.txt
pip install -r requirements-test.txt -c constraints.txt
ollama pull qwen3.8:27b-mlx
export CYCLAW_API_KEY="$(openssl rand -hex 20)"  # operator routes; /query uses sessions/tokens when auth is on
python -m retrieval.indexer                      # once; without this, /query is 503
python gate.py                                   # http://127.0.0.1:8787
```

**Windows** uses the same pins with the `-windows` lock files
(`py -3.12 -m venv .venv`, `.\.venv\Scripts\Activate.ps1`):
[Windows](setup-guide.md#windows-powershell), [Linux](setup-guide.md#linux-bash).

Confirm: `curl http://127.0.0.1:8787/health`, then open
`http://127.0.0.1:8787/`.

Updating an existing environment? Rerun the install, then the
[NeMo verification](setup-guide.md#verify-the-installed-nemo-runtime). A manual
macOS install uses plain `torch==2.13.0` (no `+cpu` wheel) then the hashed
macOS lock ([macOS (Apple Silicon)](setup-guide.md#macos-apple-silicon)).

---

## For newcomers

**Python and install paths.** Use Python 3.12 (`>=3.12,<3.13`), not an
unversioned `python3` that may resolve to 3.11; `.venv` needs no admin rights.
Choose [native macOS](macos/README.md), [Windows](powershell/README.md), the
Linux Quick Start, or [Docker](docs/DOCKER.md) (`linux/amd64`, published on
`127.0.0.1` only). The constrained editable install in the
[setup guide](setup-guide.md) adds the `cyclaw-*` commands; `python -m …`
always works.

**Secrets.** `gate.py` reads environment variables, never dotenv files
(`Invoke-CyClaw.ps1` reads non-secret settings from an owner-only
`%USERPROFILE%\.CyClaw\.env` or checkout dotenv).

**Secret persistence.** The setup paths have different operations:

| Platform | Setup | Operation | Default secret store | Plaintext opt-in |
|---|---|---|---|---|
| macOS | `macos/setup-cyclaw-keys.sh` | Set up or preserve gateway key | Keychain | `--write-env-file` |
| Windows | `powershell/Install-CyClaw.ps1` | Migrate existing plaintext secrets | Credential Manager | `-WriteEnvFile` |

Plaintext secret lines require the platform's explicit opt-in. Services read
secrets at execution through `macos/cyclaw-keychain-env.sh` or
`powershell/CyClaw-CredMan-Env.ps1`, never from dotenv, plist, task XML,
`config.yaml`, shell rc files, or argv; a configured keystore lookup fails
closed when its item is missing. On Linux, `macos/invoke-cyclaw.sh` stores the
gateway key in libsecret or an owner-only file (`macos/cyclaw-linux-key.sh`).
A missing provider key leaves that provider unavailable, not the server down.
[Provider keys](spend/README.md#api-keys).

**Offline and hybrid.** Shipped `app.mode: hybrid` permits a paid call only
when the selected provider is enabled, available, and confirmed for that
one request; confirmation is never persisted. Set `app.mode: offline` or
decline to stay local. Model downloads are separate from that consent:
`models.embeddings.offline_after_index: true` forces local files after
indexing, and the ~91 MB reranker loads on the first query, so cache it first.

**Ports.** Gateway `127.0.0.1:8787` (`api.port`, launcher override
`CYCLAW_GATE_PORT`), Ollama `127.0.0.1:11434`. The old `:8790` coding console
is now the separate [CG-agent-harness](https://github.com/cgfixit/CG-agent-harness).

**First-run checks and limits.**

- Without an index, `/query` returns `503 INDEX_NOT_FOUND`. Run
  `python -m retrieval.indexer`, or click **Build my library** in the console
  (`POST /index/build`, loopback + same-origin + no forwarding headers, then
  `GET /index/status`); once `CYCLAW_API_KEY` is set a locked build opens the
  unlock dialog and retries after the unlock.
- The console header shows the mode in plain words ("Cloud fallback · ask
  first" or "Offline only") and **Library**/**Engine** health chips. `/health`
  reporting `degraded` usually means Ollama is down; `TELEMETRY KILL` at
  startup is expected; `/auth/*` returns 503 while auth is off.
- The 60/min per-IP rate limit resets on restart unless
  `api.rate_limit.persist_path` or a Postgres DSN is set. `/health` and
  `/index/status` are public and not rate-limited. Request bodies above
  `security.max_request_body_bytes` (1 MiB) get 413.
- Browser CORS allows `http://127.0.0.1:8787` and `http://localhost:8787`;
  `/query` always rejects cross-site requests.
- Restart the gateway after editing sanitizer config (it is cached).
  `CYCLAW_EMBED_CACHE_SIZE` (default 2048) is an env var, not a YAML key.

Check policy offline with
`python .claude/skills/invariant-guard/check_invariants.py`; the unit suite is
`GROK_API_KEY=dummy python -m pytest tests/ -q --tb=short` with no live provider.

**Local records.** Paths are relative to the repository; directory ignore
checks use representative children (`logs/evals/doc-sync-probe.json` and
`index/bm25.json`), not every descendant.

| Path | Git status | Contents and behavior |
|---|---|---|
| `logs/audit.jsonl` | ignored | Authoritative audit, written synchronously on the request thread. Questions use persistent HMAC-SHA256 fingerprints by default, including when `logging.audit_fields` is absent or empty. Explicit `include_query_hash: false` stores redacted query text |
| `logs/spend.jsonl` | ignored | Tokens for billed Grok/Claude calls, without query text or prices |
| `logs/numbat-events.ndjsonl` | ignored | Derived redacted audit and out-of-band events; observation only |
| `logs/cyclaw.log` | ignored | Application log; a bounded writer drops records rather than holding a request on stalled I/O |
| `logs/evals/` | ignored | Opt-in dogfood and judge output, separate from production billing |
| `index/` | ignored | Chroma and `bm25.json`; rebuild after corpus changes |
| `data/personality/soul.md` | tracked | Changes appear in `git status` and broad staging |
| `data/personality/cyclaw_soul.db` | ignored | Version DB; not yet generated in a clean checkout |
| `data/personality/soul.md.bak` | ignored | Vetted backup; not yet generated in a clean checkout |

Day-two:

```bash
python -m metrics                           # spend, audit aggregates, sequences
python -m retrieval.clear_cache             # dry-run; --apply deletes .emb_cache
python -m retrieval.indexer                 # rebuild after editing data/corpus/
curl -s http://127.0.0.1:8787/index/status   # build progress
```

---

## What It Does

CyClaw retrieves Markdown and `.txt` documents before generation. The
enabled output rails enforce a token-overlap floor for retrieved local
answers; that heuristic does not verify individual claims, which the separate
[evals](docs/EVALS.md) measure.

1. **Retrieval first.** `retrieve` starts the 12-node graph; a miss can still
   reach `offline_best_effort` with partial context.
2. **Hybrid search.** ChromaDB and BM25 fuse through RRF (`retrieval.rrf_k`).
   A vault hit needs the best cosine to clear `retrieval.min_semantic_score`
   (without cosines, the fused score must clear the RRF-scale
   `retrieval.min_score`); the cross-encoder runs in shadow mode
   (`retrieval.min_rerank_score: null`). [Retrieval reference](retrieval/README.md).
3. **Local generation.** Ollama runs `models.local_llm.model`, shipped as
   `qwen3.8:27b-mlx`. Tunables live in `config.yaml`.
4. **Governed soul.** `data/personality/soul.md` has SHA-256 drift detection
   and atomic writes; `POST /soul/apply` requires a human `reason` and an
   enforced injection scan. Restore, `/soul/reload`, and startup drift
   recovery are the documented unscanned or advisory exceptions, and a missing
   soul self-initializes ([Soul invariants](INVARIANTS.md), Rules 4–5).
5. **Confirmed external fallback.** Grok (`grok-4.5`, `api.x.ai`) or Claude
   (`claude-sonnet-5`, `api.anthropic.com`) requires hybrid mode, that
   provider enabled and selected, `user_confirmed_online: true` on the
   request, and a usable client (key present). Calls share the remaining
   `api.graph_timeout_sec` budget, and `utils/endpoint_trust.py` rejects
   rewritten provider URLs.
6. **HTTP and MCP.** FastAPI serves the browser at `/`; the separate MCP
   server exposes sanitized retrieval only (`sampling: None`, no generation).
7. **Audit convergence.** All eleven upstream nodes reach `audit_logger`
   before END; `cyclaw-metrics` reads the audit offline.

[The six invariants](INVARIANTS.md) cover retrieval-first entry, topology,
external consent, audit convergence, soul governance, and import isolation
(core modules never import `agentic`, `sync`, `guardrails`, `telegram`, or
`opentweet`; the invariant checker enforces it).

**Storage and console.** `indexing.vector_backend` defaults to embedded
`chroma` (optional `pgvector`); BM25 is JSON, never pickle.
`static/terminal.html` provides queries, the first-run build panel, health
chips, Soul, Sync, Agentic, Filesystem, and SQL panels, plus Users and Audit
when auth is on.

### Optional layers at a glance

| Layer | Purpose | Ships |
|---|---|---|
| [Per-user auth](#per-user-authentication) | Passwords, sessions, device tokens, roles | off |
| [Memory](docs/memory/README.md) | SQLite/FTS5 facts and episodes, propose/apply, optional retrieval fusion and HTML export | off |
| [NeMo Guardrails](#nemo-guardrails) | Deny-only input/output checks, deterministic fallback on NeMo failure | on |
| [Dropbox sync](docs/SYNC_README.md) | Out-of-band `rclone` corpus pull | CLI |
| [Connectors](agentic/README.md) | Scoped filesystem, SELECT-only SQL, passive LAN inventory | off |
| [Agentic loop](docs/agentic/AGENTIC_README.md) | GitHub context, skills, clone/plan/patch/verify, human decisions | off |
| [Telegram](docs/channels/TELEGRAM_DESIGN.md) / [OpenTweet](docs/channels/OPENTWEET_DESIGN.md) | Phone remote and X drafts through loopback `/query` | off |
| [Numbat stream](docs/security-philosophy/numbat_secondary_evaluator.md) / [pre-action hook](docs/security-philosophy/numbat_pre_action_gate.md) | Derived NDJSON, observation only; deny-only gate before a confirmed external call | on / off |
| [Spend ledger](#spend-tracking) | Billed token counts | on |
| [Fine-tune kit](tools/lora_finetune/README.md) | Separate QLoRA toolkit | toolkit |

---

## Architecture

`gate.py` initializes the soul at startup. Requests pass the body cap, the
Host allowlist, applicable authentication, a **60/min per-IP limit before
injection filtering**, and the config-driven filter before entering the graph
as `GraphState`. Graph edges control routing. [Operating contract](CLAUDE.md)
and [security invariants](INVARIANTS.md).

```mermaid
flowchart TD
    A(["Client\nHTTP POST /query"])
    A --> B

    subgraph GATEWAY ["gate.py — FastAPI 127.0.0.1:8787"]
        B["TrustedHostMiddleware\nHost header allowlist"]
        B --> C["Rate Limiter\n60 req/min per IP"]
        C --> D["Prompt Injection Filter\n40 patterns · config-driven"]
        D --> E["Build GraphState\nquery + user_confirmed_online"]
    end

    E --> F

    subgraph GRAPH ["graph.py — LangGraph 12-node State Machine"]
        F(["retrieve\nChroma + BM25 + RRF"])
        F --> G["route_by_score\nbest cosine ≥ 0.30?\n(RRF ≥ 0.028 if no cosine)"]
        G -->|"YES — local context"| X["guardrail_input\noffline rail · default on"]
        X -->|"blocked"| L
        X -->|"passed · high score"| H["local_llm\nOllama :11434"]
        G -->|"NO — vault miss"| I["user_gate\nneeds_confirm = true"]
        I -->|"confirmed + hybrid\n+ grok.enabled + provider=grok"| PG["pre_action_hook_grok\ndeny-only · off = pass-through"]
        PG -->|"allow"| J["grok_fallback\ngrok-4.5 · triple-gated"]
        I -->|"confirmed + hybrid\n+ claude.enabled + provider=claude"| PC["pre_action_hook_claude\ndeny-only · off = pass-through"]
        PC -->|"allow"| W["claude_fallback\nclaude-sonnet-5 · triple-gated"]
        I -->|"declined or offline"| X
        X -->|"passed · vault miss"| K["offline_best_effort\nlocal LLM · no RAG gate"]
        I -->|"confirmed=None — pause"| L
        H --> Y["guardrail_output\noffline rail · default on\ngrounding: local_llm only"]
        J --> Y
        W --> Y
        K --> Y
        Y --> L
        PG -.->|"deny"| L
        PC -.->|"deny"| L
        L(["audit_logger\nHMAC fingerprint · PII redact\nlogs/audit.jsonl\n+ derived Numbat stream"])
    end

    L --> M(["QueryResponse\nanswer · sources · model_used\nretrieval_mode · needs_confirm"])

    subgraph RETRIEVAL ["retrieval/hybrid_search.py"]
        N["ChromaDB\nsemantic · 384-dim cosine"]
        O["BM25Okapi\nkeyword · Porter stemming"]
        P["RRF fusion\nk=60 · equal weighting"]
        N --> P
        O --> P
    end

    F <-->|"hybrid search"| P

    subgraph SOUL ["utils/personality.py"]
        Q["soul.md\nSHA-256 drift detection"]
        R["SQLite / Postgres\nversion history"]
        Q <--> R
    end

    H <-->|"soul preamble\n≤ 8000 chars"| Q
    K <-->|"soul preamble"| Q
```

The MCP server calls the retriever directly after sanitization and never
enters this gateway or graph. The diagram omits the per-answer NeMo `check()`
and the post-graph CEL monitor ([Optional layers](#optional-layers)).

---

## Installation

Platform steps, Docker, conda (`environment.yml`), and first index:
[`setup-guide.md`](setup-guide.md) (macOS installs plain `torch==2.13.0`;
Windows and Linux use the `+cpu` wheel). Scripts:
[`macos/README.md`](macos/README.md), [`powershell/README.md`](powershell/README.md);
image: [`docs/DOCKER.md`](docs/DOCKER.md).

---

## API Key Setup (Soul Mutations)

`/soul/*`, `/ops/*`, `/memory/*`, `/query/export/html`, and `/audit/summary`
require operator access. `/health` is public; `/query` requires a session
or device token when `auth.enabled` is true. Operator credentials are:

- **Bearer `CYCLAW_API_KEY`**, for HTTP clients and scripts (compared with
  `hmac.compare_digest`).
- **The console cookie.** "Unlock operator tools" trades the key once for
  an HttpOnly, `SameSite=Strict` cookie (`security.console_session_ttl_sec`,
  1 h shipped); "Lock" deletes it, and rotating the key revokes every cookie.
- **An admin login**, when `auth.enabled` is on (no key needed); `operator`
  and `audit` accounts do not get operator access.

Cookie writes need CSRF tokens, cookies reject cross-site requests, console
tokens bind the request origin, and TLS uses `__Host-` cookies. Cookies
cannot be port-scoped, so use a dedicated hostname plus TLS when other
services on the same host are untrusted. Without `CYCLAW_API_KEY`, Bearer and
console-cookie access fail closed.

`macos/invoke-cyclaw.sh` and `powershell\Invoke-CyClaw.ps1` generate a
missing key into the OS keystore and open a single-use `#pair=...` unlock
link (5 minutes). To unlock by hand, copy the key into the dialog:

```bash
# macOS
security find-generic-password -a "$(whoami)" -s com.cgfixit.cyclaw.api-key -w | pbcopy
```

```powershell
# Windows, from the CyClaw folder
. .\powershell\CyClaw-SecretStore.ps1; (Read-CyclawCredential com.cgfixit.cyclaw.api-key).Secret | Set-Clipboard
```

Do not persist the key with `setx` or a user environment variable; the
launchers read it from the keystore into the gateway process only
([`powershell/README.md`](powershell/README.md#secret-classification)).
Rotation, the macOS bootstrap, and 401 recovery:
[`macos/README.md`](macos/README.md#key-bootstrap).

`security.api_key_optional` ships `false`; when set, a request skips the key
only if the socket peer is loopback, no forwarding header is present, and the
request is not cross-site (inert under Docker NAT). Full boundary:
[`INVARIANTS.md`](INVARIANTS.md) Rule 6 and the
[threat model](docs/THREAT_MODEL.md) (eighteenth amendment).

## Per-User Authentication

Separate from the operator API key. `gate_auth.py`: scrypt passwords, a
session cookie plus CSRF for browsers, named device tokens for scripts, roles
`admin`, `operator`, and `audit`. Ships `auth.enabled: false`; while off,
every `/auth/*` route returns 503. Design, TLS, and the non-loopback bind
rule: [`docs/AUTHENTICATION_DESIGN.md`](docs/AUTHENTICATION_DESIGN.md);
first-boot `curl` and `cyclaw-user`:
[`setup-guide.md`](setup-guide.md#authentication-routes-auth-off-by-default).
`cyclaw-gen-cert` writes the self-signed cert for the auth + TLS bind exception.

---

## Spend Tracking

Billed Grok/Claude calls append tokens to `logs/spend.jsonl`; dollars are
computed at read time, so rate-card corrections re-price history. Rows
exclude queries, prompts, and keys, and a write failure drops the row without
failing the answer. Core Grok/Claude requests also reserve a durable call
allowance before each POST attempt, including retries: 100 per UTC day and
1,000 per UTC month by default (zero denies all), excluding optional agentic
providers and not enforcing dollar spend.

| `source` | Writer | Covers |
|---|---|---|
| `query` | `llm/client.py` | Confirmed `/query` fallback |
| `agentic` | `agentic/deepagent_github/chat_client.py` | Out-of-band planner calls |
| `eval` | `tests/judge_eval.py` | Opt-in judge runs, kept separately under `logs/evals/` |

`python -m metrics` reports `today` and `last_7d` tokens and USD by provider
and source, and its forensic Sequences section flags a blocked injection
followed within 15 minutes by a paid call (no policy enforced).
`tests/spend_live_probe.py` **spends real money** and is opt-in only.
[Ledger schema, rate bands, and probes](spend/README.md).

---

## Benchmarks and Evals

Only the retrieval gate blocks merges; none of these four paths is a graph
node or a security control. [Thresholds and limits](docs/EVALS.md).

| Evaluation | Command | Scope |
|---|---|---|
| Retrieval gate | `python -m tests.ci_rag_smoke` | Every PR, no LLM. Corpus probes through `route_by_score_node`, then hit@5, Recall@5, and MRR on the 52-case fixture (44 scored, 8 out-of-corpus skipped). Metric floors and `[FILTERED]` injection-chunk assertions block CI |
| Local dogfood | `CYCLAW_EVAL_DOGFOOD=1 python scripts/cyclaw-eval-dogfood.py` | Opt-in real loopback model, one case per category ([recipe](tests/fixtures/groundedness/DOGFOOD.md)) |
| Anthropic judge | `CYCLAW_EVAL_LIVE=1 python tests/judge_eval.py` | Paid opt-in Claude grades groundedness, completeness, abstention |
| Local judge | Same command with `evals.local_judge.enabled: true` | Same rubric on a second loopback model from another family |

Fixture retrieval reached 1.0 for hit@5, Recall@5, and MRR (no claim about
arbitrary corpora). The [reranker bake-off](docs/audits/2026-09-26-reranker-bakeoff.md)
found no passing threshold, so vetoing stays off; the one published local run
is the [Qwen dogfood audit](docs/audits/2026-09-12_Local_Qwen_Dogfood_Matrix.md),
and no judge-plane result has been published.

---

## Current development

This README was checked against [`origin/main` at `6b9172b`](https://github.com/cgfixit/CyClaw/commit/6b9172baf18919fa48e1ac1d5014c3918edd5da1)
on 2026-10-08, with [#1585](https://github.com/cgfixit/CyClaw/pull/1585) assumed merged. Recent changes:

| PR | Change |
|---|---|
| [#1573](https://github.com/cgfixit/CyClaw/pull/1573), [#1577](https://github.com/cgfixit/CyClaw/pull/1577), [#1583](https://github.com/cgfixit/CyClaw/pull/1583), [#1585](https://github.com/cgfixit/CyClaw/pull/1585) | Agent-neutral secrets/privacy gate in the tracked git hooks: Claude Code's SessionStart hook and the Copilot setup steps activate it automatically, every other agent runs `scripts/ensure-githooks.sh` once per clone ([`docs/GITHOOKS.md`](docs/GITHOOKS.md)) |
| [#1580](https://github.com/cgfixit/CyClaw/pull/1580), [#1581](https://github.com/cgfixit/CyClaw/pull/1581) | Agents verify by running code, lint, and GitHub Actions, not local full-suite runs |
| [#1549](https://github.com/cgfixit/CyClaw/pull/1549), [#1576](https://github.com/cgfixit/CyClaw/pull/1576), [#1554](https://github.com/cgfixit/CyClaw/pull/1554) | Agentic verification confined under Seatbelt or bubblewrap, fail-closed elsewhere |
| [#1548](https://github.com/cgfixit/CyClaw/pull/1548), [#1570](https://github.com/cgfixit/CyClaw/pull/1570) | Hashed runtime and test installs in CI, the Dockerfile, and the macOS/Windows installers (the Linux Quick Start's test install stays unhashed) |
| [#1547](https://github.com/cgfixit/CyClaw/pull/1547), [#1564](https://github.com/cgfixit/CyClaw/pull/1564) | Request-body cap, hardened credential input, database-URL validation |
| [#1561](https://github.com/cgfixit/CyClaw/pull/1561) | Linux launcher stores `CYCLAW_API_KEY` in libsecret or a 0600 file |
| [#1559](https://github.com/cgfixit/CyClaw/pull/1559), [#1562](https://github.com/cgfixit/CyClaw/pull/1562), [#1565](https://github.com/cgfixit/CyClaw/pull/1565), [#1566](https://github.com/cgfixit/CyClaw/pull/1566) | Console first-run fixes, Library/Engine chips, one error entry on generation failure, `LLM_UNAVAILABLE` for refused local models |


---

## Optional layers

**Dropbox sync.** `rclone` pulls into `data/corpus/` outside the request
path, bounded by `max_delete`, `max_transfer`, and a single-instance lock;
exit code 10 signals a reindex. `python -m sync.cli setup`, then `test`,
`sync --dry-run`, `sync`, `status`, `schedule`, or `unschedule`
([guide](docs/%21%20How-To-Guides/Dropbox_Sync_Guide.md), [CLI](docs/SYNC_README.md)).

**Native scheduling.** Generators write plist/task files and print load
commands; token-bearing jobs use the keystore wrappers, and a supervised
gateway (`macos/generate_service_plist.py`, `windows/generate_service_task.py`)
requires `--confirm` and a non-empty `--reason`
([macOS operations](macos/README.md), [launchd design](docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md)).

**Fine-tuning.** The separate QLoRA kit is excluded from runtime installs and
audited separately; `finetune_qwen38.py` can download its base checkpoint, so
seed caches before a no-egress run. GPU-free dry run:
`python tools/lora_finetune/build_cyclaw_corpus.py`, then
`python tools/lora_finetune/dryrun_finetune.py`
([toolkit](tools/lora_finetune/README.md)).

**Agentic coding.** `agentic.enabled: false` makes the out-of-band CLI a
no-op; writes also need a per-call `reason` and `confirm`, and
`allow_git_write_tools` ships false. `python -m agentic.cli real-repo-run`
clones into a jail, plans, patches, and verifies, then waits for a human
decision before committing; push and draft PR are separate decisions. Checks
run in fresh gitless copies under Linux bubblewrap or macOS Seatbelt and fail
closed without them (Windows refuses); no platform uses a microVM
([threat model](docs/THREAT_MODEL.md)). `real-repo-run*` is CLI-only
(`POST /ops/agentic` returns 422).

```bash
python -m agentic.cli status
python -m agentic.cli context --repo          # also --pr 123 / --issue 45
python -m agentic.cli propose-skill --name deploy --desc "..." --body-file s.md --reason "draft"
```

[Real-repo loop](agentic/README.md#2-real-repo-coding-loop),
[governed harness](docs/agentic/AGENTIC_README.md#9-governed-github-coding-harness),
and [write rollback](docs/agentic/GITHUB_WRITE_ENABLEMENT.md).

**Connectors.** All three ship off, outside the request path: `fsconnect`
(bounded reads; writes gated, refused on Windows), `sqlconnect` (SELECT/WITH
only), and `netconnect` (passive, explicit RFC1918/loopback CIDRs).
[Filesystem](agentic/README.md#5-filesystem-connector),
[SQL](agentic/README.md#6-sql-connector-read-only), and
[passive network](agentic/README.md#7-passive-network-connector).

### NeMo Guardrails

`guardrails.enabled: true` ships in `config.yaml`; explicit `false` or an
absent block disables it. `utils/guardrail_bridge.py` is the graph's only path
to `guardrails/`.

| Guard | Scope and refusal |
|---|---|
| Offline graph input | Local and best-effort paths; returns `block_message` through `audit_logger` without a model call |
| Offline graph output | `local_llm` only; replaces answers below `hallucination_threshold` (0.18) or matching soul-leak markers |
| NeMo `check()` | Wraps all four answer nodes (`nemoguardrails==0.24.0`); input refusal skips generation, output refusal replaces the answer |
| Broker fallback | Missing, failed, or unsupported live verdicts run deterministic input and soul-leak checks on every answer route; grounding stays `local_llm` only |

Active rails are Python checks and add no model calls; NVIDIA's
model-assisted `self_check_*` rails are inactive. NeMo failures audit
`guardrail_degraded`. Existing environments: rerun the install, then
`python -m pip check` and `python -m guardrails.verify_install`
([setup guide](setup-guide.md#verify-the-installed-nemo-runtime),
[package guide](guardrails/README.md), [NeMo reference](docs/NeMo/README.md),
[Track B record](docs/audits/2026-10-03-nemo-track-b.md)).

### Numbat

CyClaw calls the external CLI pinned at 0.2.0 (schema 0.3.0); it never
vendors or imports it.

| Piece | Switch | Default and behavior |
|---|---|---|
| Stream | `numbat.enabled` | On. `utils/numbat_emitter.py` writes redacted audit/out-of-band events to `logs/numbat-events.ndjsonl` (rolls at 50 MiB); its bounded writer cannot hold requests |
| Pre-action hook | `policy.fallback.pre_action_hook.enabled` | Off. Prepared with `engine: numbat` and monitor-only rules in `config/numbat/gate/`; after consent, `rules test --no-builtin-rules` denies enforcing matches and every engine failure |
| CEL monitor | `numbat.cel.enabled`, extra `numbat-cel` | Off. Two structured-field rules observe weak-retrieval cloud answers and hook/guardrail refusals after `/query`; never blocks |
| Offline scoring | None | Operator CLI and `numbat-rules.yml`; fixture, stream-contract, and CEL checks block CI |

Nothing scores the live file during a request. The CLI and CEL extra are
not in standard installs, so keep their switches off until installed
(enabling the hook without the binary denies every confirmed external call),
trial the maintained rules before promoting any to `enforce: true`, and avoid
`numbat hook` as the command engine (it exits 0 on errors). Stream events
include hostname, user, and uid. Once enabled, the hook and CEL report
readiness in `/health`, and `/audit/summary` shows `pre_action_hook_last_verdict`.
[Pre-action gate](docs/security-philosophy/numbat_pre_action_gate.md),
[stream](docs/security-philosophy/numbat_secondary_evaluator.md),
[phase status](docs/plans/NUMBAT_AND_ALWAYS_ON_ROADMAP.md), and the
[Track A acceptance record](docs/audits/2026-10-03-numbat-track-a.md).

### Telegram and OpenTweet

Disabled by default, both call loopback `POST /query` outside the core graph
imports, with credentials from the environment variable named in config.
Telegram supports outbound `notify` or long-poll `chat` (no public webhooks)
and requires non-empty `allowed_chat_ids`; only the exact
`/online on <grok|claude>` command, with `allow_hybrid_confirm` on (default
off), can confirm one paid call, and the triple gate still applies. OpenTweet
forces `user_confirmed_online: false` and writes drafts by default;
`scheduled_date` needs `opentweet.schedule_enabled`, and schedulers never send
`publish_now`. Inspect either with `python -m telegram.cli status` /
`python -m opentweet.cli status`.
[Telegram design](docs/channels/TELEGRAM_DESIGN.md),
[Telegram operations](telegram/README.md),
[OpenTweet design](docs/channels/OPENTWEET_DESIGN.md), and
[OpenTweet operations](opentweet/README.md).

---

## Security Model

| Layer | Mechanism |
|---|---|
| Network | Binds `127.0.0.1:8787`; request bodies capped at 1 MiB (`security.max_request_body_bytes`). A non-loopback `api.host` is refused except the documented auth + TLS path, or `CYCLAW_ALLOW_NON_LOOPBACK_BIND` ([bind guard](docs/AUTHENTICATION_DESIGN.md#7-interaction-with-the-main-bind-guard-825)) |
| Endpoint trust | Local nodes: loopback or an exact host in `models.local_llm.trusted_hosts` (ships `[]`). Online nodes: `api.x.ai` and `api.anthropic.com` only |
| Input | `policy.prompt_filter`: 40 `banned_patterns`, `max_input_chars`; same filter on MCP search |
| Rate limit | 60 req/min per IP, after same-origin rejection and before the filter; in-memory unless SQLite or Postgres is set |
| Proxy bypass | `httpx` clients set `trust_env=False` |
| Telemetry | Kill maps before any SDK import (invariant-guard G1), plus ONNX's post-import call; not a network firewall ([`SECURITY.md`](SECURITY.md)) |
| Audit | HMAC-SHA256 query fingerprint + redacted metadata in `logs/audit.jsonl`, then the derived Numbat stream |
| Grok / Claude | [Triple gate](#what-it-does) item 5, then the opt-in deny-only pre-action hook |
| Soul writes | Human `reason` + enforced scan + atomic replace on `POST /soul/apply` only ([What It Does](#what-it-does) item 4 lists the exceptions) |
| API key | Fail closed. Bearer key, console cookie, or (with `auth.enabled`) an admin login; cookie writes need CSRF; the loopback bypass needs `security.api_key_optional` plus three more conditions ([API Key Setup](#api-key-setup-soul-mutations)) |
| Guardrails | Enabled by default, deny-only; NeMo failures use deterministic checks and audit `guardrail_degraded` |
| Optional surfaces | Agentic writes, connectors, channels, and `/memory/*` ship off; `/ops/*` needs operator access and runs subprocess argv lists; no tokens in plist or task XML |
| `/auth/*` | Present either way; 503 while auth is off. When on, `/query` needs a session or device token; the last `admin` cannot be removed |
| Container | Non-root, `no-new-privileges`, dropped caps, read-only rootfs; optional Falco (`deploy/falco/`) ships off |
| Dependency risk | `chromadb==1.5.9` carries CVE-2026-45829, accepted only for embedded `PersistentClient`. [`SECURITY.md`](SECURITY.md) |
| Commit-time gate | Tracked `.githooks/` refuse secrets and private data at commit and push, protected-path edits at commit (reminder only at push), and main/force pushes without an operator override ([`docs/GITHOOKS.md`](docs/GITHOOKS.md)) |

Full threat model: [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md). Design
notes: [`docs/security-philosophy/`](docs/security-philosophy/).

---

## Project Structure

```text
CyClaw/
├── gate.py                 # FastAPI gateway
├── gate_ops.py             # /ops/* subprocess shims
├── gate_auth.py            # /auth/*
├── gate_memory.py          # /memory/* + /query/export/html
├── graph.py                # 12-node LangGraph
├── metrics.py              # cyclaw-metrics: audit + spend + sequences
├── mcp_hybrid_server.py    # retrieval-only MCP
├── config.yaml             # tunables
├── retrieval/              # indexer, hybrid search, embeddings, rerank, vector_store
├── llm/client.py           # local, Grok, Claude
├── memory/                 # optional facts + episodes (default off)
├── agentic/                # GitHub context, real-repo loop, executor, connectors
├── guardrails/             # default-on rails, reached only via guardrail_bridge
├── telegram/  opentweet/   # optional channels, shipped off
├── sync/                   # optional Dropbox pull
├── utils/                  # sanitizer, logger, personality, spend, numbat_*,
│                           # endpoint_trust, authn*, console_session, telemetry_kill
├── macos/  powershell/  windows/   # native installers and schedulers
├── spend/                  # ledger reference
├── schemas/  static/  tests/  docs/  deploy/
├── tools/lora_finetune/    # operator QLoRA kit, not a runtime extra
└── .github/workflows/
```

`data/corpus/` is the sample corpus, `data/personality/soul.md` the live
soul; `data/agentic/skills_registry.json` ships empty.

---

## Documentation Map

| Read this | When you want |
|---|---|
| [`setup-guide.md`](setup-guide.md) | Install paths, Docker, conda, and every REST call |
| [`INVARIANTS.md`](INVARIANTS.md) | I1–I6, code vs convention, and the test that pins each |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) / [`docs/GITHOOKS.md`](docs/GITHOOKS.md) | Request-path map, agent rules, and the commit/push security gate |
| [`SECURITY.md`](SECURITY.md) / [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Egress, accepted CVEs, disclosure; scope, bind exceptions, amendments |
| [`docs/AUTHENTICATION_DESIGN.md`](docs/AUTHENTICATION_DESIGN.md) / [`docs/DOCKER.md`](docs/DOCKER.md) | Per-user auth; GHCR image and compose hardening |
| [`docs/EVALS.md`](docs/EVALS.md) / [`spend/README.md`](spend/README.md) | The four eval planes and their floors; ledger schema and live probes |
| [`docs/memory/README.md`](docs/memory/README.md) / [`retrieval/README.md`](retrieval/README.md) | Facts, episodes, propose/apply; hybrid search, the cosine gate, the shadow reranker |
| [`docs/security-philosophy/`](docs/security-philosophy/) | Telemetry suppression, offline operation, and Numbat designs |
| [`guardrails/README.md`](guardrails/README.md) / [`docs/NeMo/README.md`](docs/NeMo/README.md) | Rail semantics and what is display-only |
| [`docs/agentic/AGENTIC_README.md`](docs/agentic/AGENTIC_README.md) | Real-repo loop, exit codes, and the write gate |
| [`macos/README.md`](macos/README.md) / [`powershell/README.md`](powershell/README.md) | Keychain, Credential Manager, 401 recovery |

---

## License

Source-available, all rights reserved; personal use is permitted. See
[`LICENSE`](LICENSE).

*Designed and built by Chris Grady, with AI tooling used under human review,
CI, and the invariant guard.*
