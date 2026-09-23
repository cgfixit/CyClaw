# CyClaw — local AI you can trust, and track $pend

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141.1-blue.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.11-blue.svg)](https://github.com/langchain-ai/langgraph)
[![CyClaw CI/CD testing](https://github.com/cgfixit/CyClaw/actions/workflows/ci.yml/badge.svg)](https://github.com/cgfixit/CyClaw/actions/workflows/ci.yml)

[![Screenshots: local AI](https://github.com/cgfixit/CyClaw/blob/main/docs/screenshots/grok-a5efec11-9333-4583-8f97-5fa78803f703.jpg)](https://github.com/CGFixIT/CyClaw/tree/main/docs/screenshots)

CyClaw is a local RAG / chatbot / research server for **your own documents, on
your own hardware**: hybrid retrieval over a local Markdown corpus, a local
model answering from it, and safety rules written into the graph that routes
each request — not into a prompt asking a model to behave. It binds to
`127.0.0.1:8787`, answers locally by default, and treats any paid-provider call
as an exception you confirm per question and can account for afterwards, token
by token.

**What that means in practice**

- **Your data stays put.** Once the embedding model is cached, nothing leaves
  the machine unless you say so on that question.
- **Policy is topology.** Retrieval is the graph's unconditional entry node,
  every path converges on the audit logger, and the online-provider gate is a
  graph edge — checkable in code, not a prompt someone can forget.
- **Paid calls are opt-in and ledgered.** Three independent conditions must
  hold before Grok or Claude is called; every billed call appends token counts
  to a local ledger, with dollars derived at read time so a rate-card fix
  re-prices history instead of baking in errors.
- **Everything else ships off.** Per-user auth, memory, guardrails, local-data
  connectors, the agentic coding loop, and the Telegram/X channels sit behind
  master switches that ship disabled.

**Scope.** CyClaw is a trusted-operator, loopback-bound, single-tenant server —
one operator by default, or a small mutually-trusted group once `auth.enabled`
is on. Not multi-tenant. The full threat model, including what the sandbox
does *not* cover (no microVM by design), is
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Table of Contents

**Getting started**

- [Quick Start](#quick-start)
- [What It Does](#what-it-does)
- [Architecture](#architecture)
- [Installation](#installation)
- [Full Setup Guide](setup-guide.md) — every platform, Docker, every REST endpoint with `curl`

**Configuration and access**

- [API Key Setup (Soul Mutations)](#api-key-setup-soul-mutations)
- [Per-User Authentication](#per-user-authentication)

**Operating it**

- [Spend Tracking](#spend-tracking)
- [Benchmarks and Evals](#benchmarks-and-evals)
- [Dropbox Corpus Sync](#dropbox-corpus-sync)
- [macOS launchd & Keychain](#macos-launchd--keychain)
- [Local Model Fine-Tuning](#local-model-fine-tuning)

**Optional layers** (master switches ship disabled; each section names its enablement gates)

- [Optional layers at a glance](#optional-layers)
- [Agentic Layer](#agentic-layer)
- [Agentic Coding Loop (GitHub)](#agentic-coding-loop-github)
- [Filesystem, SQL & Passive Network Connectors](#filesystem-sql--passive-network-connectors)
- [NeMo Guardrails](#nemo-guardrails)
- [Telegram Channel](#telegram-channel)
- [OpenTweet Channel](#opentweet-channel)

**Reference**

- [Security Model](#security-model)
- [Project Structure](#project-structure)
- [Documentation Map](#documentation-map)
- [License](#license)

---

## Quick Start

**macOS (Apple Silicon)** — the onboarding script handles installation, keys,
Ollama, indexing, and startup:

```bash
git clone https://github.com/CGFixIT/CyClaw && cd CyClaw
bash macos/setup-cyclaw.sh
```

**Linux** — manual path (Ollama must already be running on `:11434`):

```bash
git clone https://github.com/CGFixIT/CyClaw && cd CyClaw
python3.12 -m venv .venv && source .venv/bin/activate
pip install torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r requirements-test.txt -c constraints.txt --ignore-installed PyYAML
ollama pull qwen3.8:27b-mlx
export CYCLAW_API_KEY="$(openssl rand -hex 20)"  # needed for the /soul/* and /ops/* endpoints
python -m retrieval.indexer                      # builds the retrieval index, once
python gate.py                                   # → http://127.0.0.1:8787
```

**Windows** uses the same dependency pins with PowerShell activation
(`py -3.12 -m venv .venv`, `.\.venv\Scripts\Activate.ps1`); see
[Windows](setup-guide.md#windows-powershell) and
[Linux](setup-guide.md#linux-bash) in the setup guide.

Confirm it's alive: `curl http://127.0.0.1:8787/health`, then open
`http://127.0.0.1:8787/` for the browser console.

> **Manual macOS install differs in one step.** The `+cpu` torch wheel does not
> exist for macOS, so torch installs plain (`torch==2.13.0`) from stripped
> copies of `requirements.txt` and `constraints.txt`. Exact commands:
> [macOS (Apple Silicon)](setup-guide.md#macos-apple-silicon).

---

## What It Does

CyClaw answers questions from your documents using a local model reading a
local index. What makes the "nothing leaves the machine" claim checkable is
*where* the safety lives: the shape of the graph, not a prompt, system
message, or config flag someone could forget to set.

> **First run is the one exception.** If the embedding model isn't already in
> the Hugging Face cache, `retrieval/embeddings.py` fetches it once — a
> documented bootstrap, not something `user_confirmed_online` gates. Once
> cached, a disk-only probe confirms it and every later load passes
> `local_files_only=True`, so a warm cache never reaches out again.

### The core — always present, no switches involved

1. **Retrieval comes first, unconditionally.** `retrieve` is the entry node of
   the 12-node LangGraph state machine in `graph.py`; no model call can
   precede it. Edges enforce retrieval and provider selection, not groundedness
   — `offline_best_effort` can answer from partial context after a vault miss.
2. **Hybrid search over your Markdown corpus.** ChromaDB semantic vectors plus
   BM25 keyword ranking, fused by RRF (`retrieval.rrf_k`), both local and
   CPU-only. A query whose best semantic match is below
   `retrieval.min_semantic_score` (or, with no semantic scores, whose top fused
   hit is below `retrieval.min_score`) routes to a user gate instead of a
   confident guess.
3. **A local model by default.** Ollama serving `models.local_llm.model`
   (shipped: `qwen3.8:27b-mlx`). Context budget, generation cap, and every
   timeout are `config.yaml` values — nothing tunable is hardcoded.
4. **A governed personality layer.** `data/personality/soul.md`, SHA-256 drift
   detection, atomic writes. `POST /soul/apply` requires a human `reason` and
   an enforced injection scan; `POST /soul/restore` re-adopts vetted `.bak`
   content under only an advisory scan; a missing file self-heals at boot.
   Governed — neither frozen nor self-editable.
5. **Online fallback, triple-gated per question.** A paid Grok (xAI) or Claude
   (Anthropic) call fires only when **all three** hold: `app.mode: hybrid`
   **and** the provider's own `enabled` flag **and** a per-request
   `user_confirmed_online: true` — never persisted, never carried forward. The
   provider is chosen per query via `online_provider`. Both ship
   `enabled: true`, so the per-question confirmation is the gate actually
   holding the line — not a server-enforced challenge (a client can send
   `true` on its first call), but *something* still has to assert it every
   time. Outbound calls are also capped by the remaining
   `api.graph_timeout_sec` budget. "Triple-gated" below always means this gate.
6. **Two front doors.** A FastAPI gateway at `127.0.0.1:8787` (browser console
   at `/`) and a retrieval-only MCP server (`mcp_hybrid_server.py`,
   `sampling: None`) — search only, no model path.
7. **An audit trail that hashes the question.** All eleven upstream paths
   converge on `audit_logger` before END, writing a SHA-256 query hash plus
   PII-redacted metadata to `logs/audit.jsonl`; `cyclaw-metrics` reads it
   offline. `logging.audit_fields.include_query_hash: false` stores raw query
   text instead (privacy-affecting, per `utils/logger.py`'s own docstring).

### Where the invariants are enforced

Enforced in four places: **graph topology** (entry, routing, audit
convergence), **`gate.py` construction** (two of the three external-provider
gates — only per-request confirmation is decided in the graph),
**`utils/personality.py`** (the soul reason gate and atomic write), and
**import structure** (module isolation, invariant **I6**).
`python3 .claude/skills/invariant-guard/check_invariants.py` asserts all six
invariants plus five guards statically; [`INVARIANTS.md`](INVARIANTS.md)
records which are code-enforced vs. conventional, and the test pinning each.

### Optional layers

Three kinds: **route modules** on the gateway (per-user auth, memory),
**in-path utilities** inside the core request path (the Numbat stream and
spend ledger — both in `utils/` rather than out-of-band, and both ship **on**
since neither needs a config edit, adds egress, or does more than write a
local file), and **I6-isolated subsystems** — everything else, never imported
by `gate.py`/`graph.py`/the MCP server, a boundary asserted statically.

| Layer | What it adds | Ships |
|---|---|---|
| [Per-user authentication](#per-user-authentication) (`gate_auth.py`, `utils/authn*`) | scrypt password hashes, session cookie + CSRF, bearer device tokens, three roles (`admin`/`operator`/`audit`), `cyclaw-user` CLI. With `auth.enabled: true`, `/query` requires a session or token | off |
| Facts + episodes memory (`gate_memory.py`, [`memory/`](memory/README.md)) | SQLite + FTS5 store with propose/apply governance (human `reason` + injection scan) and an optional retrieval-fusion hook | off |
| [NeMo Guardrails](#nemo-guardrails) ([`guardrails/`](guardrails/README.md)) | content-safety input rail + output grounding check, degrading to offline heuristics without `nemoguardrails` — defense in depth, never a routing authority | off |
| [Dropbox corpus sync](#dropbox-corpus-sync) (`sync/`) | an `rclone` wrapper refreshing `data/corpus/` out-of-band, signaling "reindex" by exit code | CLI only |
| [Local-data connectors](#filesystem-sql--passive-network-connectors) (`agentic/fsconnect`, `sqlconnect`, `netconnect`) | scoped filesystem reads with gated writes, SELECT-only SQL, and passive LAN inventory | off |
| [Agentic layer](#agentic-layer) + [coding loop](#agentic-coding-loop-github) (`agentic/`) | read-only GitHub context via `gh`, a governed skills registry, and a real-repo clone → plan → patch → verify → **human decides** → commit pipeline (push/draft-PR are further decisions) | off |
| [Telegram](#telegram-channel) and [OpenTweet](#opentweet-channel) channels | a phone remote and a weekly X poster; both reach the pipeline only through loopback `POST /query` | off |
| Numbat forensic stream (`utils/numbat_emitter.py`) | a derived NDJSON projection of the audit trail (`logs/numbat-events.ndjsonl`) that the pinned Numbat 0.2.0 CLI can score ([design note](docs/security-philosophy/numbat_secondary_evaluator.md)) | **on** |
| [Spend ledger](#spend-tracking) (`utils/spend.py`) | token counts per billed call in `logs/spend.jsonl`, tagged `source: query`/`agentic`; dollars derived at read time | **on** |
| [Fine-tune kit](#local-model-fine-tuning) (`tools/lora_finetune/`) | offline QLoRA kit teaching a local model this codebase; installed by no runtime surface | toolkit |

---

## Architecture

`gate.py` (FastAPI on `127.0.0.1:8787`) runs the `TrustedHostMiddleware` Host
allowlist, then the per-IP rate limiter (**60 req/min — before the injection
filter**), then the config-driven injection filter, then soul init, and hands
a `GraphState` to the 12-node LangGraph state machine in `graph.py`. Routing
is graph edges only — `retrieve` is the unconditional entry, and every path
converges on `audit_logger` before END. The numbered plain-text version of
this flow is [`CLAUDE.md`](CLAUDE.md) §2 "The Map"; the invariants it encodes
are in [`INVARIANTS.md`](INVARIANTS.md).

### LangGraph Topology (rendered)

```mermaid
flowchart TD
    A(["🌐 Client\nHTTP POST /query"])
    A --> B

    subgraph GATEWAY ["gate.py — FastAPI 127.0.0.1:8787"]
        B["TrustedHostMiddleware\nHost header allowlist"]
        B --> C["Rate Limiter\n60 req/min per IP"]
        C --> D["Prompt Injection Filter\n40 patterns · config-driven · lru_cache"]
        D --> E["Build GraphState\nquery + user_confirmed_online"]
    end

    E --> F

    subgraph GRAPH ["graph.py — LangGraph 12-node State Machine"]
        F(["① retrieve\nChroma + BM25 + RRF"])
        F --> G["② route_by_score\ntop_score ≥ 0.028?"]
        G -->|"YES — local context"| X["③ guardrail_input\noffline rail · opt-in\npass-through when disabled"]
        X -->|"blocked"| L
        X -->|"passed · high score"| H["④ local_llm\nOllama :11434\nqwen3.8:27b-mlx"]
        G -->|"NO — vault miss"| I["⑤ user_gate\nneeds_confirm = true"]
        I -->|"confirmed=true + hybrid\n+ grok.enabled + provider=grok"| PG["⑥ pre_action_hook_grok\nsync · disabled=pass-through\nexit 2 → deny"]
        PG -->|"exit 0 → allow"| J["⑦ grok_fallback\nxAI grok-4.5\ntriple-gated · not railed"]
        I -->|"confirmed=true + hybrid\n+ claude.enabled + provider=claude"| PC["⑧ pre_action_hook_claude\nsync · disabled=pass-through\nexit 2 → deny"]
        PC -->|"exit 0 → allow"| W["⑨ claude_fallback\nAnthropic claude-sonnet-5\ntriple-gated · not railed"]
        I -->|"confirmed=false\nor offline mode"| X
        X -->|"passed · vault miss"| K["⑩ offline_best_effort\nlocal LLM · no RAG gate"]
        I -->|"confirmed=None — PAUSE\nreturn needs_confirm to the client"| L
        H --> Y["⑪ guardrail_output\noffline rail · opt-in\ngrounding check: local_llm only"]
        J --> Y
        W --> Y
        K --> Y
        Y --> L
        PG -.->|"deny"| L
        PC -.->|"deny"| L
        L(["⑫ audit_logger\nSHA-256 hash · PII redact\n→ logs/audit.jsonl"])
    end

    L --> M(["📤 QueryResponse\nanswer · sources · model_used\nretrieval_mode · needs_confirm"])

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
        R["SQLite / Postgres\nversion history · TTL prune"]
        Q <--> R
    end

    H <-->|"soul preamble\n≤ 8000 chars"| Q
    K <-->|"soul preamble"| Q

    subgraph OOB ["Out-of-band — never imported by gate/graph/MCP"]
        S["agentic/cli.py\nGitHub read ops"]
        T["agentic/fsconnect/\nscoped FS read/write"]
        U["sync/cli.py\nDropbox corpus pull"]
        V["guardrails/\noptional rails via guardrail_bridge"]
    end

    style GATEWAY fill:#1a3a5c,color:#ffffff,stroke:#4a90d9
    style GRAPH fill:#1a3a2a,color:#ffffff,stroke:#4a9d5a
    style RETRIEVAL fill:#3a2a1a,color:#ffffff,stroke:#d9904a
    style SOUL fill:#3a1a3a,color:#ffffff,stroke:#d94ad9
    style OOB fill:#2a2a2a,color:#aaaaaa,stroke:#666666,stroke-dasharray:5 5
    style J fill:#5c1a1a,color:#ffffff
    style W fill:#5c1a1a,color:#ffffff
    style L fill:#1a1a3a,color:#ffffff
```

The retrieval-only MCP server calls the retriever directly after sanitization;
it never enters this HTTP gateway or generation graph.

What the diagram compresses: `HybridRetriever` fuses ChromaDB (semantic,
`all-MiniLM-L6-v2`, 384-dim cosine, CPU-only embeddings) with BM25Okapi
(keyword, Porter stemming) by RRF (`k=60`, equal weighting), carrying
per-chunk provenance metadata in every result. The telemetry kill block runs
before any SDK import; the MCP server and indexer apply the same block.

---

## Installation

Install, first run, and starting the gateway are in
[`setup-guide.md`](setup-guide.md). macOS installs plain `torch==2.13.0`;
Windows and Linux use the `+cpu` wheel. Platform scripts:
[`macos/README.md`](macos/README.md) and
[`powershell/README.md`](powershell/README.md). The optional GHCR image is
[`docs/DOCKER.md`](docs/DOCKER.md).

---

## API Key Setup (Soul Mutations)

`/soul/*`, `/ops/*`, `/memory/*`, and `/audit/summary` require a Bearer
`CYCLAW_API_KEY` and fail closed (401) when unset. `/query` and `/health`
don't use it. What the key gates and the per-platform generate step are in
[`setup-guide.md`](setup-guide.md#cyclawapikey--required-for-the-soul-console-not-for-query).
macOS persist is the Keychain bootstrap:
[`macos/README.md`](macos/README.md#key-bootstrap)
([401 recovery](macos/README.md#401--key-drift-recovery)). Provider key names
and the ledger are in [`spend/README.md`](spend/README.md#api-keys); Windows
persist is next.

### Windows — PowerShell / cmd.exe

Generate the session value in
[`setup-guide.md`](setup-guide.md#windows-powershell), then persist it —
current user, open a new session before `python gate.py`:

```powershell
[System.Environment]::SetEnvironmentVariable("CYCLAW_API_KEY", $env:CYCLAW_API_KEY, "User")
```

cmd.exe: `set CYCLAW_API_KEY=<value>` for the session, `setx CYCLAW_API_KEY "<value>"`
to persist. A repo `.env` is sourced by `Invoke-CyClaw.ps1` only when every
Allow ACE is the current user (`icacls .env /inheritance:r /grant:r
"${env:USERNAME}:(R,W)"`). Scheduled-task secrets use Credential Manager
([`powershell/README.md`](powershell/README.md#scripts)).

## Per-User Authentication

The operator API key above gates soul and ops routes. Per-user auth is the
account system (`gate_auth.py`): scrypt passwords, a session cookie plus CSRF
for browsers, named device tokens for scripts, and roles `admin`, `operator`,
and `audit`. It ships with `auth.enabled: false` — while off, every `/auth/*`
route returns 503. The design, role table, TLS, and non-loopback bind rule are
in [`docs/AUTHENTICATION_DESIGN.md`](docs/AUTHENTICATION_DESIGN.md).
First-boot `curl` and `cyclaw-user` are in
[`setup-guide.md`](setup-guide.md#authentication-routes-auth-off-by-default).

---

## Spend Tracking

Every triple-gated Grok/Claude call that actually bills appends one line to
`logs/spend.jsonl` via `utils/spend.py`. **Tokens are the ground truth;
dollars are derived at read time** — the ledger never stores a price, so a
rate fix re-prices the entire history instead of leaving wrong numbers baked
in. It never stores query text, prompt content, or API keys, and writes are
best-effort: a full disk logs a warning and drops the row rather than turning
a successful paid answer into a failed request.

| `source` | Writer | What it covers |
|---|---|---|
| `query` | `llm/client.py` | The `/query` online fallback — a triple-gated escalation a human confirmed per request |
| `agentic` | `agentic/deepagent_github/chat_client.py` | The out-of-band cloud planner's one-shot plan calls |
| `eval` | `tests/judge_eval.py` / `judge_calibrate.py` | Opt-in Anthropic-judge evals; routed to `logs/evals/spend.jsonl`, never the production ledger |

**Reading it:** `python -m metrics` (or `cyclaw-metrics`). Prints `today`/
`last_7d` windows: tokens, a derived USD figure, per-provider/source row
counts, and two data-quality counters (`usage_missing`, `rate_unknown`). A
vendor-reported cost also shows `table_usd`/`vendor_usd`/`delta_usd` side by
side, so rate-table drift is visible rather than hidden.

**Pricing is exact, not approximated:** Grok's long-context band (above 200k
tokens, xAI bills the *entire* request at the long rate) and Claude's
cache-write split by TTL. `PRICED_AS_OF` flags stale after 30 days.
`compare_vendor_cost()` verifies against xAI's own ticks (Claude's check is
the Anthropic console total). `utils/sequence_detect.py` joins the ledger to
`logs/audit.jsonl` on `query_hash` to correlate a blocked injection with a
later online escalation.

**Live probes** (spend real money, opt-in, never collected by pytest):
`CYCLAW_SPEND_LIVE=1 python tests/spend_live_probe.py` writes to a **temp**
ledger, deletes it, and asserts no forbidden field reached the row.

Full schema and the live-probe walkthrough: [`spend/README.md`](spend/README.md).

---

## Benchmarks and Evals

Quality is measured on four separate planes, and only the first blocks a
merge. All score the synthetic fixture under `tests/fixtures/groundedness/`
(eight documents, 52 labeled cases in six categories including
`injected_content`, where the evidence itself carries instructions); none is a
graph node or a security control.

| Plane | Command | Runs | Measures |
|---|---|---|---|
| Retrieval gate | `python -m tests.ci_rag_smoke` | every PR (`ci.yml`), no LLM | four `data/corpus` queries against `retrieval.min_score`, then hit@5/Recall@5/MRR, plus a check each injected doc's chunk was sanitized to `[FILTERED]` |
| Local dogfood | `CYCLAW_EVAL_DOGFOOD=1 python scripts/cyclaw-eval-dogfood.py` | operator, opt-in | one case per category on the real loopback model, with latency and a sanitizer probe; rows are `generated`/`unverified`, never assumed |
| Anthropic judge | `CYCLAW_EVAL_LIVE=1 python tests/judge_eval.py` (+ key) | operator, opt-in, spends money | groundedness, completeness, abstention per case, graded by Claude |
| Local judge | same, with `evals.local_judge.enabled: true` | operator, opt-in, fully local | same rubric graded by a second loopback model of a different family |

**Measured so far.** The retrieval gate holds at hit@5 1.0 / Recall@5 1.0 /
MRR 1.0 on CI (20 scored cases, 2026-09-12) and locally after the fixture grew
to 52 (44 scored, 2026-09-16). The dogfood matrix produced five real
`generated` rows on `qwen3.8:27b-mlx` on an M5 Pro 48 GB
([dated record](docs/audits/2026-09-12_Local_Qwen_Dogfood_Matrix.md)).
**No judge-plane result has been published yet.** Planes, thresholds, and the
not-yet-measured list are in [`docs/EVALS.md`](docs/EVALS.md).

---

## Dropbox Corpus Sync

An **optional, out-of-band** `rclone`-backed pull sync mirrors a Dropbox
corpus into `data/corpus/` without touching `gate.py`, `graph.py`, or the MCP
path. It carries safety fuses (`max_delete`, `max_transfer`), an OS-backed
single-instance lock so a scheduled and a manual run can't race, audit logging
of changed corpus files, an optional reindex trigger, and scheduler glue for
cron / Windows Task Scheduler plus an opt-in Darwin-only launchd backend that
generates the plist and prints the bootstrap command — never loading it.

```bash
python -m sync.cli setup          # first-run bootstrap; then: test | sync --dry-run | sync | status | schedule | unschedule
```

The **Sync Console** panel drives the same actions via `POST /ops/sync`
(loopback-only, API-key gated, audited). Full setup and scheduling:
[`docs/! How-To-Guides/Dropbox_Sync_Guide.md`](docs/%21%20How-To-Guides/Dropbox_Sync_Guide.md);
module internals: [`docs/SYNC_README.md`](docs/SYNC_README.md).

---

## macOS launchd & Keychain

CyClaw's scheduled/supervised jobs on macOS run through generated launchd
LaunchAgents: every generator writes a plist from real resolved install paths
and prints the exact `launchctl bootstrap` command — **none of them ever
loads the agent itself**; loading a background job is always a separate,
explicit operator action.

- **Secrets never land in a plist.** Token-bearing jobs chain
  `macos/cyclaw-keychain-env.sh`, which fetches the secret from the Keychain at
  process start and `exec`s the real command — failing closed if the item is
  missing. Store secrets with `macos/cyclaw-keychain-set.sh`, a no-echo prompt
  so the secret never appears in argv; trust-pinned with `-T /usr/bin/security`.
- **Scheduled jobs** — Dropbox sync (above), Telegram poll/health, fsconnect
  trash emptying, and OpenTweet — each a generate-only `*-plist` subcommand.
- **Supervised services** (highest risk) — `macos/generate_service_plist.py`
  writes a KeepAlive LaunchAgent for `gate.py`, refusing to write without
  `--confirm` **and** a non-empty `--reason` since that turns a loopback server
  into an always-on listener that survives reboot. Windows counterpart:
  `windows/generate_service_task.py`.
- **Uninstall symmetry** — `macos/uninstall-cyclaw.sh` unschedules any
  registered sync job and removes landed LaunchAgents by label.

```bash
bash macos/cyclaw-keychain-set.sh com.cgfixit.cyclaw.telegram-bot-token   # store a secret (TTY prompt)
python -m telegram.cli poll-plist                                        # Darwin-only; generates, never loads
python macos/generate_service_plist.py --service gate \
    --reason "keep the RAG server up across reboots" --confirm
```

Script-by-script reference (including 401 / key-drift recovery):
[`macos/README.md`](macos/README.md). Design and phase ledger:
[`docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md`](docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md).

---

## Local Model Fine-Tuning

Retrieval tells the local model what this codebase *says*; a fine-tune teaches
it how this codebase *thinks*, so an operator model stops re-deriving the same
invariants every question. `tools/lora_finetune/` is a QLoRA kit for
`models.local_llm.model` built on a curated Q&A dataset generated from live
source, each example carrying `source_refs` back to its file.

**It is an operator toolkit outside the runtime install profiles.** Its CUDA
training install is currently blocked: Unsloth's dependency ranges conflict
with the kit's patched Hugging Face pins — do not bypass those; audit the
training environment separately (excluded from this repo's OSV walk).

**It is not air-gapped, though.** `finetune_qwen38.py` downloads the base
checkpoint from Hugging Face on first run with no `local_files_only`. Seed the
model/tokenizer caches first on a no-egress machine — "offline" here means
independent of the CyClaw server, not free of network.

```bash
python tools/lora_finetune/build_cyclaw_corpus.py   # rebuild the dataset from source
python tools/lora_finetune/dryrun_finetune.py       # full control flow, mocked, no GPU
```

Dataset shape, category counts, the confirmed training-install blocker, and
the `pip-audit`-on-the-GPU-box step are in
[`tools/lora_finetune/README.md`](tools/lora_finetune/README.md).

---

## Agentic Layer

A **concise, governed agentic layer** for local operator workflows. It is
**opt-in, disabled by default, and out-of-band (I6)** — never imported by
`gate.py`, `graph.py`, or `mcp_hybrid_server.py`. `data/agentic/skills_registry.json`
is a governed store that ships empty (`apply-skill` writes it). Package guide:
[`agentic/README.md`](agentic/README.md).

What it adds: read-only GitHub context via the `gh` CLI (argv list, never a
shell; no token stored or forwarded), a governed local skills registry with
explicit human gating, and the operator workflows under `.claude/`
([`.claude/README.md`](.claude/README.md)). All reads, refusals, and registry
changes are audit logged.

The GitHub write path (`gh pr create --draft`) is implemented and its
code-level gates (`EXECUTION_ENABLED`, `mode: "write"`, `writes_enabled`) ship
open since 2026-08-07. The layer master switch `agentic.enabled` still ships
`false`, so a default checkout can't open a PR — that, plus a per-call
`reason` and `confirm`, is what refuses. Rollback:
[`docs/agentic/GITHUB_WRITE_ENABLEMENT.md`](docs/agentic/GITHUB_WRITE_ENABLEMENT.md).

### Enable it

```yaml
agentic:
  enabled: true                  # the one edit this block asks you to make
  repo: "cgfixit/CyClaw"
  mode: "write"                  # ships open since 2026-08-07
  writes_enabled: true           # ships open since 2026-08-07
  gh_min_version: "2.40.0"
  registry_path: "data/agentic/skills_registry.json"
```

### Main agentic commands

```bash
python -m agentic.cli status
python -m agentic.cli context --repo             # also: --pr 123 / --issue 45
python -m agentic.cli test
python -m agentic.cli propose-skill --name deploy --desc "..." --body-file s.md --reason "draft"
python -m agentic.cli apply-skill --name deploy --desc "..." --body-file s.md --reason "add deploy runbook" --confirm
```

The **Agentic Console** panel drives these from the terminal UI via
`POST /ops/agentic`; skill-Apply is refused under shipped defaults by
`agentic.enabled: false`, and a per-call `reason` + `--confirm` remain
mandatory once it is on.

---

## Agentic Coding Loop (GitHub)

The real-repo pipeline clones a repo, plans, patches, verifies, and stops for
a human decision before it commits. Pushing the branch and opening a draft PR
are two further decisions. A default checkout holds the run: `agentic.enabled`,
`deepagent_github.enabled`, and `allow_git_write_tools` ship `false`.
Enablement and commands are in
[`agentic/README.md`](agentic/README.md#2-real-repo-coding-loop) and
[`docs/agentic/AGENTIC_README.md`](docs/agentic/AGENTIC_README.md#9-governed-github-coding-harness).
Draft-PR arming and the rollback are in
[`docs/agentic/GITHUB_WRITE_ENABLEMENT.md`](docs/agentic/GITHUB_WRITE_ENABLEMENT.md).

---

## Filesystem, SQL & Passive Network Connectors

Three connectors extend the agentic layer to local data. All three ship off
and stay outside the request path. `fsconnect` does scoped filesystem reads,
with writes on a separate gate. `sqlconnect` is SELECT-only. `netconnect` is a
passive inventory of local host data and the existing neighbor cache.
Enablement, security notes, and tool lists are in
[`agentic/README.md`](agentic/README.md):
[filesystem](agentic/README.md#5-filesystem-connector),
[SQL](agentic/README.md#6-sql-connector-read-only),
and [passive network](agentic/README.md#7-passive-network-connector).

---

## NeMo Guardrails

An **opt-in** content-safety layer in `guardrails/`
([package README](guardrails/README.md)). Absence of the `guardrails:` block,
or `enabled: false` (shipped default), is a pure no-op. When enabled,
`utils/guardrail_bridge.py` wires two `graph.py` nodes — `guardrail_input` and
`guardrail_output` (grounding check, **`local_llm` path only**) — still
**defense-in-depth only, never a routing authority**: the graph's own edges
decide where a blocked query goes. `gate.py`/`graph.py`/`mcp_hybrid_server.py`
never import `guardrails` directly (I6).

`nemoguardrails` is an **optional dependency**: absent, the layer degrades to
offline heuristic rails needing no second LLM call — an **input** rail
(injection marker scan + soul-mutation intent detection) and an **output**
rail (token-overlap **grounding** check, flagging likely-hallucinated answers
below `hallucination_threshold`). When installed, the same checks back the
live NeMo actions via `guardrails/config/rails.co`, so heuristics and live
rails never drift. Decisions go to a **separate** metrics stream
(`logs/guardrails.jsonl`) storing only SHA-256 hashes.

```bash
python -m guardrails.cli status
python -m guardrails.cli check "your query here"   # also: metrics | test
```

Config keys (`guardrails.enabled`, `engine`, `model`, `hallucination_threshold`,
`metrics_path`) and their shipped values live in `config.yaml`; the status
table, phased history, and rail semantics are in
[`docs/NeMo/README.md`](docs/NeMo/README.md).

---

## Telegram Channel

An **optional, out-of-band (I6)** channel (`telegram/`, shipped
`enabled: false`) giving the single trusted operator a phone-reachable remote
— outbound notifications and, when configured, allowlisted two-way chat.
Inbound chat text only ever reaches the RAG pipeline via loopback
`POST /query`, never a direct call into `graph.py`.

Outbound notify (`mode: "notify"`) or long-poll two-way chat (`mode: "chat"`,
still `enabled: false`; no public webhook listener). `allowed_chat_ids` is
required non-empty when enabled; the bot token comes only from the env var
named by `bot_token_env`, never YAML. T3 hybrid-confirm consent
(`allow_hybrid_confirm: false` by default): the exact command
`/online on <grok|claude>` is the only way chat text can set
`user_confirmed_online`, for one message only (hard-capped at 300s) — core's
triple gate remains final authority. T4 media staging (`media.enabled: false`)
accepts attachments captioned `/save --confirm <reason>` only through the
existing `agentic/fsconnect` write path.

```bash
python -m telegram.cli status
python -m telegram.cli test
python -m telegram.cli send --chat-id "<id>" --text "..."   # T1; add --dry-run to preview
python -m telegram.cli poll                                # T2; requires telegram.mode: chat
python -m telegram.cli poll-plist / health-plist           # Darwin-only; generates, never loads
```

See [`docs/channels/TELEGRAM_DESIGN.md`](docs/channels/TELEGRAM_DESIGN.md) for
architecture, the T0–T4 phase ledger, and threat-model obligations
(`docs/THREAT_MODEL.md`'s seventh amendment), and
[`telegram/README.md`](telegram/README.md) for package internals.

---

## OpenTweet Channel

Optional out-of-band (I6) X poster (`opentweet/`, shipped `enabled: false`).
Generation is loopback `POST /query` with `user_confirmed_online: false`, so
it can never trigger a paid call. The default write is an OpenTweet **draft**;
`scheduled_date` is opt-in via `opentweet.schedule_enabled`. Schedulers never
send `publish_now`.

```bash
python -m opentweet.cli status
python -m opentweet.cli post --topic "..."          # add --dry-run to preview
python -m opentweet.cli schedule-plist              # Darwin/Windows: schedule-task; generates, never loads
```

See [`docs/channels/OPENTWEET_DESIGN.md`](docs/channels/OPENTWEET_DESIGN.md)
and [`opentweet/README.md`](opentweet/README.md). Keychain/CredMan wrappers
are in [`macos/README.md`](macos/README.md) and
[`powershell/README.md`](powershell/README.md).

---

## Security Model

| Layer | Mechanism |
|---|---|
| Network | Binds `127.0.0.1:8787` — no external exposure by design; `_require_loopback_bind` refuses a non-loopback `api.host` outside the documented auth + TLS exception ([bind guard](docs/AUTHENTICATION_DESIGN.md#7-interaction-with-the-main-bind-guard-825)) |
| Endpoint trust | `utils/endpoint_trust.py` allowlists where a generation client may talk, checked in `graph.py`. Local nodes accept loopback or `models.local_llm.trusted_hosts` (ships `[]`); online nodes pin Grok to `api.x.ai` and Claude to `api.anthropic.com`, so a tampered `base_url` can't redirect a confirmed call |
| Input | Config-driven injection filter (`policy.prompt_filter`: 40 `banned_patterns`, `max_input_chars: 4000`) |
| Rate limit | 60 req/min per IP, sliding window; in-memory by default, optional SQLite/Postgres persistence |
| Proxy bypass | All `httpx` clients set `trust_env=False` — ambient `HTTP(S)_PROXY`/`.netrc` can't reroute local traffic or carry API keys |
| Telemetry | Canonical kill maps applied before any SDK import at every chokepoint (invariant-guard G1) and delivered as literal environment at every process boundary. ONNX gets a post-import suppression call; HF Hub calls stop once the embedding model is confirmed cached. Not a network kill switch — see [SECURITY.md](SECURITY.md) |
| Audit | All paths log SHA-256 query hash + PII-redacted metadata ([What It Does](#what-it-does), item 7) |
| Grok / Claude gating | The [triple gate](#the-core--always-present-no-switches-involved) (item 5), per provider: `mode=hybrid` AND `<provider>.enabled=true` AND `user_confirmed_online=true` |
| Soul writes | Explicit human reason string + enforced write-boundary scan + atomic write |
| Agentic writes | `pr_create` implemented; `agentic.enabled` (ships `false`) plus per-call reason/confirm is what refuses — see [Agentic Layer](#agentic-layer). Git-level writes additionally need `deepagent_github.allow_git_write_tools`, ships `false` |
| Local-data connectors | fsconnect reads scoped/capped with atomic gated writes; sqlconnect is SELECT/WITH-only; netconnect is passive-only — all disabled by default, see [Connectors](#filesystem-sql--passive-network-connectors) |
| Guardrails | Out-of-band, opt-in defense-in-depth; degrades to offline heuristics without `nemoguardrails`; never a routing authority — see [NeMo Guardrails](#nemo-guardrails) |
| Telegram / OpenTweet channels | Both out-of-band, ship `enabled: false`, and reach the pipeline only via loopback `POST /query` — see their sections above for the T3/T4 gates and draft-only defaults |
| launchd secrets (macOS) | Generated plists never embed tokens — Keychain wrapper injects at exec time, fails closed when missing; supervised-service generators require `--confirm` + `--reason` |
| `/ops/*` routes | Loopback-only, `require_api_key` gated, rate-limited, every call audited; shells out via `subprocess.run([...])` — never imports `sync/` or `agentic/` |
| `/auth/*` routes | Per-user auth (`gate_auth.py`); first-boot `GET /auth/setup-status` and loopback-only `POST /auth/bootstrap-password`; session cookie + CSRF for browsers, bearer tokens for scripts; three roles gate `/auth/users*`, last `admin` protected; every handler checks `auth.enabled` first, returns 503. When true, `POST /query` requires a session or token |
| `/memory/*` + `/query/export/html` routes | Optional, default-off; every `memory:` switch ships `false`; `require_api_key` gated, rate-limited; mutating routes require a non-empty `reason`, injection scan on `apply` |
| Container | Non-root, `no-new-privileges`, `cap_drop: ALL`, read-only rootfs, seccomp, resource limits; optional eBPF/Falco (`deploy/falco/`, off by default) |
| Dependency risk | Pins tracked in `constraints.txt`, walked by `pip-audit`. One accepted risk: `chromadb==1.5.9` carries CVE-2026-45829 (critical pre-auth RCE, no patch), accepted **only** for the embedded `PersistentClient` mode CyClaw uses. Rationale: [SECURITY.md](SECURITY.md) |

> **Docker / GHCR:** published runtime image `ghcr.io/cgfixit/cyclaw`
> (tag-triggered), host publish `127.0.0.1` only. Guide, Falco opt-in, and
> explicit non-goals (no microVM): [`docs/DOCKER.md`](docs/DOCKER.md).

> **Scope** is unchanged from the top of this README — trusted-operator,
> loopback-bound, single-tenant. LAN/WAN exposure needs an explicit bind
> exception (auth + TLS), never the default. Full threat model:
> [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md); design philosophy:
> [`docs/security-philosophy/`](docs/security-philosophy/).

---

## Project Structure

```text
CyClaw/
├── gate.py                # FastAPI gateway — bind guard, middleware, GraphState hand-off
├── gate_ops.py             # /ops/* subprocess shims (sync/agentic/fsconnect/sqlconnect)
├── gate_auth.py            # /auth/* — session cookie + CSRF, bearer device tokens
├── gate_memory.py          # /memory/* + /query/export/html — default-off memory admin
├── graph.py                # the 12-node LangGraph state machine
├── metrics.py              # audit.jsonl + spend.jsonl analyzer (cyclaw-metrics)
├── spend/                  # token-ledger reference (see Spend Tracking)
├── config.yaml             # single source of truth
├── mcp_hybrid_server.py    # retrieval-only MCP server
├── memory/                 # optional facts + episodes store (default-off)
├── agentic/                # out-of-band GitHub context + governed registry: writer.py
│   (gh pr create --draft), real_repo_loop.py (clone→plan→patch→verify→human
│   decides→commit), executor/ (sandboxed check runner), fsconnect/sqlconnect/
│   netconnect (local FS, read-only SQL, passive LAN), deepagent_github/
├── guardrails/             # opt-in rails; graph nodes via guardrail_bridge
├── telegram/ / opentweet/  # optional channels, out-of-band, shipped enabled: false
├── powershell/ / windows/ / macos/   # per-platform installers, launchd/task glue
├── .claude/                # local operator workflows and prompts (22 project skills)
├── retrieval/              # indexer, hybrid_search (RRF), embeddings, stemmer,
│                           # vector_store (pluggable Chroma/pgvector), clear_cache
├── llm/client.py
├── sync/                   # optional Dropbox corpus sync
├── utils/                  # sanitizer, logger, personality, health, ratelimit,
│   guardrail_bridge (sole bridge to guardrails/), endpoint_trust (destination
│   allowlist), ops_runner, numbat_emitter, spend.py, sequence_detect, authn*
│   (per-user auth stack), gen_cert, telemetry_kill (invariant-guard G1),
│   onnx_telemetry
├── schemas/                # Pydantic API models (extra='forbid', strict)
├── scripts/                # install-githooks.sh, measure_local_llm_throughput.py
├── tools/lora_finetune/    # offline QLoRA kit; installed by no runtime surface
├── deploy/                 # apparmor/ falco/ seccomp/ container hardening
├── tests/ / docs/ / static/
├── data/
│   ├── corpus/ / personality/
│   └── agentic/             # skills_registry.json — governed store, ships empty
└── .github/workflows/
```

Every top-level package carries its own `README.md` (map + traps + links to
its authoritative doc) — the exception is `tools/`, whose README lives at
`tools/lora_finetune/README.md`. The tree omits most files for brevity.

---

## Documentation Map

| Read this | When you want |
|---|---|
| [`setup-guide.md`](setup-guide.md) | every install path step by step, Docker, and every REST endpoint with `curl` |
| [`INVARIANTS.md`](INVARIANTS.md) | the rules behind the graph, which are enforced by code vs. convention, and the test pinning each |
| [`CLAUDE.md`](CLAUDE.md) | the numbered request-path map and the operator conventions AI tooling works under |
| [`SECURITY.md`](SECURITY.md) | egress classification, dependency risk acceptances, disclosure |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | scope, bind exceptions, and the numbered amendments the sections above cite |
| [`docs/AUTHENTICATION_DESIGN.md`](docs/AUTHENTICATION_DESIGN.md) | the per-user auth design and rationale |
| [`docs/DOCKER.md`](docs/DOCKER.md) | the GHCR image, compose hardening, Falco opt-in |
| [`docs/EVALS.md`](docs/EVALS.md) | the four eval planes, thresholds, and what is not yet measured |
| [`spend/README.md`](spend/README.md) | the ledger schema, Keychain service names, live probes |
| [`docs/security-philosophy/`](docs/security-philosophy/) | why telemetry is killed and why offline is the default |
| [`macos/README.md`](macos/README.md) / [`powershell/README.md`](powershell/README.md) | platform scripts, Keychain / Credential Manager, 401 recovery |

---

## License

Source-available, all rights reserved; personal use is permitted — see
[`LICENSE`](LICENSE) for the exact terms.

*Designed and built by Chris Grady, with AI tooling used under human review,
CI, and the invariant guard.*
