# CyClaw

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141.1-blue.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.11-blue.svg)](https://github.com/langchain-ai/langgraph)
[![CyClaw CI/CD testing](https://github.com/cgfixit/CyClaw/actions/workflows/ci.yml/badge.svg)](https://github.com/cgfixit/CyClaw/actions/workflows/ci.yml)

[![Local RAG console](https://github.com/cgfixit/CyClaw/blob/main/docs/screenshots/2026-09-11-local-rag-and-injection-verification.png)](https://github.com/cgfixit/CyClaw/tree/main/docs/screenshots)

CyClaw answers questions from **your documents on your hardware**. Its
12-node LangGraph starts with retrieval, ends every path in the audit log,
and requires per-question consent for paid Grok or Claude fallback. The
server binds to `127.0.0.1:8787`.

- Local embeddings, BM25, and the cross-encoder run on CPU. Cache both
  retrieval models before offline use; downloads are separate from paid-call consent.
- Soul, ops, memory, and audit routes require [operator access](#api-key-setup-soul-mutations).
  Bearer and console-cookie credentials fail closed without `CYCLAW_API_KEY`;
  an enabled admin's login also works when per-user auth is on.
- Audit records hash questions by default. The spend ledger records tokens
  and computes dollars at read time. `cyclaw-metrics` joins both offline.
- Auth, memory, guardrails, connectors, the agentic loop, and Telegram/X
  channels ship disabled. The local Numbat stream and spend ledger ship on.

CyClaw serves one trusted operator or a mutually trusted group with auth
enabled. It provides neither tenant isolation nor a microVM.
See the [threat model](docs/THREAT_MODEL.md).

## Table of Contents

- [Quick Start](#quick-start)
- [For newcomers](#for-newcomers)
- [What It Does](#what-it-does)
- [Architecture](#architecture)
- [Installation](#installation)
- [API Key Setup (Soul Mutations)](#api-key-setup-soul-mutations)
- [Per-User Authentication](#per-user-authentication)
- [Spend Tracking](#spend-tracking)
- [Benchmarks and Evals](#benchmarks-and-evals)
- [Current development](#current-development)
- [Optional layers](#optional-layers)
- [Security Model](#security-model)
- [Project Structure](#project-structure)
- [Documentation Map](#documentation-map)
- [License](#license)

Step-by-step installs and every REST call: [Full Setup Guide](setup-guide.md).

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
pip install torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r requirements-test.txt -c constraints.txt --ignore-installed PyYAML
ollama pull qwen3.8:27b-mlx
export CYCLAW_API_KEY="$(openssl rand -hex 20)"  # operator routes; /query uses sessions/tokens when auth is on
python -m retrieval.indexer                      # once; without this, /query is 503
python gate.py                                   # http://127.0.0.1:8787
```

**Windows** uses the same pins (`py -3.12 -m venv .venv`,
`.\.venv\Scripts\Activate.ps1`). [Windows](setup-guide.md#windows-powershell)
and [Linux](setup-guide.md#linux-bash).

Confirm: `curl http://127.0.0.1:8787/health`, then open
`http://127.0.0.1:8787/`.

> **Manual macOS install differs in one step.** There is no `+cpu` torch
> wheel for macOS. Install plain `torch==2.13.0` from stripped copies of
> `requirements.txt` and `constraints.txt`:
> [macOS (Apple Silicon)](setup-guide.md#macos-apple-silicon).

---

## For newcomers

**Python and install paths.** Use Python 3.12 (`>=3.12,<3.13`), not an
unversioned `python3` that resolves to 3.11. Creating `.venv` needs no admin
rights. Choose [native macOS](macos/README.md), [Windows](powershell/README.md),
the Linux Quick Start, or [Docker](docs/DOCKER.md). The GHCR image targets
`linux/amd64`; publish only on host `127.0.0.1`. Use native Apple Silicon
until an arm64 image is verified.

`pip install -e .` creates `cyclaw-server`, `cyclaw-index`, `cyclaw-mcp`,
`cyclaw-metrics`, `cyclaw-user`, `cyclaw-gen-cert`, and `cyclaw-clear-cache`.
Without it, use the corresponding `python -m …` commands.

**Secrets.** `gate.py` reads environment variables, never dotenv files.
`Invoke-CyClaw.ps1` reads non-secret settings from the first owner-only
file found, preferring `%USERPROFILE%\.CyClaw\.env` over a checkout dotenv.

**Secret persistence.** The setup paths have different operations:

| Platform | Setup | Operation | Default secret store | Plaintext opt-in |
|---|---|---|---|---|
| macOS | `macos/setup-cyclaw-keys.sh` | Set up or preserve gateway key | Keychain | `--write-env-file` |
| Windows | `powershell/Install-CyClaw.ps1` | Migrate existing plaintext secrets | Credential Manager | `-WriteEnvFile` |

The owner-only dotenv holds ordinary settings. Plaintext secret lines require
the platform's explicit opt-in; the Windows installer does not generate a missing key.

Services obtain secrets only at execution through
`macos/cyclaw-keychain-env.sh` or `powershell/CyClaw-CredMan-Env.ps1`, never
from dotenv, plist, task XML, `config.yaml`, shell rc files, or argv.
`windows/generate_service_task.py` injects the gateway key only with
`--api-key-target`; populate it with
`powershell/CyClaw-CredMan-Set.ps1 com.cgfixit.cyclaw.api-key`. Configured
keystore lookups fail closed when an item is missing. Missing provider
keys leave the server running with that provider unavailable.
[Provider keys](spend/README.md#api-keys).

**Offline and hybrid.** Shipped `app.mode: hybrid` permits paid calls only
when the selected provider is enabled, available, and confirmed for that
request. Both providers ship enabled. Confirmation is never persisted.
Set `app.mode: offline` or decline confirmation to keep generation local;
`offline_best_effort` can use partial context after a vault miss.

Embedding and reranker downloads do not use that consent flag. After a
completed index, `models.embeddings.offline_after_index: true` forces both
loaders onto local files. The reranker loads on the first query, not during
indexing, so cache its roughly 91 MB model before expecting offline use.

**Ports.** Gateway `127.0.0.1:8787` (`api.port`, launcher override
`CYCLAW_GATE_PORT`), Ollama `127.0.0.1:11434`, and optional local failover
(example `127.0.0.1:1234`, disabled by default). The removed `:8790` coding
console is now the separately installed
[CG-agent-harness](https://github.com/cgfixit/CG-agent-harness); CyClaw does
not start it.

**First-run checks and limits.**

- Without an index, `/query` returns `503 INDEX_NOT_FOUND`. Run
  `python -m retrieval.indexer` or use the browser's `POST /index/build`
  action and poll `GET /index/status`.
- Check `curl -s http://127.0.0.1:8787/health` for `index_ready`, then ask
  the browser a question covered by `data/corpus/`. `degraded` usually
  means Ollama is down, not a server crash. `TELEMETRY KILL` at startup is expected.
- Soul, ops, memory, and `/audit/summary` require
  [operator access](#api-key-setup-soul-mutations). `/auth/*` returns 503
  while auth is disabled.
- The 60/min per-IP rate limit resets on restart unless
  `api.rate_limit.persist_path` or its Postgres DSN is configured.
  `/health` and `/index/status` are unauthenticated and unrate-limited
  for console polling. Concurrent health calls share probes behind a short cache.
- External provider probes are absent unless
  `api.health_probe_external_providers` is enabled; it ships `false`.
  Browser CORS allows `http://127.0.0.1:8787` and `http://localhost:8787`,
  not a portless origin. `/query` always rejects cross-site requests.
- `CYCLAW_EMBED_CACHE_SIZE` fixes the query-cache size at import
  (default 2048); it is not a YAML key. The sanitizer caches by config
  path, so restart the gateway after editing its configuration.

Verify policy without services with
`python .claude/skills/invariant-guard/check_invariants.py`. Run unit tests
with `GROK_API_KEY=dummy python -m pytest tests/ -q --tb=short`; they use no
live provider. `python -m tests.ci_rag_smoke` checks retrieval floors with
cached models.

**Local records.** Paths are relative to the repository. Directory ignore checks
use representative children (`logs/evals/doc-sync-probe.json` and `index/bm25.json`),
not a guarantee about every possible descendant.

| Path | Git status | Contents and behavior |
|---|---|---|
| `logs/audit.jsonl` | ignored | Authoritative audit, written synchronously on the request thread. Questions are SHA-256 hashes by default, including when `logging.audit_fields` is absent or empty. Explicit `include_query_hash: false` stores redacted query text |
| `logs/spend.jsonl` | ignored | Tokens for billed Grok/Claude calls, without query text or prices |
| `logs/numbat-events.ndjsonl` | ignored | Derived redacted audit and out-of-band events; observation only |
| `logs/cyclaw.log` | ignored | Application log; a bounded writer drops records rather than holding a request on stalled I/O |
| `logs/evals/` | ignored | Opt-in dogfood and judge output, separate from production billing |
| `index/` | ignored | Chroma and `bm25.json`; rebuild after corpus changes |
| `data/personality/soul.md` | tracked | Changes appear in `git status` and broad staging |
| `data/personality/cyclaw_soul.db` | ignored | Version DB; not yet generated in a clean checkout |
| `data/personality/soul.md.bak` | ignored | Vetted backup; not yet generated in a clean checkout |

Day-two commands:

```bash
python -m metrics                           # spend, audit aggregates, sequences
python -m retrieval.clear_cache             # dry-run; --apply deletes .emb_cache
python -m retrieval.indexer                 # rebuild after editing data/corpus/
curl -s http://127.0.0.1:8787/index/status   # build progress
```

---

## What It Does

CyClaw retrieves Markdown and `.txt` documents before generation. Groundedness
is measured in CI, not enforced by another graph node.

1. **Retrieval first.** `retrieve` starts the 12-node graph. A miss can still
   reach `offline_best_effort` with partial context.
2. **Hybrid search.** ChromaDB and BM25 fuse through RRF (`retrieval.rrf_k`).
   A vault hit needs the best cosine in the local context window to clear
   `retrieval.min_semantic_score`. Without cosines, the top fused score must
   clear `retrieval.min_score`, which uses the RRF scale. The cross-encoder
   runs in shadow mode: `retrieval.min_rerank_score: null` audits
   `rerank_best` without vetoing hits. A numeric threshold can only demote
   a hit. An unavailable reranker preserves the cosine rule and records
   `rerank_degraded`. Both retrieval models can download missing snapshots;
   cache them before offline use. [Retrieval reference](retrieval/README.md).
3. **Local generation.** Ollama uses `models.local_llm.model`, shipped as
   `qwen3.8:27b-mlx`. `models.local_llm.fallback` ships disabled. Tunables
   live in `config.yaml`.
4. **Governed soul.** `data/personality/soul.md` has SHA-256 drift detection
   and atomic writes. `POST /soul/apply` requires a human `reason` and the
   enforced injection scan. Restore reapplies the vetted `.bak` with only
   advisory scanning. Startup drift recovery and `/soul/reload` adopt
   on-disk content unscanned; a missing soul self-initializes at boot.
   [Soul invariants](INVARIANTS.md), Rules 4–5.
5. **Confirmed external fallback.** Grok (`grok-4.5`, `api.x.ai`) or Claude
   (`claude-sonnet-5`, `api.anthropic.com`) requires hybrid mode, that
   provider enabled, `user_confirmed_online: true`, provider selection,
   and a usable client. Gateway construction enforces mode and enablement;
   graph routing enforces the per-request decision. The first request can
   carry confirmation. Calls use the remaining `api.graph_timeout_sec`
   budget, and `utils/endpoint_trust.py` rejects rewritten provider URLs.
6. **HTTP and MCP.** FastAPI serves the browser at `/`. The separate MCP
   server exposes sanitized retrieval only, with `sampling: None` and no
   generation path. `notifications/*` messages receive no reply.
7. **Audit convergence.** All eleven upstream nodes reach `audit_logger`
   before END. `cyclaw-metrics` reads the audit offline.

[The six invariants](INVARIANTS.md) cover retrieval-first entry, topology,
external consent, audit convergence, soul governance, and import isolation.
Core modules do not import `agentic`, `sync`, `guardrails`, `telegram`, or
`opentweet`; the invariant checker enforces that boundary.

**Storage and console.** `indexing.vector_backend` defaults to embedded
`chroma`; optional `pgvector` requires Postgres. BM25 uses JSON, never
pickle. `sqlite-vec` remains a test prototype because macOS CI cannot load
the extension ([spike notes](docs/audits/2026-09-21-sqlite-vec-phase-c-spike.md)).
`static/terminal.html` provides queries, index progress, Soul, Sync,
Agentic, Filesystem, and SQL panels, plus Users and Audit when auth is on.

### Optional layers at a glance

| Layer | Purpose | Ships |
|---|---|---|
| [Per-user auth](#per-user-authentication) | Passwords, sessions, device tokens, and roles | off |
| [Memory](docs/memory/README.md) | SQLite/FTS5 facts and episodes, propose/apply, optional retrieval fusion and HTML export. Consolidation remains an inert stub | off |
| [NeMo Guardrails](#optional-layers) | Deny-only input/output checks, audited fail-open behavior | off |
| [Dropbox sync](docs/SYNC_README.md) | Out-of-band `rclone` corpus pull | CLI |
| [Connectors](agentic/README.md) | Scoped filesystem, SELECT-only SQL, passive LAN inventory | off |
| [Agentic loop](docs/agentic/AGENTIC_README.md) | GitHub context, skills, clone/plan/patch/verify, human decisions | off |
| [Telegram](docs/channels/TELEGRAM_DESIGN.md) / [OpenTweet](docs/channels/OPENTWEET_DESIGN.md) | Phone remote and X drafts through loopback `/query` | off |
| [Numbat stream](docs/security-philosophy/numbat_secondary_evaluator.md) | Derived NDJSON, observation only | on |
| [Pre-action hook](docs/security-philosophy/numbat_pre_action_gate.md) | Deny-only gate before a confirmed external call | off |
| [Spend ledger](#spend-tracking) | Billed token counts | on |
| [Fine-tune kit](tools/lora_finetune/README.md) | Separate QLoRA toolkit | toolkit |

---

## Architecture

`gate.py` initializes the soul at startup. Requests pass the Host allowlist,
applicable authentication, a **60/min per-IP limit before injection filtering**,
and the config-driven filter before entering the graph as `GraphState`.
Graph edges control routing. [Operating contract](CLAUDE.md) and
[security invariants](INVARIANTS.md).

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
        G -->|"YES — local context"| X["guardrail_input\noffline rail · opt-in\npass-through when disabled"]
        X -->|"blocked"| L
        X -->|"passed · high score"| H["local_llm\nOllama :11434\nqwen3.8:27b-mlx"]
        G -->|"NO — vault miss"| I["user_gate\nneeds_confirm = true"]
        I -->|"confirmed + hybrid\n+ grok.enabled + provider=grok"| PG["pre_action_hook_grok\ndeny-only · off = pass-through"]
        PG -->|"allow"| J["grok_fallback\nxAI grok-4.5\ntriple-gated · skips guardrail_input"]
        I -->|"confirmed + hybrid\n+ claude.enabled + provider=claude"| PC["pre_action_hook_claude\ndeny-only · off = pass-through"]
        PC -->|"allow"| W["claude_fallback\nclaude-sonnet-5\ntriple-gated · skips guardrail_input"]
        I -->|"declined or offline"| X
        X -->|"passed · vault miss"| K["offline_best_effort\nlocal LLM · no RAG gate"]
        I -->|"confirmed=None — pause"| L
        H --> Y["guardrail_output\noffline rail · opt-in\ngrounding check: local_llm only"]
        J --> Y
        W --> Y
        K --> Y
        Y --> L
        PG -.->|"deny"| L
        PC -.->|"deny"| L
        L(["audit_logger\nSHA-256 hash · PII redact\nlogs/audit.jsonl\n+ derived Numbat stream"])
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

The MCP server calls the retriever directly after sanitization. It never
enters this HTTP gateway or this graph.

`HybridRetriever` uses CPU `all-MiniLM-L6-v2` embeddings (384-dimensional
cosine), Porter-stemmed BM25Okapi, and equal-weight RRF (`k=60`), retaining
chunk provenance. Finite BM25 scores use numpy `argpartition` for top-k;
`heapq.nlargest` handles the fallback. Gateway, MCP, and indexer suppress
telemetry before SDK imports. The diagram omits per-model NeMo checks and
the post-graph CEL monitor; [Optional layers](#optional-layers) describes
their failure and observation semantics.

---

## Installation

Platform steps, Docker, conda (`environment.yml`), and first index:
[`setup-guide.md`](setup-guide.md). macOS installs plain `torch==2.13.0`;
Windows and Linux use the `+cpu` wheel. Scripts:
[`macos/README.md`](macos/README.md),
[`powershell/README.md`](powershell/README.md). Image:
[`docs/DOCKER.md`](docs/DOCKER.md).

---

## API Key Setup (Soul Mutations)

`/soul/*`, `/ops/*`, `/memory/*`, `/query/export/html`, and `/audit/summary`
require operator access. `/health` is public; `/query` requires a session
or device token when `auth.enabled` is true. Operator credentials are:

- **Bearer `CYCLAW_API_KEY`**, for HTTP clients and scripts. Comparison is
  `hmac.compare_digest`.
- **The console cookie.** In the browser, "Unlock operator tools" trades the
  key once for an HttpOnly, `SameSite=Strict` cookie and forgets the key.
  The cookie lasts `security.console_session_ttl_sec` (12 h shipped);
  "Lock" deletes it, and rotating the key revokes every cookie at once.
- **An admin login**, when `auth.enabled` is on. No key is needed in the
  browser at all. `operator` and `audit` accounts do not get operator
  access.

Writes authorized by console or admin login cookies require CSRF tokens;
both cookie credentials reject cross-site requests. Without `CYCLAW_API_KEY`, Bearer and console-cookie access fail
closed. An enabled admin login still works, as does the explicit loopback
bypass described below.

`macos/invoke-cyclaw.sh` and `powershell\Invoke-CyClaw.ps1` generate a
missing key into the OS keystore and open a single-use `#pair=...` unlock
link. Its `security.console_pairing_ttl_sec` defaults to 5 minutes. For
manual browser access, copy the key into the unlock dialog:

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
Rotation and the macOS bootstrap:
[`macos/README.md`](macos/README.md#key-bootstrap)
([401 recovery](macos/README.md#401--key-drift-recovery)).

`security.api_key_optional` ships `false`. When set, a request skips the key
only if the flag is on, the socket peer is loopback, no forwarding header
is present, and the request is not cross-site. Remote callers need another
accepted operator credential. Docker NAT makes the peer the bridge gateway,
so the bypass is inert there. [`INVARIANTS.md`](INVARIANTS.md) Rule 6 and
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) (eighteenth amendment) hold
the full boundary.

## Per-User Authentication

Separate from the operator API key. `gate_auth.py`: scrypt passwords, a
session cookie plus CSRF for browsers, named device tokens for scripts,
roles `admin`, `operator`, and `audit`. Ships `auth.enabled: false`. While
off, every `/auth/*` route returns 503. Design, TLS, and the non-loopback
bind rule: [`docs/AUTHENTICATION_DESIGN.md`](docs/AUTHENTICATION_DESIGN.md).
First-boot `curl` and `cyclaw-user`:
[`setup-guide.md`](setup-guide.md#authentication-routes-auth-off-by-default).
`cyclaw-gen-cert` writes a self-signed cert for the auth + TLS bind exception.

---

## Spend Tracking

Billed Grok/Claude calls append tokens to `logs/spend.jsonl`. Dollars are
computed at read time, so rate-card corrections re-price history. Rows
exclude queries, prompts, and keys. Write failures warn and drop the row
without failing the answer.

| `source` | Writer | Covers |
|---|---|---|
| `query` | `llm/client.py` | Confirmed `/query` fallback |
| `agentic` | `agentic/deepagent_github/chat_client.py` | Out-of-band planner calls |
| `eval` | `tests/judge_eval.py` | Opt-in judge runs, kept separately under `logs/evals/` |

`python -m metrics` reports `today` and `last_7d` tokens, USD, provider/source
counts, `usage_missing`, and `rate_unknown`. Vendor costs appear beside
table prices as `table_usd`, `vendor_usd`, and `delta_usd`. Pricing includes
Grok's long-context band and Claude's cache-write split; `PRICED_AS_OF`
becomes stale after 30 days.

The forensic Sequences section joins query rows to audit hashes. It detects
a blocked injection followed within 15 minutes by a paid call on another
hash on this host, skipping repeated same-hash escalation runs. Core
request modules do not import it; it enforces no query policy.

`CYCLAW_SPEND_LIVE=1 python tests/spend_live_probe.py` **spends real money**,
checks forbidden fields in a temporary ledger, then deletes it. Pytest does
not collect it. [Ledger schema, rate bands, and probes](spend/README.md).

---

## Benchmarks and Evals

Only the retrieval gate blocks merges. These four evaluation paths are
neither graph nodes nor security controls. [Thresholds and limits](docs/EVALS.md).

| Evaluation | Command | Scope |
|---|---|---|
| Retrieval gate | `python -m tests.ci_rag_smoke` | Every PR, no LLM. Corpus probes through `route_by_score_node`, then hit@5, Recall@5, and MRR on 8 documents and 52 fixture cases. Metric floors and `[FILTERED]` injection-chunk assertions block CI |
| Local dogfood | `CYCLAW_EVAL_DOGFOOD=1 python scripts/cyclaw-eval-dogfood.py` | Opt-in real loopback model, one case per category. [Recipe](tests/fixtures/groundedness/DOGFOOD.md) |
| Anthropic judge | `CYCLAW_EVAL_LIVE=1 python tests/judge_eval.py` | Paid opt-in Claude grades groundedness, completeness, and abstention |
| Local judge | Same command with `evals.local_judge.enabled: true` | Same rubric on a second loopback model from a different family |

Published fixture retrieval reached 1.0 for hit@5, Recall@5, and MRR;
this does not establish arbitrary-corpus accuracy. The
[reranker bake-off](docs/audits/2026-09-26-reranker-bakeoff.md) found no
passing model/threshold combination, so vetoing stays disabled. No
judge-plane result has been published.

The [Qwen dogfood audit](docs/audits/2026-09-12_Local_Qwen_Dogfood_Matrix.md)
is one opt-in run on an M5 Pro with 48 GB: five generated rows using
`qwen3.8:27b-mlx` and a sanitizer probe with no model call. An unavailable
Ollama produces `unverified`. Dogfood is not a GitHub Actions job.

---

## Current development

Documentation follows [`origin/main` at `ba74653`](https://github.com/cgfixit/CyClaw/commit/ba7465354754a554cb7bd6b3fa711709dbf47fce).
As of 2026-10-03, these changes have **merged and shipped** (#1521, #1522, #1523, #1524):

| PR (merged) | Change |
|---|---|
| [#1521](https://github.com/cgfixit/CyClaw/pull/1521) | Give both sandbox emulators the terminal's query timeout allowance instead of 10 seconds |
| [#1522](https://github.com/cgfixit/CyClaw/pull/1522) | Preserve existing indexes when an empty or whitespace-only corpus produces no chunks |
| [#1523](https://github.com/cgfixit/CyClaw/pull/1523) | Enforce `memory.facts.max_active` when reactivating inactive facts |
| [#1524](https://github.com/cgfixit/CyClaw/pull/1524) | Remove a fresh clone if the initial agentic run record cannot be saved |

---

## Optional layers

Master switches default off except the local Numbat stream and spend ledger.

**Dropbox sync.** `rclone` pulls into `data/corpus/` outside the request
path. `max_delete`, `max_transfer`, and a single-instance lock bound each
run. An optional reindex follows corpus changes; exit code 10 signals
reindexing. Run `python -m sync.cli setup`, then `test`, `sync --dry-run`,
`sync`, `status`, or `schedule`. The console uses audited, operator-gated
`POST /ops/sync`. Schedulers cover cron, Windows tasks, and opt-in launchd;
the Darwin generator prints `launchctl bootstrap` without loading it.
[Sync guide](docs/%21%20How-To-Guides/Dropbox_Sync_Guide.md) and
[CLI reference](docs/SYNC_README.md).

**Native scheduling.** Generators resolve install paths, write plist/task
files, and print load commands. Token-bearing jobs use the keystore
wrappers described above. `macos/cyclaw-keychain-set.sh` prompts without
echo and pins trust with `-T /usr/bin/security`. Jobs cover Dropbox,
Telegram polling/health, fsconnect trash cleanup, and OpenTweet.

`macos/generate_service_plist.py` and `windows/generate_service_task.py`
require `--confirm` and non-empty `--reason` for a supervised gateway that
survives reboot. `macos/uninstall-cyclaw.sh` removes registered jobs and
landed agents by label. [macOS operations](macos/README.md) and
[launchd design](docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md).

**Fine-tuning.** The separate QLoRA kit assembles curated examples with
`source_refs` to repository files. It is excluded from runtime install profiles and the
repository OSV walk. CUDA installation is blocked by Unsloth's incompatible
Hugging Face ranges; retain the patched pins and audit this environment
separately. `finetune_qwen38.py` can download its base checkpoint because it
does not set `local_files_only`; seed caches before using a no-egress host.
For a GPU-free dry run, use
`python tools/lora_finetune/build_cyclaw_corpus.py`, then
`python tools/lora_finetune/dryrun_finetune.py`.
[Toolkit](tools/lora_finetune/README.md).

**Agentic coding.** `agentic.enabled: false` makes the out-of-band CLI
no-op. Although `mode: write` and `writes_enabled: true` are configured,
writes still require the master switch, a per-call `reason`, and `confirm`.
`deepagent_github.enabled` and `allow_git_write_tools` also ship false.
`gh` uses argv lists without shell evaluation or stored/forwarded tokens.
The skills registry at `data/agentic/skills_registry.json` ships empty.

`python -m agentic.cli real-repo-run` clones into a jail, plans, patches,
verifies, then requires a human decision before committing. Push and draft
PR creation are separate decisions. Caller-declared checks use Linux
`unshare --net`, macOS `sandbox-exec`, or Windows Job Objects. Missing
sandbox tools fail closed. Windows kills the process tree but does not
block sockets; no platform uses a microVM. [Threat model](docs/THREAT_MODEL.md).

The console's `POST /ops/agentic` accepts `status`, `test`, `context`,
`propose-skill`, and `apply-skill`; `real-repo-run*` receives 422.
Optional offline prose checks use `agentic/unslop_bridge.py`, with
`unslop.enabled: false` by default.

```bash
python -m agentic.cli status
python -m agentic.cli context --repo          # also --pr 123 / --issue 45
python -m agentic.cli propose-skill --name deploy --desc "..." --body-file s.md --reason "draft"
```

[Real-repo loop](agentic/README.md#2-real-repo-coding-loop),
[governed harness](docs/agentic/AGENTIC_README.md#9-governed-github-coding-harness),
and [write rollback](docs/agentic/GITHUB_WRITE_ENABLEMENT.md).

**Connectors.** All three ship off and stay outside the request path.
`fsconnect` bounds reads; writes need another gate and are always refused
on Windows. `sqlconnect` permits SELECT/WITH only. `netconnect` reads host
and neighbor-cache data for explicit RFC1918/loopback CIDRs without probes.
The browser calls subprocess shims at `/ops/fsconnect` and `/ops/sqlconnect`.
[Filesystem](agentic/README.md#5-filesystem-connector),
[SQL](agentic/README.md#6-sql-connector-read-only), and
[passive network](agentic/README.md#7-passive-network-connector).

**NeMo Guardrails.** Only literal `guardrails.enabled: true` activates the
layer; boot rejects non-booleans. `utils/guardrail_bridge.py` supplies three
callables or `None`, preserving core import isolation and graph routing.

| Guard | Scope and refusal |
|---|---|
| Offline input | Local and best-effort paths only. Returns `block_message` through `audit_logger` without a model call |
| Offline output | `local_llm` only. Replaces answers below `hallucination_threshold` (0.18) or leaking soul text |
| NeMo `check()` | All four answer nodes with `pip install -e ".[guardrails]" -c constraints.txt` (`nemoguardrails==0.24.0`). Input refusal skips generation; output refusal replaces the answer |

Rails run Python checks, not LLM calls; CI enforces that. Engine, package,
or rail failures leave the answer intact and audit `guardrail_degraded`.
With the layer enabled but the extra absent, every answered query is
degraded. Blocked events also write hashes to unrotated
`logs/guardrails.jsonl`. Inspect `python -m guardrails.cli status`.
[Guardrails](guardrails/README.md) and [NeMo reference](docs/NeMo/README.md).

**Numbat.** CyClaw calls the external CLI pinned at 0.2.0, schema 0.3.0;
it never vendors or imports it.

| Piece | Switch | Default and behavior |
|---|---|---|
| Stream | `numbat.enabled` | On. `utils/numbat_emitter.py` writes redacted audit/out-of-band events to `logs/numbat-events.ndjsonl`, rolling at 50 MiB to one `.1`. Its bounded writer cannot hold requests |
| Pre-action hook | `policy.fallback.pre_action_hook.enabled` | Off. Deny-only after external consent. `engine: command` uses exit 0 for allow, 2 for deny; `engine: numbat` runs `rules test --no-builtin-rules`. Missing explicit allow, including failure, denies |
| CEL monitor | `numbat.cel.enabled`, extra `numbat-cel` | Off. Requires the stream. Records matches after HTTP `/query`; never blocks |
| Offline scoring | None | Operator CLI and `numbat-rules.yml`. Fixture checks are advisory; stream-contract checks block CI |

Nothing scores the live file during a request. Avoid `numbat hook` as the
command engine: it drops provider/URL and exits 0 on errors. No gate rules
ship; examples are in `tests/fixtures/numbat/gate-rules/`. Events include
hostname, user, and uid (`N/A` on Windows). Audit and metrics preserve
`hook_allowed`, `hook_denied`, `hook_timeout`, `hook_error`, `hook_failure`,
and `hook_misconfigured` reason codes.

`/health` reports readiness. Operator-gated `/audit/summary` exposes
`pre_action_hook_last_verdict`: this process's latest codes, provider,
engine, and timestamp, or `null` before its first verdict. Public health
contains no decision history.
[Pre-action gate](docs/security-philosophy/numbat_pre_action_gate.md),
[stream](docs/security-philosophy/numbat_secondary_evaluator.md), and
[phase status](docs/plans/NUMBAT_AND_ALWAYS_ON_ROADMAP.md).

**Telegram and OpenTweet.** Disabled by default, both call loopback
`POST /query` outside the core graph imports. Credentials come from the
environment variable named in config, never YAML.

Telegram supports outbound `notify` or long-poll `chat`, without public
webhooks. Enabling it requires non-empty `allowed_chat_ids`. Only the exact
`/online on <grok|claude>` command can confirm a paid call, with
`allow_hybrid_confirm` enabled (default off), for one message and at most
300 seconds. The triple gate still applies. Optional media staging uses
`/save --confirm <reason>` through fsconnect writes. Inspect
`python -m telegram.cli status`.

OpenTweet generation forces `user_confirmed_online: false`. Writes default
to drafts; `scheduled_date` requires `opentweet.schedule_enabled`.
Schedulers never send `publish_now`. Inspect `python -m opentweet.cli status`.
[Telegram design](docs/channels/TELEGRAM_DESIGN.md),
[Telegram operations](telegram/README.md),
[OpenTweet design](docs/channels/OPENTWEET_DESIGN.md), and
[OpenTweet operations](opentweet/README.md).

`policy.fallback.enabled` is unused; the triple gate controls external
calls. Boot rejects `require_user_confirm: false`. Telemetry suppression
runs before heavy imports, plus ONNX's post-import call. It is not a
network firewall. [Security policy](SECURITY.md) and
[kill reference](docs/security-philosophy/cyclaw_telemetry_kill.env).

---

## Security Model

| Layer | Mechanism |
|---|---|
| Network | Binds `127.0.0.1:8787`. A non-loopback `api.host` is refused except the documented auth + TLS path, or `CYCLAW_ALLOW_NON_LOOPBACK_BIND` ([bind guard](docs/AUTHENTICATION_DESIGN.md#7-interaction-with-the-main-bind-guard-825)) |
| Endpoint trust | Local nodes: loopback or an exact host in `models.local_llm.trusted_hosts` (ships `[]`). Online nodes: `api.x.ai` and `api.anthropic.com` only |
| Input | `policy.prompt_filter`: 40 `banned_patterns`, `max_input_chars` from config. Same filter on MCP search |
| Rate limit | 60 req/min per IP, before the filter. In-memory unless you set SQLite or Postgres |
| Proxy bypass | `httpx` clients set `trust_env=False` |
| Telemetry | Kill maps before any SDK import (invariant-guard G1), plus ONNX's post-import call. Not a network kill switch. [`SECURITY.md`](SECURITY.md) |
| Audit | SHA-256 query hash + redacted metadata in `logs/audit.jsonl`, then the derived Numbat stream. `include_query_hash: false` stores redacted query text |
| Grok / Claude | [Triple gate](#what-it-does) item 5, then the opt-in pre-action hook (deny-only once enabled) |
| Soul writes | Human `reason` + enforced scan + atomic replace, on `POST /soul/apply` only. Restore, reload, and drift recovery are the exceptions in [What It Does](#what-it-does) item 4 |
| API key | Fail closed. Bearer key, the browser's console cookie, or (with `auth.enabled`) an admin login; cookie writes need CSRF. The loopback bypass is `security.api_key_optional` plus three more conditions ([API Key Setup](#api-key-setup-soul-mutations)) |
| Agentic writes | `agentic.enabled` ships `false`. Git writes also need `allow_git_write_tools`, which ships `false`. `real-repo-run*` is CLI-only |
| Connectors | fsconnect scoped; sqlconnect SELECT/WITH-only; netconnect passive. All off |
| Guardrails | Opt-in, deny-only, fail open with `guardrail_degraded` audited. Not a router |
| Channels | Off by default. Loopback `POST /query` only. OpenTweet cannot confirm a paid call |
| launchd / tasks | No tokens in the plist or task XML. Supervised-service generators require `--confirm` and `--reason` |
| `/ops/*` | Operator access, rate limit, audit. Subprocess argv lists preserve core import isolation |
| `/auth/*` | Present either way; 503 while auth is off. When on, `/query` needs a session or device token. Last `admin` cannot be removed |
| `/memory/*` | Off unless enabled. Mutations need operator access and a non-empty `reason` |
| Container | Non-root, `no-new-privileges`, dropped caps, read-only rootfs. Optional Falco (`deploy/falco/`) ships off |
| Dependency risk | `chromadb==1.5.9` carries CVE-2026-45829, accepted only for embedded `PersistentClient`. [`SECURITY.md`](SECURITY.md) |

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
├── retrieval/              # indexer, hybrid search, embeddings, rerank,
│                           # vector_store (Chroma or pgvector), clear_cache
├── llm/client.py           # local, Grok, Claude
├── memory/                 # optional facts + episodes (default off)
├── agentic/                # GitHub context, real-repo loop, executor,
│                           # fsconnect / sqlconnect / netconnect
├── guardrails/             # opt-in rails, reached only via guardrail_bridge
├── telegram/  opentweet/   # optional channels, shipped off
├── sync/                   # optional Dropbox pull
├── utils/                  # sanitizer, logger, personality, spend,
│                           # sequence_detect, numbat_*, endpoint_trust,
│                           # authn*, console_session, telemetry_kill, onnx_telemetry
├── macos/  powershell/  windows/   # native installers and schedulers
├── spend/                  # ledger reference
├── schemas/  static/  tests/  docs/  deploy/
├── tools/lora_finetune/    # operator QLoRA kit, not a runtime extra
└── .github/workflows/
```

`data/corpus/` is the shipped sample corpus. `data/personality/soul.md` is
the live soul. `data/agentic/skills_registry.json` ships empty.

---

## Documentation Map

| Read this | When you want |
|---|---|
| [`setup-guide.md`](setup-guide.md) | Install paths, Docker, conda, and every REST call |
| [`INVARIANTS.md`](INVARIANTS.md) | I1–I6, what is code vs convention, and the test that pins each |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | Request-path map and the rules agents work under |
| [`SECURITY.md`](SECURITY.md) | Egress, accepted CVEs, disclosure |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Scope, bind exceptions, amendments (including the removed harness) |
| [`docs/AUTHENTICATION_DESIGN.md`](docs/AUTHENTICATION_DESIGN.md) | Per-user auth |
| [`docs/DOCKER.md`](docs/DOCKER.md) | GHCR image and compose hardening |
| [`docs/EVALS.md`](docs/EVALS.md) | The four eval planes and their floors |
| [`spend/README.md`](spend/README.md) | Ledger schema and live probes |
| [`docs/memory/README.md`](docs/memory/README.md) | Facts, episodes, propose/apply, and the inert consolidation stub |
| [`retrieval/README.md`](retrieval/README.md) | Hybrid search, the cosine gate, and the shadow reranker |
| [`docs/security-philosophy/`](docs/security-philosophy/) | Why telemetry is killed, why offline is the default, Numbat designs |
| [`guardrails/README.md`](guardrails/README.md) / [`docs/NeMo/README.md`](docs/NeMo/README.md) | Rail semantics and what is display-only |
| [`docs/agentic/AGENTIC_README.md`](docs/agentic/AGENTIC_README.md) | Real-repo loop, exit codes, and the write gate |
| [`macos/README.md`](macos/README.md) / [`powershell/README.md`](powershell/README.md) | Keychain, Credential Manager, 401 recovery |

Memory, when you turn it on, is not the soul. Facts are proposed and
applied with a human `reason` and an injection scan; retrieval fusion is
a later switch (`facts.retrieval_enabled` plus `retrieval_fusion.enabled`).
`GET /query/export/html` stays 404 until `memory.export_html.enabled`.
Consolidation does not run in this version: `memory/consolidation.py`
returns `disabled` and ignores the flag. [`memory/README.md`](memory/README.md).

---

## License

Source-available, all rights reserved; personal use is permitted. See
[`LICENSE`](LICENSE).

*Designed and built by Chris Grady, with AI tooling used under human review,
CI, and the invariant guard.*
