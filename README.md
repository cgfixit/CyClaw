# Local (portable) AI you can Trust.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.139-blue.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.9-blue.svg)](https://github.com/langchain-ai/langgraph)
[![CyClaw CI/CD testing](https://github.com/cgfixit/CyClaw/actions/workflows/ci.yml/badge.svg)](https://github.com/cgfixit/CyClaw/actions/workflows/ci.yml)

[![Screenshots: local AI](https://github.com/cgfixit/CyClaw/blob/main/docs/screenshots/grok-a5efec11-9333-4583-8f97-5fa78803f703.jpg)](https://github.com/CGFixIT/CyClaw/tree/main/docs/screenshots)

A private Local AI RAG/Chatbot/Research server for your own documents: hybrid retrieval over a local
corpus, a local model answering from it, and the safety rules written into the
graph that routes the request rather than into a prompt asking a model to
behave. It binds to `127.0.0.1:8787`, runs offline by default, and treats any
call to a paid provider as an exception you approve per question.

## Table of Contents

**The server**

- [Quick Start](#quick-start)
- [What It Does](#what-it-does)
- [Architecture](#architecture)
- [Installation](#installation)
- [Project Structure](#project-structure)
- [Security Model](#security-model)

**Operating it**

- [API Key Setup (Soul Mutations)](#api-key-setup-soul-mutations)
- [Per-User Authentication](#per-user-authentication)
- [Docker / GHCR](docs/DOCKER.md)
- [Full Setup Guide](setup-guide.md)
- [Dropbox Corpus Sync](#dropbox-corpus-sync)
- [macOS launchd & Keychain](#macos-launchd--keychain)
- [Local Model Fine-Tuning](#local-model-fine-tuning)

**Optional layers** (all six ship disabled; enable one by editing `config.yaml`)

- [Agentic Layer](#agentic-layer)
- [Filesystem, SQL & Passive Network Connectors](#filesystem-sql--passive-network-connectors)
- [NeMo Guardrails](#nemo-guardrails)
- [Agentic Coding Loop (GitHub)](#agentic-coding-loop-github)
- [Telegram Channel](#telegram-channel)
- [OpenTweet Channel](#opentweet-channel)

**Beyond this file**

- [Remaining Work](docs/plans/remaining_work.md)
- [Archive & Roadmap](docs/ARCHIVE_AND_ROADMAP.md)

---

## Quick Start

The fastest path to a running RAG server — macOS/Linux shown; only the torch
pin and the activation command differ on Windows (see
[Installation](#installation) for the full per-platform split):

```bash
git clone https://github.com/CGFixIT/CyClaw && cd CyClaw
python3.12 -m venv .venv && source .venv/bin/activate
pip install torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r requirements-test.txt -c constraints.txt --ignore-installed PyYAML
ollama pull qwen3.8:27b-mlx                      # Ollama must already be running on :11434
export CYCLAW_API_KEY="$(openssl rand -hex 20)"  # needed for the /soul/* endpoints
python -m retrieval.indexer                      # builds the retrieval index, once
uvicorn gate:app --host 127.0.0.1 --port 8787    # → http://127.0.0.1:8787
```

Confirm it's alive: `curl http://127.0.0.1:8787/health`.

**On macOS (Apple Silicon, the primary platform):** the `+cpu` torch wheel
above doesn't exist there — use plain `torch==2.13.0` and strip the `torch`/
`--extra-index-url` lines from both manifests first, or just run
`bash ./macos/setup-cyclaw.sh`, which handles the torch difference, Ollama,
the index, and the server for you.

**Full step-by-step guide** — exact per-platform commands, Docker, and
every REST endpoint with a copy-pasteable `curl`:
[`setup-guide.md`](setup-guide.md).

---

## What It Does

CyClaw answers questions from **your documents, on your hardware**. A local
model reads a local index, and once the embedding model is on disk, nothing
leaves the machine unless you say so on that specific question. What makes that
claim checkable is *where* the safety lives: in the shape of the graph, not in a
prompt, a system message, or a config flag someone could forget to set.

**First run is the one exception.** If the sentence-transformer embedding model
is not already in the Hugging Face cache, `retrieval/embeddings.py` fetches it
once — a documented bootstrap rather than a per-question escalation, and not
something `user_confirmed_online` gates. Once the model is cached, a disk-only
probe (`try_to_load_from_cache`, no network) confirms it and every later load
passes `local_files_only=True`, so a warm cache never reaches out again. Seed
the cache on a machine you are happy to let fetch once, and CyClaw is offline
from its first query onward.

### The core — always present, no switches involved

1. **Retrieval comes first, unconditionally.** `retrieve` is the entry node of
   the 12-node LangGraph state machine in `graph.py`; no model call can precede
   it. Routing between nodes is graph edges, never a model's decision, so
   "answer only from the corpus" is a property of the wiring rather than a
   request the model may decline.
2. **Hybrid search over your Markdown corpus** — ChromaDB semantic vectors plus
   BM25 keyword ranking, fused by Reciprocal Rank Fusion (`retrieval.rrf_k`).
   Both legs run locally on CPU. A top hit weaker than `retrieval.min_score`
   (and `retrieval.min_semantic_score`, when a cosine score is present) routes
   to a user gate instead of to a confident guess.
3. **A local model by default** — Ollama serving the tag in
   `models.local_llm.model` (shipped: `qwen3.8:27b-mlx`). The
   prompt-context budget (`retrieval.max_context_tokens`), the generation cap
   (`max_tokens`), and every timeout are `config.yaml` values; nothing tunable
   is hardcoded elsewhere.
4. **A persistent personality layer** (`data/personality/soul.md`) with SHA-256
   drift detection and atomic writes. `POST /soul/apply` — the route that adopts
   *new* content — requires a human `reason` string and runs an enforced
   injection scan. Two paths deliberately differ and are documented as such:
   `POST /soul/restore` re-adopts previously-vetted `.bak` content under a
   hardcoded reason with the scan advisory rather than enforced, and a missing
   `soul.md` self-heals to a default at boot. The soul is governed — neither
   frozen nor self-editable.
5. **Optional online fallback, gated three ways per question** — `app.mode:
   hybrid` AND the chosen provider's own `enabled` flag AND a
   `user_confirmed_online` that lives only in that one request body — it is
   never persisted, never a config key, and never carried over to the next
   question. (It is not a server-enforced two-step challenge: a programmatic
   client may send `true` on its first `POST /query`. What the gate guarantees
   is that *something* has to assert it per request, and that nothing in
   `config.yaml` can assert it once for all of them.) Grok (xAI) and Claude (Anthropic) are picked per query via
   `online_provider`, and both ship armed, so on a default checkout the
   per-question confirmation is the gate actually holding the line. Outbound
   calls are additionally capped by the remaining `api.graph_timeout_sec`
   budget: a retry whose backoff would overrun the deadline is refused rather
   than left to hang.
6. **Two front doors** — a FastAPI gateway bound to `127.0.0.1:8787` (browser
   console at `/`) and a retrieval-only MCP server (`mcp_hybrid_server.py`,
   `sampling: None`) for Claude Desktop / Copilot Studio, which exposes search
   and no model path at all.
7. **An audit trail that hashes the question.** All eleven upstream paths
   converge on `audit_logger` before END, writing a SHA-256 query hash plus
   PII-redacted metadata to `logs/audit.jsonl`, with `cyclaw-metrics` as the
   offline reader. Hashing is the shipped default and the reason the log cannot
   become an exfiltration vector; setting
   `logging.audit_fields.include_query_hash: false` stores raw query text
   instead (redactors still apply) and is privacy-affecting — `utils/logger.py`
   says so in its own module docstring.

Those properties are enforced in four different places, and the distinction
matters to anyone auditing them: graph topology (`retrieve` as entry, routing by
edges, audit convergence), `gate.py` construction (two of the three
external-provider gates — only the per-request confirmation is decided in the
graph), `utils/personality.py` (the soul reason gate and atomic write), and
import structure (module isolation). `python3
.claude/skills/invariant-guard/check_invariants.py` asserts all six statically;
[`INVARIANTS.md`](INVARIANTS.md) records which are enforced by code and which by
convention, and names the test pinning each.

### Optional layers

They are not all isolated the same way, and the table below mixes three kinds.
Authentication and memory are route modules registered onto the gateway itself.
The numbat stream and the spend ledger run *inside* the core path — `audit_log`
lazy-imports `utils/numbat_emitter` on every audit record, and `graph.py`
reaches `utils/spend` through `llm/client.py` — which is why both are `utils/`
rather than out-of-band packages. Only the remaining rows are the I6-isolated
subsystems that `gate.py`, `graph.py`, and the MCP server never import at all,
a boundary asserted statically rather than merely intended. Every row marked
`off` is a no-op until you edit
`config.yaml`. The two marked **on** need no edit to start writing: the numbat
stream projects every audit record, so it grows from your first ordinary local
query, and the spend ledger appends as soon as a confirmed Grok/Claude call is
billed. Both write local files and neither adds network egress — but the numbat
stream is a second *sensitive local log*, not a privacy improvement, and it is
on by default.

| Layer | What it adds | Ships |
|---|---|---|
| [Per-user authentication](#per-user-authentication) (`gate_auth.py`, `utils/authn*`) | scrypt password hashes, session cookie + CSRF for browsers, bearer device tokens for scripts, three roles (`admin`/`operator`/`audit`), `cyclaw-user` CLI. With `auth.enabled: true`, `POST /query` and the console require a session or named token | off |
| Facts + episodes memory (`gate_memory.py`, [`memory/`](memory/README.md); plan in [`docs/memory/`](docs/memory/README.md), not the `docs/memories/` sandbox notes) | SQLite + FTS5 store with propose/apply governance (human `reason` plus an injection scan on apply) and an optional retrieval-fusion hook | off |
| [NeMo Guardrails](#nemo-guardrails) ([`guardrails/`](guardrails/README.md)) | content-safety input rail and an output grounding check, degrading to offline heuristic rails when `nemoguardrails` is absent — defense in depth, never a routing authority | off |
| [Dropbox corpus sync](#dropbox-corpus-sync) (`sync/`) | an `rclone` wrapper that refreshes `data/corpus/` out-of-band and signals "reindex" by exit code | CLI only |
| [Local-data connectors](#filesystem-sql--passive-network-connectors) (`agentic/fsconnect`, `sqlconnect`, `netconnect`) | scoped filesystem reads with gated atomic writes, SELECT-only SQL, and passive LAN inventory with no active probes | off |
| [Agentic layer](#agentic-layer) + [coding loop](#agentic-coding-loop-github) (`agentic/`) | read-only GitHub context via the `gh` CLI, a governed skills registry, and a real-repo clone → plan → patch → verify → **human decides** → commit pipeline whose push and draft-PR steps are two further separate decisions | off |
| [Telegram](#telegram-channel) (`telegram/`) and [OpenTweet](#opentweet-channel) (`opentweet/`) channels | a phone remote and a weekly X poster; both reach the pipeline only through loopback `POST /query`, never a direct `graph.py` call | off |
| Numbat forensic stream (`utils/numbat_emitter.py`) | a derived NDJSON projection of the audit trail at `logs/numbat-events.ndjsonl` that the pinned Numbat 0.2.0 CLI can score for patterns like `exfil.curl_post_file` ([design note](docs/security-philosophy/numbat_secondary_evaluator.md)). Projected after hashing and redaction, but it carries host/user metadata — a second sensitive local log, not a privacy upgrade | **on** |
| Spend ledger (`utils/spend.py`) | token counts per billed Grok/Claude call in `logs/spend.jsonl`, tagged by plane. Tokens are ground truth; dollars are derived at read time by `cyclaw-metrics`, which also flags a stale rate table ([`docs/spend/README.md`](docs/spend/README.md)) | **on** |
| [Fine-tune kit](#local-model-fine-tuning) (`tools/lora_finetune/`) | an offline QLoRA kit that teaches a local model this codebase. Not installed by any runtime install surface | operator toolkit |

---

## Architecture

`gate.py` (FastAPI on `127.0.0.1:8787`) runs the `TrustedHostMiddleware` Host
allowlist, then the per-IP rate limiter (**60 req/min — it runs first, before
the injection filter**), then the config-driven injection filter, then soul
init, and hands a `GraphState` to the 12-node LangGraph state machine in
`graph.py`. Routing is graph edges only — `retrieve` is the unconditional
entry, and every path converges on `audit_logger` before END. The numbered
plain-text version of this flow is [`CLAUDE.md`](CLAUDE.md) §2 "The Map"; the
invariants it encodes are in [`INVARIANTS.md`](INVARIANTS.md).

### LangGraph Topology (rendered)

```mermaid
flowchart TD
    A(["🌐 Client\nHTTP POST /query\nor MCP tool call"])
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
        V["guardrails/\nNeMo rails skeleton"]
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


What the diagram compresses: `HybridRetriever` (`retrieval/hybrid_search.py`)
fuses ChromaDB (semantic, `all-MiniLM-L6-v2`, 384-dim cosine, CPU-only
embeddings) with BM25Okapi (keyword, Porter stemming) by RRF (`k=60`, equal
weighting) and carries per-chunk provenance metadata in every result. The
telemetry kill block runs before any SDK import, and the MCP server and the
indexer apply the same block.

---

## API Key Setup (Soul Mutations)

CyClaw's soul mutation endpoints (`/soul/propose`, `/soul/apply`, `/soul/reload`, `/soul/restore`) require a **Bearer API key**. Without it they return `HTTP 401` immediately — intentional fail-closed behavior.

> **All `/soul/*` endpoints — including `GET /soul` — require a valid `Authorization: Bearer <key>` token.** Only `/health`, `/query`, `GET /index/status`, `GET /auth/setup-status`, `POST /auth/login` (issues the session itself; 503 when `auth.enabled` is false), and the console pages (`GET /`, `/static/*`) are unauthenticated. `POST /index/build` and `POST /auth/bootstrap-password` carry no credential either, but neither is open: each is gated on a loopback socket peer plus a same-origin check and returns 403 off-box — `/index/build` 409 while a build is already running, `/auth/bootstrap-password` 409 once the first admin password is set. `POST /query`, though credential-free by default, additionally carries an **unconditional same-origin check** — a cross-site browser request is rejected 403 `CROSS_SITE_BLOCKED` regardless of `auth.enabled`; requests carrying neither `Origin` nor `Sec-Fetch-Site` (curl, PowerShell, schedulers) are unaffected.

> **Opting out entirely:** `config.yaml`'s `security.api_key_optional` (default `false`) removes the `CYCLAW_API_KEY` requirement from every route above, for both apps at once — but **only for requests arriving from this machine**. The bypass is granted on the socket peer, so a remote caller still needs the real key no matter how the process was launched. Entries in `security.allowed_hosts` do not change that: that list filters request `Host` headers and opens no listening socket. What *would* matter is the bind itself — `gate.py` refuses to start with a non-loopback `api.host` while the flag is `true`, and `config-guard`'s C13 warns on that pair. Note it also does nothing under Docker: NAT rewrites the source address, so the container sees the bridge gateway rather than loopback and the routes stay key-gated (set `CYCLAW_API_KEY` in the container instead).

### macOS / Linux — zsh or bash

Set it for the current shell. Generate a real value instead of typing one —
`openssl` ships with macOS and every Linux distribution:

```bash
export CYCLAW_API_KEY="$(openssl rand -hex 20)"
echo "$CYCLAW_API_KEY"
uvicorn gate:app --host 127.0.0.1 --port 8787
```

Persist it in your shell profile. macOS has defaulted to **zsh** since
Catalina, so that means `~/.zshrc` unless you switched — check with
`echo $SHELL`. On bash, append it to the first existing login file in this
order: `~/.bash_profile`, `~/.bash_login`, `~/.profile`; create
`~/.bash_profile` only when none exists, because macOS bash login shells do not
read `~/.bashrc` (Linux bash does).

```bash
echo 'export CYCLAW_API_KEY="your-strong-local-secret"' >> ~/.zshrc   # or the bash file above
source ~/.zshrc
```

Full macOS walkthrough — including exercising every REST endpoint with
`curl` — is in
[`setup-guide.md`](setup-guide.md#macos-apple-silicon).

### Windows — PowerShell / cmd.exe

*(Windows is the fallback path; CyClaw is developed and verified on macOS
first. Everything below still works and is CI-covered on `windows-latest`.)*

```powershell
$env:CYCLAW_API_KEY = "your-strong-local-secret"      # current session only
uvicorn gate:app --host 127.0.0.1 --port 8787
```

Persist it for the current user (writes the user environment permanently);
verify with `echo $env:CYCLAW_API_KEY` before launching:

```powershell
[System.Environment]::SetEnvironmentVariable("CYCLAW_API_KEY", "your-strong-local-secret", [System.EnvironmentVariableTarget]::User)
```

Windows Server, system-wide (all users, requires admin): the same call with
`[System.EnvironmentVariableTarget]::Machine`, or **System Properties →
Advanced → Environment Variables → System variables → New**. From cmd.exe:
`set CYCLAW_API_KEY=your-strong-local-secret` for the session and
`setx CYCLAW_API_KEY "your-strong-local-secret"` to persist.

### All platforms — `.env` file (already in `.gitignore`)

Create `.env` in the repo root:

```
# Keys live here, never in config.yaml — config.yaml only names which
# provider is enabled; the key itself is read from the environment.
CYCLAW_API_KEY=your-strong-local-secret
GROK_API_KEY=your-xai-key-or-dummy-when-offline
ANTHROPIC_API_KEY=your-anthropic-key
```

Then tighten it — a hand-created file inherits the shell's umask (usually
`0644`, i.e. world-readable), and `macos/invoke-cyclaw.sh` **refuses to source a
dotenv that is not `600` or `400`** rather than load secrets from a file other
local accounts can read:

```bash
chmod 600 .env
```

On Windows, a hand-created file often inherits `BUILTIN\Users` read. Tighten it
the same way `powershell/Invoke-CyClaw.ps1` requires before it will source the
file (owner-only; refuse Everyone / Users / Authenticated Users):

```powershell
icacls .env /inheritance:r /grant:r "${env:USERNAME}:(R,W)"
```

`macos/setup-cyclaw-keys.sh` already writes `~/.CyClaw/.env` at `600`; only
a hand-made file needs this step.

The Claude variable is **`ANTHROPIC_API_KEY`**, not `CLAUDE_API_KEY` —
`llm/client.py` and `agentic/config.py` both read the former, and nothing in
the codebase reads the latter. Setting the wrong name is silent: Claude simply
reports unavailable and the query falls back to a local answer.

Load it before launching:

```bash
# Bash / Zsh
export $(grep -v '^#' .env | xargs)
uvicorn gate:app --host 127.0.0.1 --port 8787
```

```powershell
# PowerShell
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#=][^=]*)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim())
    }
}
uvicorn gate:app --host 127.0.0.1 --port 8787
```

### Choosing an API key value

CyClaw is loopback-only (`127.0.0.1:8787`) — the key never crosses a network. Still:

- Use at least **20 random characters**: `openssl rand -hex 20` (Linux/macOS) or `[System.Web.Security.Membership]::GeneratePassword(24,4)` (PowerShell)
- Do **not** reuse a password from elsewhere
- Do **not** commit the key to Git (`.env` is already in `.gitignore`)
- Don't forget to set the api key via terminal on Mac or env var in Windows or the web app will not recognize it.

## Per-User Authentication

CyClaw ships **two independent credential systems**, and confusing them is the
most common setup mistake:

| System | Secret | Guards | Toggle |
|---|---|---|---|
| **Operator API key** | `CYCLAW_API_KEY` env var (Bearer) | `/soul/*`, `/ops/*`, `/memory/*`, `/audit/summary` | Always on (fail-closed when unset); `security.api_key_optional` is the one deliberate loopback-peer bypass |
| **Per-user auth** | Per-account scrypt password → session cookie, or a named device token | `POST /query` and the console's user surface | `auth.enabled` in `config.yaml` — ships **`false`** |

The per-user layer is `gate_auth.py` + `utils/authn*`; the full design is
[`docs/AUTHENTICATION_DESIGN.md`](docs/AUTHENTICATION_DESIGN.md). With
`auth.enabled: false` (the shipped default) `POST /query` takes no credential
and every `/auth/*` route answers **503**, not 404 — route presence never
discloses whether the feature is on.

### Turning it on

1. Set `auth.enabled: true` in `config.yaml` and restart `gate.py`. The store is
   SQLite at `auth.db_path` (`data/auth/cyclaw_auth.db`); `CYCLAW_AUTH_DB_URL` —
   its **own** env var, deliberately not the personality subsystem's
   `CYCLAW_DB_URL` — switches it to a `postgresql://` DSN.
2. Set the first admin password. The bootstrap account is username **`admin`**,
   created with no password. Use the terminal console's first-boot box on
   loopback, or post directly:

   ```bash
   curl -s -X POST http://127.0.0.1:8787/auth/bootstrap-password \
     -H 'Content-Type: application/json' \
     -d '{"password":"<a long passphrase>"}'
   ```

   That route is **loopback-peer + same-origin only** — 403 from off-box, 409
   once a password is set, 503 when `auth.enabled` is false — and carries no
   credential on purpose: on a genuine first run there is nothing to present
   yet. `GET /auth/setup-status` (no credential, but same-origin-checked and rate-limited) reports
   `{enabled, needs_password, username}` so a console can tell first-boot from
   logged-out.
3. Add the accounts operators actually use with the local-only `cyclaw-user`
   console script (no HTTP route reaches it). Subcommands: `add`, `list`,
   `role`, `disable`, `enable`, `passwd`, `token create|list|revoke`; new
   accounts default to `operator`:

   ```bash
   cyclaw-user add alice --role operator     # prompts for the password
   cyclaw-user token create alice laptop     # prints the token ONCE
   ```

### Roles, sessions, lockout

Three roles, checked server-side on every request:

| Capability | `admin` | `operator` | `audit` |
|---|---|---|---|
| `POST /query` | yes | yes | **no** — 403 `AUTH_ROLE_DENIED` |
| List users (`GET /auth/users`) | yes | yes | no |
| Create user / reset another user's password | yes | yes, but never on an `admin` account | no |
| Set role, delete user | yes | no | no |
| Disable / enable | yes | non-admins only | no |
| Change own password (`POST /auth/password`) | yes | yes | yes |
| `GET /auth/audit/summary` | yes | no | yes |

The **last enabled `admin` is protected** — disable, delete, and role-change
all refuse it, so an operator cannot lock the deployment out of its own admin
surface. `GET /auth/audit/summary` is the reduced, session-gated audit view, not
the API-key-gated `GET /audit/summary`.

Browsers get a `cyclaw_session` cookie plus a CSRF token that every mutating
`/auth/*` route requires in the `X-CyClaw-CSRF` header; `POST /query` is
deliberately CSRF-exempt because it takes a session *or* a bearer device token
and mutates no auth state. Programmatic clients send a named device token as
`Authorization: Bearer <token>` — displayed once, stored only as a hash,
revoked by label. A session dies at whichever of `auth.session`'s two limits
comes first: `idle_timeout_sec: 43200` (12 h, rolling) or
`absolute_timeout_sec: 604800` (7 d, never resets). Failed logins back off per
account — the first **5** consecutive failures are free, then the delay doubles
from 2 s to a **900 s ceiling**; no admin action is needed to recover.
Passwords are scrypt-hashed (`utils/authn.py`), and no password, session id,
CSRF token, or device token is ever written to `audit.jsonl`. Design and
rationale: [`docs/AUTHENTICATION_DESIGN.md`](docs/AUTHENTICATION_DESIGN.md).

### Serving it beyond loopback

Enabling `auth.enabled` does **not** by itself make a non-loopback bind safe or
permitted. `gate.py`'s `_require_loopback_bind` still refuses a non-loopback
`api.host`, and the auth+TLS route past it is refused outright while
`security.api_key_optional` is `true` — that flag removes the `CYCLAW_API_KEY`
gate from `/soul/*`, `/ops/*`, and `/memory/*`, which per-user auth does not
replace. Set `security.api_key_optional` back to `false` first, then generate a
certificate with the bundled openssl wrapper (no new runtime dependency):

```bash
cyclaw-gen-cert --hostname "$(hostname)" --days 825
```

Flags: `--certfile`, `--keyfile`, `--hostname` (defaults to the machine
hostname), `--days` (default `825`), `--san` (repeatable extra SAN entry,
e.g. `IP:10.0.0.5` or `DNS:box.local`), and `--force` — **required to
overwrite an existing cert/key pair**; without it the command refuses rather
than clobbering one. Read
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) before exposing the port —
CyClaw's stated scope is trusted-operator (single by default, a small trusted
group behind `auth.enabled`), loopback-bound, and single-tenant.

## Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 | Primary supported runtime |
| [Ollama](https://ollama.com/) | Any | Must be running on `localhost:11434` |
| Model pulled in Ollama | — | `qwen3.8:27b-mlx` (default), `mistral:7b`, or any chat model |
| **macOS** (primary) | 14 Sonoma+ | **Apple Silicon only.** An Intel Mac cannot install this repo's pinned torch at all — no `x86_64` wheel is published at that pin |
| Windows / Linux (fallback) | — | Both fully supported and CI-covered; they share the `+cpu` torch path below |


**Optional local-backend failover.** Ollama is the primary local backend;
CyClaw can also fail over to LM Studio (or any OpenAI-compatible loopback
server) when Ollama isn't reachable. Off by default — set
`models.local_llm.fallback.enabled: true` and fill in `fallback.model` with
the LM Studio id (no Ollama-style `name:tag` colon). A short probe
(`fallback.probe_timeout_sec`, default 1.5s) tries Ollama first and LM Studio
second, `LocalLLMClient` and `/health` share the choice, and it re-probes if
neither answered the first time (`llm/client.py`'s `resolve_local_backend`).

### Docker (optional runtime image)

Prefer GHCR when you want a prebuilt `linux/amd64` runtime without a local `pip install`.
Pull `ghcr.io/cgfixit/cyclaw` and run with the existing compose hardening (loopback publish,
read-only rootfs, seccomp builtin). Full operator guide: [`docs/DOCKER.md`](docs/DOCKER.md).

```bash
export CYCLAW_IMAGE_TAG=1.9.0
docker compose pull && docker compose up -d
curl -sS http://127.0.0.1:8787/health
```

Native install (below) remains the primary path for Apple Silicon.

### Install — macOS (Apple Silicon)

macOS is the primary platform and needs a **different torch step** than
Windows/Linux: the `+cpu` local-version wheel does not exist for macOS, and
both manifests hardcode that pin, so the generic block fails twice on a Mac.

```bash
git clone https://github.com/CGFixIT/CyClaw
cd CyClaw
python3.12 -m venv .venv
source .venv/bin/activate
# 1) torch FIRST, and PLAIN — no +cpu suffix, no --index-url override.
#    Apple Silicon has one arm64 wheel; there is no CPU/CUDA build to pick between.
pip install "torch==2.13.0"
# 2) Everything else, from a requirements.txt copy with the torch and
#    PyTorch-index lines stripped out, and a constraints.txt copy that keeps
#    torch pinned minus the +cpu suffix (--ignore-installed reinstalls torch
#    too, so an unconstrained copy floats it) — the same thing CI's
#    macos-latest leg runs.
grep -v -e '^torch==' -e '^--extra-index-url https://download.pytorch.org' \
    requirements.txt > /tmp/requirements-macos.txt
sed 's/^\(torch==[0-9][0-9.]*\)+cpu$/\1/' constraints.txt > /tmp/constraints-macos.txt
pip install -r /tmp/requirements-macos.txt -c /tmp/constraints-macos.txt \
    --ignore-installed PyYAML
```

Prefer a script? `bash ./macos/setup-cyclaw.sh` is the single operator-facing
entry point (offers to clone, asks its few choices once, then runs
`macos/setup-from-clone.sh`: installer + Keychain keys + Ollama check +
retrieval index + a running server). `bash ./macos/install-cyclaw.sh` is the
installer alone — it handles the torch difference but skips the Ollama / index /
API-key steps, so the gateway stays degraded (503 on `/query`) until you do
them. Flags, privacy notes, and tradeoffs:
[`macos/README.md`](macos/README.md#one-command-apple-silicon) and
[`setup-guide.md`](setup-guide.md#option-a--the-installer-script-handles-the-torch-difference-for-you).

### Install — Windows / Linux (fallback)

```bash
git clone https://github.com/CGFixIT/CyClaw
cd CyClaw
python3.12 -m venv .venv
source .venv/bin/activate
# 1) CPU-only torch first (CVE-2025-32434 fixed in 2.6.0; 2.13.0 is within the patched range)
pip install torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
# 2) The rest, pinned to the verified transitive tree. --ignore-installed PyYAML
#    avoids a resolver conflict with a system PyYAML some platforms preinstall.
pip install -r requirements.txt -r requirements-test.txt -c constraints.txt --ignore-installed PyYAML
```

### Every optional feature in one environment (any platform)

For a from-scratch dev box or a full manual smoke test — Postgres/pgvector, NeMo
Guardrails, dev/test tools, and both cloud providers — substitute step 2 with:

```bash
pip install -e ".[all]" -c constraints.txt
```

### Required local prep

```bash
mkdir -p index logs   
export GROK_API_KEY=dummy
```
^ # optional — gate.py/the retriever/logger self-create these on first run

`data/personality/soul.md` ships committed to git with CyClaw's real
personality already in place — do not recreate it from a placeholder on a
fresh clone. If it's ever deleted, `PersonalityManager` self-heals with a
generic default, but that's a recovery path, not the normal first-run state.

### Run

CyClaw ships **two** independent local web apps. Neither starts the other; run
whichever you need, or both in separate terminal tabs.

```bash
# The RAG gateway — serves static/terminal.html at / plus the whole REST API
python -m retrieval.indexer                          # once, before the first /query
uvicorn gate:app --host 127.0.0.1 --port 8787        # → http://127.0.0.1:8787
```

**The `cyclaw-*` short names need a self-install.** `cyclaw-server`,
`cyclaw-index`, `cyclaw-mcp`, `cyclaw-metrics`,
`cyclaw-clear-cache`, `cyclaw-user`, and `cyclaw-gen-cert` are
`[project.scripts]` shims that pip writes only when the project itself is
installed; `requirements.txt` has no self-install line, so add
`pip install -e . -c constraints.txt` if you want them. The `python -m …` forms
always work and are what both shipped launchers use.

Open `/` for the terminal UI and `/health` for readiness. The terminal exposes five operator consoles — **Soul**, **Sync**, **Agentic**, **Filesystem**, and **SQL** — the latter four calling `POST /ops/sync`, `/ops/agentic`, `/ops/fsconnect`, and `/ops/sqlconnect` (API-key gated, rate-limited, audited).

Every gateway route with a copy-pasteable `curl` invocation, plus what each
status code means, is in
[`setup-guide.md`](setup-guide.md#rest-api--testing-every-endpoint-from-the-terminal).

---

## Project Structure

```text
CyClaw/
├── gate.py
├── gate_ops.py                 # /ops/* endpoints (sync/agentic/fsconnect/sqlconnect subprocess shims)
├── gate_auth.py                # /auth/* endpoints — session cookie + CSRF, bearer device tokens
├── gate_memory.py              # /memory/* + /query/export/html — optional, default-off memory admin surface
├── graph.py
├── metrics.py                  # audit.jsonl analyzer + spend.jsonl Spend section (cyclaw-metrics)
├── config.yaml                 # single source of truth
├── README.md
├── mcp_hybrid_server.py        # retrieval-only MCP server
├── memory/                     # optional facts + episodes store (default-off)
│   ├── README.md               # package pointer (not docs/memories/)
│   ├── store.py                # SQLite + FTS5 backend for facts/episodes
│   ├── policy.py               # propose/apply governance (reason required, injection scan)
│   ├── retrieval_adapter.py    # optional fusion hook into hybrid retrieval
│   ├── mirror.py               # episode staging (lazy, non-fatal)
│   ├── consolidation.py        # stub — stay false in v1
│   └── models.py               # typed request/response shapes
├── agentic/                    # out-of-band GitHub context + governed registry (see README.md)
│   ├── cli.py
│   ├── context.py
│   ├── gh_client.py
│   ├── registry.py
│   ├── writer.py               # gh pr create --draft; armed flag, held by agentic.enabled
│   ├── real_repo_loop.py       # clone → plan → patch → verify → human decides → commit
│   ├── unslop_bridge.py        # offline slop-detection probe for real_repo_loop; default off
│   ├── vendor/unslop/          # vendored offline AI-writing-tell scanners (suggest.py); no network calls
│   ├── executor/               # sandboxed argv-list check runner; required fail-closed hard sandbox (hard_sandbox.py)
│   ├── fsconnect/              # local/SMB filesystem connector
│   │   ├── cli.py
│   │   ├── client.py           # scoped reads (fs_list/stat/read/grep)
│   │   ├── pathsafe.py         # held-handle containment core (POSIX + Windows reads)
│   │   ├── writer.py           # gated, atomic writes (default-disabled)
│   │   └── indexer.py          # toggleable RAG-corpus indexing of the share
│   ├── sqlconnect/             # read-only SQL scaffold (Postgres/MSSQL)
│   │   ├── cli.py
│   │   └── client.py           # SELECT-only query guard, env-only DSN
│   ├── harness_optimizer/      # retired 2026-07-31 train/holdout scaffold; kept and tested, all gates false
│   │   ├── core.py             # Experiment/Surface/RunReport/CandidateDecision models
│   │   ├── proposer.py         # scoped train/holdout workspace builder
│   │   ├── mcp/tools.py        # audited, symlink-hardened proposer workspace tools
│   │   └── governance.py       # visible-case-hardcoding + governance-finding gates
│   └── deepagent_github/       # live workspace tools + cloud planner; DeepAgents subgraph retired
│       ├── repo_workspace.py   # live: jailed workspace tools (clone/read/write/commit/push) used by real_repo_loop
│       ├── chat_client.py      # live: cloud-provider planner adapter (Grok/Claude)
│       ├── builder.py          # retired DeepAgents subgraph (2026-07-31) — kept, not deleted
│       ├── permissions.py      # phase-5 no-write policy refusal
│       └── subagents.py        # validated SubAgent specs, no bare-string tools
├── guardrails/                 # opt-in rails; graph nodes via guardrail_bridge
│   ├── README.md
│   ├── cli.py
│   ├── config.py
│   ├── integration.py          # soft-imports nemoguardrails; degrades gracefully
│   ├── rails.py                # offline heuristic rails (injection/soul/grounding)
│   ├── metrics.py              # separate logs/guardrails.jsonl stream (hashes only)
│   └── config/                 # NeMo config.yml + rails.co (Colang flows)
├── telegram/                   # optional Telegram channel (out-of-band), shipped enabled: false
│   ├── cli.py
│   ├── client.py               # Bot API client — outbound notify + long-poll inbound chat
│   ├── config.py               # loads config.yaml's `telegram:` block
│   ├── runner.py                # long-poll loop; answers via loopback POST /query only
│   ├── state.py                 # T3 hybrid-confirm consent state (default off)
│   ├── media.py                 # T4 attachment staging via agentic/fsconnect (default off)
│   └── ratelimit.py
├── opentweet/                  # optional X channel (out-of-band), shipped enabled: false
│   ├── cli.py                  # status / test / post / schedule-plist / schedule-task
│   ├── client.py               # loopback /query + OpenTweet REST; trust_env=False
│   ├── config.py               # loads config.yaml's `opentweet:` block
│   ├── runner.py               # topic → query → validate → draft/schedule
│   └── selftest.py
├── powershell/                 # Windows installer/launcher for the RAG gateway
│   ├── Install-CyClaw.ps1      # home + venv + PATH shim + profile function
│   ├── Invoke-CyClaw.ps1
│   └── Uninstall-CyClaw.ps1
├── macos/                      # macOS/Linux installer/launchd glue (see macos/README.md)
│   ├── setup-cyclaw.sh         # single entry point: clone? + one-shot + optional start/browser/autofill
│   ├── setup-from-clone.sh     # one-shot after git clone (Apple Silicon)
│   ├── install-cyclaw.sh
│   ├── uninstall-cyclaw.sh
│   ├── invoke-cyclaw.sh        # gate :8787
│   ├── setup-cyclaw-keys.sh    # Keychain + ~/.CyClaw/.env (never config.yaml)
│   ├── setup-fsconnect.sh      # confined ~/CyClaw-FS list/stat/read
│   ├── cyclaw-keychain-*.sh    # Keychain inject/store for launchd jobs
│   ├── generate_service_plist.py  # supervised gate LaunchAgent — requires --confirm + --reason, never loads
│   └── LaunchAgents/           # templates only — never auto-loaded
├── .claude/                    # local operator workflows and prompts
│   ├── commands/
│   ├── hooks/
│   ├── memory/
│   ├── patterns/
│   ├── rules/
│   ├── skills/
│   ├── tools/
│   └── utility-prompts/
├── retrieval/
│   ├── indexer.py
│   ├── hybrid_search.py
│   ├── embeddings.py
│   ├── stemmer.py
│   ├── vector_store.py         # pluggable: embedded ChromaDB (default) or pgvector; sole Chroma chokepoint
│   └── clear_cache.py          # dry-run-by-default embedding-cache cleaner (cyclaw-clear-cache)
├── llm/
│   └── client.py
├── sync/                       # optional Dropbox corpus sync
│   ├── cli.py
│   ├── runner.py
│   └── scheduler.py
├── utils/
│   ├── sanitizer.py
│   ├── logger.py
│   ├── personality.py
│   ├── health.py
│   ├── ratelimit.py
│   ├── launchd_plist.py        # stdlib-only plist builder shared by the telegram / fsconnect / opentweet / generate_service_plist generators (sync.scheduler builds its own)
│   ├── guardrail_bridge.py     # only bridge from graph.py to guardrails/ (never a direct import)
│   ├── endpoint_trust.py       # destination allowlist: loopback-or-trusted_hosts for the local model, api.x.ai / api.anthropic.com for the online ones
│   ├── ops_runner.py           # subprocess shim behind /ops/* — never imports sync/ or agentic/
│   ├── config_validation.py    # boot-time config validation; fails fast
│   ├── errors.py               # typed exception hierarchy rooted at RAGError
│   ├── repo_paths.py           # repo-root anchoring so nothing resolves against cwd
│   ├── numbat_emitter.py       # derived Numbat NDJSON stream: action-plane emits + mainline audit projection
│   ├── spend.py                # append-only Grok/Claude token ledger (logs/spend.jsonl); dollars derived at read time
│   ├── sequence_detect.py      # offline forensic join of audit.jsonl + spend.jsonl on query_hash (CLI only)
│   ├── authn.py                # per-user auth primitives: scrypt hashing, lockout arithmetic, id generation
│   ├── authn_store.py          # users/sessions/device_tokens backend (CYCLAW_AUTH_DB_URL)
│   ├── authn_manager.py        # AuthManager — ties authn.py + authn_store.py together; no HTTP awareness
│   ├── authn_cli.py            # cyclaw-user console script (local-only by construction)
│   ├── gen_cert.py             # cyclaw-gen-cert — self-signed cert + key with hostname/LAN SAN
│   ├── telemetry_kill.py       # shared kill block — applied by gate.py, the five out-of-band package __init__.py files, and eight module-level chokepoints (invariant-guard G1 pins all 14 orderings)
│   └── onnx_telemetry.py       # post-import ONNX Runtime suppression at the two model-load seams
├── schemas/                    # Pydantic API models (api.py; extra='forbid', strict)
├── scripts/                    # install-githooks.sh, check-pr-template.sh, measure_local_llm_throughput.py
├── tools/
│   └── lora_finetune/          # offline QLoRA kit for local_llm.model; installed by no runtime surface (see Local Model Fine-Tuning)
├── deploy/                     # apparmor/ falco/ seccomp/ container-hardening profiles (all opt-in)
├── tests/
├── docs/
├── static/
├── data/
│   ├── corpus/
│   ├── personality/
│   └── agentic/                # skills_registry.json — governed store, ships empty
└── .github/workflows/
```

Every top-level package and directory above carries its own `README.md`
(map + traps + links to its authoritative doc) — the one exception is `tools/`,
whose README lives a level down at `tools/lora_finetune/README.md`. The tree
omits most of them for brevity.

---

## Dropbox Corpus Sync

An **optional, out-of-band** `rclone`-backed pull sync mirrors a Dropbox corpus
into `data/corpus/` without touching `gate.py`, `graph.py`, or the MCP request
path. It carries safety fuses (`max_delete`, `max_transfer`), an OS-backed
single-instance lock (`fcntl.flock` / `msvcrt.locking`) that keeps a scheduled
run and a manual run from racing and releases even if the process dies, audit
logging of changed corpus files, an optional reindex trigger, and scheduler glue
for cron / Windows Task Scheduler plus an opt-in Darwin-only launchd backend
(`sync.scheduler_backend: "launchd"`, `schedule_frequency` daily/weekly/monthly)
that generates the plist and prints the `launchctl bootstrap` command — never
loading it itself.

```bash
python -m sync.cli setup          # first-run bootstrap; then: test | sync --dry-run | sync | status | schedule | unschedule
```

The **Sync Console** panel drives the same actions via `POST /ops/sync`
(loopback-only, API-key gated, audited). Full setup and scheduling:
[`docs/! How-To-Guides/Dropbox_Sync_Guide.md`](docs/%21%20How-To-Guides/Dropbox_Sync_Guide.md);
module internals (lock lifecycle, exit codes, error taxonomy):
[`docs/SYNC_README.md`](docs/SYNC_README.md).

---

## macOS launchd & Keychain

CyClaw's scheduled and supervised jobs on macOS run through **generated launchd
LaunchAgents** with one uniform posture: every generator writes a plist from
real resolved install paths and prints the exact `launchctl bootstrap` command
— **none of them ever loads the agent itself**. Loading a background job is
always a separate, explicit operator action.

- **Secrets never land in a plist.** Token-bearing jobs chain
  `macos/cyclaw-keychain-env.sh`, which fetches the secret from the Keychain at
  process start, exports it, and `exec`s the real command — failing closed
  (nothing launched) if the item is missing or empty. Store secrets first with
  `macos/cyclaw-keychain-set.sh`, a no-echo prompt driven by `security` itself
  so the secret never appears in any argv; the item is trust-pinned with
  `-T /usr/bin/security`.
- **Scheduled jobs** — Dropbox sync (see [Dropbox Corpus Sync](#dropbox-corpus-sync)),
  Telegram poll/health, fsconnect trash emptying, and OpenTweet — each a
  generate-only `*-plist` subcommand (commands below).
- **Supervised services** (highest risk) — `macos/generate_service_plist.py`
  writes a KeepAlive LaunchAgent for `gate.py`. Because
  that turns a loopback server into an always-on listener that survives reboot,
  it refuses to write without `--confirm` **and** a non-empty `--reason` (the
  reason-required idiom soul mutations use). Restart-on-crash only; a clean
  `launchctl stop` stays stopped.
- **Uninstall symmetry** — `macos/uninstall-cyclaw.sh` unschedules any
  registered sync job and boots out + removes landed CyClaw LaunchAgents by
  label (`telegram-poll`, `telegram-health`, `fsconnect-trash`, `gate`,
  `keys-rotate`, `opentweet`, plus the retired console's `harness` label so
  an older install's agent is still removed), so no background job outlives the
  install. Sync's own launchd job is owned by `sync.cli unschedule`.

**Core commands**

```bash
bash macos/cyclaw-keychain-set.sh com.cgfixit.cyclaw.telegram-bot-token   # store a secret (TTY prompt)
python -m telegram.cli poll-plist                                        # Darwin-only; generates, never loads
python -m telegram.cli health-plist
python -m agentic.fsconnect.cli trash-empty-plist
python -m opentweet.cli schedule-plist                                   # Darwin-only; generates, never loads
python macos/generate_service_plist.py --service gate \
    --reason "keep the RAG server up across reboots" --confirm
```

Script-by-script reference: [`macos/README.md`](macos/README.md). Design and
phase ledger: [`docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md`](docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md).

---

## Local Model Fine-Tuning

Retrieval tells the local model what this codebase *says*; a fine-tune teaches
it how this codebase *thinks*, so an operator model stops re-deriving the same
invariants on every question. `tools/lora_finetune/` is a QLoRA kit for
`models.local_llm.model` built on a curated Q&A dataset generated from live
source — `graph.py`, `INVARIANTS.md`, `retrieval/indexer.py`, `llm/client.py`,
`config.yaml` — with each example carrying `source_refs` back to the file it
came from.

**It is an operator toolkit deliberately outside the runtime.** No CyClaw
install surface — `requirements.txt`, `pyproject.toml` extras, Docker, or conda
— pulls Unsloth, Transformers, TRL, Datasets, or Accelerate. Training happens on
a separate CUDA box; the server never imports any of it, and the kit's own pins
are excluded from this repo's OSV walk precisely because that GPU tree is not
installed here.

**It is not air-gapped, though.** `finetune_qwen38.py` calls
`FastModel.from_pretrained` with a Hugging Face repo id and no
`local_files_only`, so the base checkpoint downloads on first run, and
rebuilding the dataset can pull a tokenizer the same way. On a machine with no
egress, seed the model and tokenizer caches first — "offline" here means
independent of the CyClaw server and its config, not free of network.

```bash
python tools/lora_finetune/build_cyclaw_corpus.py   # rebuild the dataset from source
python tools/lora_finetune/dryrun_finetune.py       # full control flow, mocked, no GPU
pip install -r tools/lora_finetune/requirements.txt # on the CUDA box only
```

Dataset shape, category counts, the Unsloth pin caveat, and the
`pip-audit`-on-the-GPU-box step are in
[`tools/lora_finetune/README.md`](tools/lora_finetune/README.md).

---

## Agentic Layer

CyClaw ships a **concise, governed agentic layer** for local operator workflows. It is **opt-in, disabled by default, and fully out-of-band**: it is never imported by `gate.py`, `graph.py`, or `mcp_hybrid_server.py`. `data/agentic/skills_registry.json` is a governed store that ships empty (`apply-skill` writes it). Package guide: [`agentic/README.md`](agentic/README.md).

What it adds: read-only GitHub context through the `gh` CLI (invoked as an
argv list, never via a shell; no GitHub token is stored or forwarded by
CyClaw), a governed local skills registry with explicit human gating, and the
operator workflows under `.claude/` ([`.claude/README.md`](.claude/README.md)).
All agentic reads, refusals, and registry changes are audit logged.

The GitHub write path (`gh pr create --draft`) is implemented and its
code-level gate `EXECUTION_ENABLED` ships `True` (operator-signed 2026-08-07),
as do `mode: "write"` and `writes_enabled`. The layer master switch
`agentic.enabled` still ships `false`, so a default checkout cannot open a PR —
that switch, plus a per-call `reason` and `confirm`, is what refuses. Procedure
and the `CYCLAW_AGENTIC_WRITE_DISABLE` rollback:
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
python -m agentic.cli context --repo
python -m agentic.cli context --pr 123
python -m agentic.cli context --issue 45
python -m agentic.cli test
python -m agentic.cli propose-skill --name deploy --desc "..." --body-file s.md --reason "draft"
python -m agentic.cli apply-skill --name deploy --desc "..." --body-file s.md --reason "add deploy runbook" --confirm
```


The **Agentic Console** panel drives these from the terminal UI via
`POST /ops/agentic`; skill-Apply is refused under shipped defaults by
`agentic.enabled: false` (the CLI no-ops while it is off), and a per-call
`reason` + `--confirm` remain mandatory once it is on.

---

## Filesystem, SQL & Passive Network Connectors

Three connectors extend the agentic layer beyond GitHub to **local data**, for the regulated or security-conscious case where AI use is compliance heavy. All three connectors are **opt-in, disabled by default, and fully out-of-band** — never imported by `gate.py`, `graph.py`, or `mcp_hybrid_server.py`, so the six security invariants hold by construction. While disabled, their CLIs are a pure no-op (exit 0).

### `agentic/fsconnect/` — local / SMB filesystem connector

Scoped **reads** and separately-gated **writes** over a local or SMB share,
sharing one held-handle security core (`pathsafe.py`): POSIX descends with
`openat` / `O_NOFOLLOW` from a held root fd; Windows read/list/stat locks the
canonical root ancestry against rename, opens once with `CreateFileW`, verifies
`GetFinalPathNameByHandleW` containment, and consumes that same handle —
Windows writes remain hard-refused. UNC, NTFS alternate data streams
(`file::$DATA`), `\\?\` / `\\.\` device paths, `..` traversal, and symlink /
reparse traversal are denied; segment-aware containment closes
**CVE-2025-53110** (sibling-prefix), and held-handle authority prevents
name-reopen junction swaps.

- **Reads** (`fs_list` / `fs_stat` / `fs_read` / `fs_grep` / `fs_glob` /
  `fs_largest`) are confined to `allowed_roots`, audited, capped at 5 MiB, and
  content-scanned (OWASP ∪ `banned_patterns`, advisory).
- **Writes** (`fs_write` / `fs_append` / `fs_mkdir` / `fs_move`) ship
  **`writes_enabled: false`**; confined to a **separate** `writable_roots` list;
  gated by a human `reason` (+ `--confirm` for destructive ops); atomic
  (`tmp` + `os.replace`); content-agnostic (never calls the LLM). A code-level
  `FS_WRITE_HARD_DISABLE` kill switch forces dry-run regardless of config.
- **Toggleable RAG-corpus indexing** of the share (`index_enabled`, dry-run
  default) stages eligible files into the corpus and triggers a reindex
  **subprocess** — a generate → write → index loop without importing retrieval.

```bash
python -m agentic.fsconnect.cli status
python -m agentic.fsconnect.cli read  --path "<path>"                     # scoped read
python -m agentic.fsconnect.cli grep  --path "<path>" --pattern "<pattern>"
python -m agentic.fsconnect.cli largest --path "<dir>" --top 20 --min-bytes 1048576
python -m agentic.fsconnect.cli write --path "<path>" --reason "..."      # dry-run unless writes_enabled
python -m agentic.fsconnect.cli index --apply           # stage share → corpus
python -m agentic.fsconnect.cli test                    # pre-flight self-test
```

Enable in `config.yaml`:

```yaml
fsconnect:
  enabled: true
  allowed_roots: ["/srv/share"]   # REQUIRED when enabled; existing dirs
  max_file_bytes: 5242880         # 5 MiB read cap
  largest_max_entries: 100000     # truthful traversal ceiling per largest command
  writes_enabled: false           # master write switch (dry-run plans while false)
  writable_roots: [null]          # null => ~/CyClaw-FS (macOS) | /var/lib/cyclaw-fs (Linux) | C:\CyClaw-FS
  max_write_bytes: 10485760       # 10 MiB write cap
  index_enabled: false            # toggle RAG-corpus indexing of the share
```

### `agentic/sqlconnect/` — read-only SQL connector (v0.1 scaffold)

Read-only on-prem SQL (Postgres / MSSQL), enforced three ways: a
**SELECT/WITH-only query guard** (rejects DDL/DML, stacked statements, and
comment-hidden keywords by scanning a quote-stripped copy), a **session-level
read-only** transaction, and a hard `allow_write: false`. The DSN comes from an
**environment variable only** (`CYCLAW_SQL_DSN`); drivers (`psycopg` / `pyodbc`)
import lazily. The quote-stripping scan is a single left-to-right pass that
gives `'...'`, `"..."`, `[...]`, and Postgres `$tag$...$tag$` quoting the same
precedence the database does — an earlier regex-alternation version could be
fooled by a quote nested inside a different quoting form (e.g. `$$'$$`) into
treating a stacked `DROP` as part of one `SELECT`; the other two layers were
never affected.

```bash
python -m agentic.sqlconnect.cli status
python -m agentic.sqlconnect.cli schema                 # list table schemas (read-only)
python -m agentic.sqlconnect.cli query --table public.users   # bounded preview
python -m agentic.sqlconnect.cli test
```

```yaml
sqlconnect:
  enabled: false
  driver: "postgres"             # "postgres" | "mssql"
  dsn_env: "CYCLAW_SQL_DSN"      # DSN from this env var only
  statement_timeout_ms: 5000
  max_rows: 1000
  allow_write: false             # reserved; v0.1 cannot write regardless
```

### `agentic/netconnect/` — passive LAN inventory (v0.1 scaffold)

Reports best-effort local host metadata and reads the OS's existing
ARP/neighbor cache. No ping, port probe, subnet sweep, packet send,
scheduling, or request-path integration; every returned IPv4 address is
filtered through operator-supplied CIDRs that must be subnets of RFC1918 or
loopback space.

```bash
python -m agentic.netconnect.cli status
python -m agentic.netconnect.cli self
python -m agentic.netconnect.cli arp
python -m agentic.netconnect.cli test
```

```yaml
netconnect:
  enabled: false
  allowed_cidrs: ["192.168.1.0/24"]
  allowed_net_ops: [self, arp]
  command_timeout_sec: 5
  max_neighbors: 512
```

---

## NeMo Guardrails

An **opt-in** content-safety layer in `guardrails/` ([package README](guardrails/README.md)). Absence of the `guardrails:` block, or `enabled: false` (the shipped default), is a pure no-op. When enabled, `utils/guardrail_bridge.py` wires two visible `graph.py` nodes — `guardrail_input` (after `route_by_score`) and `guardrail_output` (after generation; grounding check on the **`local_llm` path only**) — still **defense-in-depth only, never a routing authority**: the graph's own edges decide where a blocked query goes. `gate.py` / `graph.py` / `mcp_hybrid_server.py` never import `guardrails` directly (I6). Status table: [`docs/NeMo/README.md`](docs/NeMo/README.md).

`nemoguardrails` is an **optional dependency**: the layer soft-imports it and,
when absent, degrades to offline heuristic rails that need no second LLM call —
an **input** rail (prompt-injection marker scan + soul/identity-mutation intent
detection, the content-layer arm of the Soul-Governance invariant) and an
**output** rail (token-overlap **grounding** check against the retrieved
context, flagging likely-hallucinated answers below `hallucination_threshold`).
When `nemoguardrails` **is** installed, the same Python checks back the live
NeMo actions via the Colang flows in `guardrails/config/rails.co`, so offline
heuristics and live rails never drift. Decisions go to a **separate** metrics
stream (`logs/guardrails.jsonl`) that stores only SHA-256 hashes.

```bash
python -m guardrails.cli status | check "your query here" | metrics | test
```

Config keys (`guardrails.enabled`, `engine`, `model`, `hallucination_threshold`,
`metrics_path`) and their shipped values live in `config.yaml`; the status
table, phased history, and rail semantics are in
[`docs/NeMo/README.md`](docs/NeMo/README.md).

---

## Agentic Coding Loop (GitHub)

The real-repo coding pipeline: **clone → plan → patch → verify → human decides →
commit**, with pushing and opening a draft PR as two further, separate decisions.
Driven by `agentic/real_repo_loop.py`, which fuses three previously-independent
pieces — the planner's model call, a jailed real clone
(`agentic/deepagent_github/repo_workspace.py`), and the sandboxed verification
executor (`agentic/executor/`). Out-of-band like every other agentic feature:
never imported by `gate.py`, `graph.py`, or `mcp_hybrid_server.py` (invariant I6).

**It ships held, not disarmed.** The three switches that gate whether a run
happens at all — `agentic.enabled`, `deepagent_github.enabled`,
`allow_git_write_tools` — ship `false`. The write-path constant
`agentic/writer.py::EXECUTION_ENABLED` and the cloud switches (`mode: "write"`,
`writes_enabled`, `allow_cloud_providers`, both providers) ship **open** since
the signed enablement of 2026-08-07, so on a default checkout it is the master
switches plus a per-call `reason`/`confirm` that refuse (see "already armed,
waiting on the master switches" below).

**What sits beside it.** `agentic/deepagent_github/` also carries the pieces the
loop actually calls — `repo_workspace.py` (the jailed clone: clone, read,
write_file, commit, push) and `chat_client.py` (the cloud-provider planner
adapter). Its `builder.py` DeepAgents subgraph and the
`agentic/harness_optimizer/` train/holdout scaffold beside it are **retired by
owner decision (2026-07-31)** — kept and tested, not deleted, and superseded by
the pipeline described here. Every switch below the `agentic.enabled` master
(`deepagent_github.enabled`, `allow_deepagents_dependency`,
`allow_filesystem_write_tools`, `allow_shell_execution`, `allow_github_writes`,
`harness_optimizer.enabled`) ships `false`, so nothing under either package is
reachable from `agentic.cli` and no `deepagents` / `langchain` optional
dependency is imported. The phase ledger is in
[`docs/work/GITHUB_DEEP_AGENT_HARNESS_OPTIMIZER_PLAN.md`](docs/work/GITHUB_DEEP_AGENT_HARNESS_OPTIMIZER_PLAN.md).

### How a run works

0. **`real-repo-run-plan`** (optional, two-stage) asks a model for a plan and
   prints it — clones, writes, and commits nothing. You read and edit the plan
   and feed it back with `--plan-file`, so one model plans, a **human
   approves**, and another model codes against the approved text. The plan is
   injection-scanned on load, truncated at 6,000 chars, and its SHA-256 is
   recorded on the run.
1. **`real-repo-run`** clones the configured repo into a jailed workspace, asks
   the planner for whole-file replacements, writes them, runs the selected
   checks, and **stops before committing** (`status: pending_decision`; a run
   that never passes reports `exhausted`).
2. **`real-repo-run-decide --decision approve`** commits locally; `reject`
   discards. Neither pushes.
3. **`real-repo-run-push`** puts the `claude/*` branch on origin.
4. **`real-repo-run-publish`** opens a **draft** PR (`gh pr create --draft`).
5. **`real-repo-run-discard`** reclaims a decided or orphaned run's clone
   (`reject` and `exhausted` free theirs immediately; only an approved run keeps
   its clone, since push and publish still need it).

Each escalation is its own command and its own decision, deliberately not
folded into `approve`.

### Security posture

- **Diff-scope gate.** A candidate that writes into any of `config.yaml`'s
  `agentic.deepagent_github.protected_write_paths` (the tests, CI, lint, and
  config files that judge the candidate's own acceptance — the classic
  reward-hacking failure of a make-the-checks-pass loop) is refused outright,
  and writes are budget-capped (`max_write_budget_bytes`).
- **Two scanners, two questions, on the same bytes.** Proposed content gets an
  injection scan (*is this trying to talk to a model?*) **and** a code-shape
  scan (`inspect_code_shape`; `scan_code_shape` ships `true`) that matches
  *combinations* — a secret path plus network egress, a decode plus dynamic
  exec, a socket plus fd-dup or a shell path, a pipe-to-shell — because a
  working key-exfiltration payload contains no injection phrase at all. Every
  hit is CRITICAL and refuses the candidate.
- **Verification runs as argv-list subprocesses**, never a shell: `cwd` pinned
  to the clone, a scrubbed env allowlist (`PATH`, `LANG`, `LC_ALL`,
  `PYTHONPATH`, `VIRTUAL_ENV`, `PYTHONIOENCODING`) plus a disposable
  `HOME`/`USERPROFILE`, forced `NO_PROXY=*` / `PIP_NO_INDEX=1`, and a 120s
  per-check timeout. **Every non-empty check list runs inside a required,
  fail-closed hard sandbox** (`hard_sandbox.py`: Windows Job Object with
  `KILL_ON_JOB_CLOSE`, Darwin `sandbox-exec` denying network and off-cwd
  writes, Linux `unshare --net`) — a missing binary or failed capability probe
  raises `HardSandboxUnavailable`, with no silent fallback. Residual limits (no
  microVM; Windows is a process-tree kill, so sockets keep working there) are
  in `docs/THREAT_MODEL.md`'s executor amendments.
- **`push_branch` passes no credential.** Its env allowlist deliberately
  excludes `GH_TOKEN`/`GITHUB_TOKEN` because that environment is shared with
  the executor; it authenticates only via a HOME-resident credential helper
  (`gh auth setup-git`). Branch names are forced into the PR-template vendor
  namespaces (`utils/agent_identity.py`) and `run_id` is validated as 32-char
  lowercase hex before it can become an argv element.
- **Optional offline slop-detection nudge** (`unslop.enabled`, ships `false`):
  hits become feedback appended to the next planning prompt, never a gate.

### Enable it

The block below is what `config.yaml` ships. The three switches that gate
whether a run happens at all — `agentic.enabled`, `deepagent_github.enabled`,
`allow_git_write_tools` — ship `false`; the three cloud switches ship **`true`**,
armed alongside `models.grok` / `models.claude` on 2026-08-07
(`docs/THREAT_MODEL.md`'s eighth amendment). Read it as "already armed, waiting
on the master switches," not as "off": reaching a cloud provider still needs
the two masters, the provider's API-key env var, and a per-run `--confirm-online`.

```yaml
agentic:
  enabled: false                        # master switch -- ships closed
  deepagent_github:
    enabled: false                      # ships closed
    allow_git_write_tools: false        # gates every write/commit/push in the clone
    model: "qwen3.8:27b-mlx"                # local planner model; cite models.local_llm.model
    workspace_root: "data/agentic/workspaces"
    max_write_budget_bytes: 100000
    max_handoff_chars: 200000           # outbound-prompt cap for cloud egress
    planner_max_tokens: 3072             # real-repo completion cap; keep it within Ollama num_ctx
    allow_cloud_providers: true         # gate 3 of the cloud chain -- ARMED
    providers:
      grok:   { enabled: true, model: "grok-4.5" }        # ARMED
      claude: { enabled: true, model: "claude-sonnet-5" } # ARMED
```

Setting a provider `enabled: true` while `allow_cloud_providers` is `false` is a
config error, not a silent no-op — the three move together. Opening a PR needs
`agentic.mode: "write"`, `writes_enabled: true`, and `agentic/writer.py`'s
`EXECUTION_ENABLED` (all ship open) **and** `agentic.enabled: true` plus a
per-call `reason` and `confirm`; the arming checklist and the
`CYCLAW_AGENTIC_WRITE_DISABLE` rollback are in
[`docs/agentic/GITHUB_WRITE_ENABLEMENT.md`](docs/agentic/GITHUB_WRITE_ENABLEMENT.md).

### Commands

```bash
# Optional stage 0: plan, review by hand, then hand the approved text to the coder.
python -m agentic.cli real-repo-run-plan \
  --pr 123 --instruction "fix the off-by-one in the parser" --out plan.md

python -m agentic.cli real-repo-run \
  --pr 123 --instruction "fix the off-by-one in the parser" \
  --read-file src/parser.py --checks-file checks.json \
  --plan-file plan.md \
  --branch claude/parser-fix --commit-message "fix: off-by-one" \
  --reason "triage issue 123" --confirm

python -m agentic.cli real-repo-run-status  --run-id "<32-hex>"
python -m agentic.cli real-repo-run-decide  --run-id "<32-hex>" --decision approve
python -m agentic.cli real-repo-run-push    --run-id "<32-hex>"
python -m agentic.cli real-repo-run-publish --run-id "<32-hex>" --reason "..." --confirm
python -m agentic.cli real-repo-run-discard --run-id "<32-hex>"
```

Exit codes are an API: `0` ok · `2` failed · `3` env/config · `4` write refused.
`real-repo-run` exits `0` whether or not a candidate was accepted — the record's
`status` field carries that.


### Optional cloud planner (Grok / Claude)

The loop is local-only by default, and the local path (no `--provider` flag)
needs nothing beyond the base install — `LocalProposerClient` is a plain
`httpx` call and nothing on that path imports `deepagents` or `langchain`.
`--provider grok|claude --confirm-online` drives the loop with a cloud model
behind a **six-condition chain**: `agentic.enabled` →
`deepagent_github.enabled` → `allow_cloud_providers` → `providers.<name>.enabled`
→ the provider's API-key env var (`GROK_API_KEY` / `ANTHROPIC_API_KEY`, presence
only, never a network probe) → per-run `--confirm-online`. Every outbound prompt
is injection-scanned, redacted, hashed, and audited as egress before it leaves
the process.

Cloud SDKs are **opt-in extras, deliberately absent from the default install,
`requirements.txt`, and the Docker image**:

```bash
pip install -e ".[agentic-deepagents]"                          -c constraints.txt   # Claude only
pip install -e ".[agentic-deepagents-cloud]"                    -c constraints.txt   # Grok only — just langchain-xai
pip install -e ".[agentic-deepagents,agentic-deepagents-cloud]" -c constraints.txt   # both
```

`full` (what CI and dev boxes get) pulls `agentic-deepagents` but deliberately
not `agentic-deepagents-cloud`, so a machine that never touches Grok never
carries `langchain-xai`; `[all]` is the only extra that installs both. The
published Docker image installs `requirements.txt` only, so running this
feature in a container means installing on top (`pip install -e .` for local
mode, or one of the commands above for cloud).

---

## Telegram Channel

CyClaw includes an **optional, out-of-band** Telegram channel (`telegram/`,
shipped `enabled: false`) that gives the single trusted operator a
phone-reachable remote — outbound notifications and, when configured,
allowlisted two-way chat — without touching `gate.py`, `graph.py`, or the MCP
request path (invariant I6). Inbound chat text only ever reaches the RAG
pipeline via loopback `POST /query`, never a direct call into `graph.py`.

Outbound notify (`mode: "notify"`) or long-poll two-way chat (`mode: "chat"`,
the shipped YAML, still `enabled: false`; long-poll only, no public webhook
listener beside the loopback server; T1-first remains the recommended enable
order). `allowed_chat_ids` is required non-empty when enabled, and the bot
token comes only from the env var named by `bot_token_env`
(`TELEGRAM_BOT_TOKEN`), never from YAML. T3 hybrid-confirm consent
(`allow_hybrid_confirm: false` by default): the exact private-chat command
`/online on <grok|claude>` is the only way chat text can set
`user_confirmed_online`, for one next message only (`hybrid_confirm_ttl_sec`,
hard-capped at 300s) — core's triple gate remains the final authority. T4 media
staging (`media.enabled: false`) accepts private-chat attachments captioned
`/save --confirm <reason>` only through the existing `agentic/fsconnect` write
path. The `poll-plist` / `health-plist` generators never load, and their
secrets are injected at process start by the Keychain wrapper (see
[macOS launchd & Keychain](#macos-launchd--keychain)).

**Core commands**

```bash
python -m telegram.cli status
python -m telegram.cli test
python -m telegram.cli send --chat-id "<id>" --text "..."   # T1; add --dry-run to preview
python -m telegram.cli poll                                # T2; requires telegram.mode: chat
python -m telegram.cli poll-plist                          # Darwin-only; generates, never loads
python -m telegram.cli health-plist                        # Darwin-only; generates, never loads
```

See [`docs/channels/TELEGRAM_DESIGN.md`](docs/channels/TELEGRAM_DESIGN.md) for
architecture, the T0–T4 phase ledger, and the threat-model obligations
(`docs/THREAT_MODEL.md`'s seventh amendment), and
[`telegram/README.md`](telegram/README.md) for package internals.

---

## OpenTweet Channel

Optional out-of-band X poster (`opentweet/`, shipped `enabled: false`).
`gate.py`, `graph.py`, and the MCP server never import it (invariant I6).
Generation is loopback `POST /query` with `user_confirmed_online: false`.
The default write is an OpenTweet **draft**; `scheduled_date` is opt-in via
`opentweet.schedule_enabled`. Schedulers never send `publish_now`.

**Core commands**

```bash
python -m opentweet.cli status
python -m opentweet.cli test
python -m opentweet.cli post --topic "..."          # add --dry-run to preview
python -m opentweet.cli schedule-plist              # Darwin; generates, never loads
python -m opentweet.cli schedule-task               # Windows; generates, never registers
```

See [`docs/channels/OPENTWEET_DESIGN.md`](docs/channels/OPENTWEET_DESIGN.md)
and [`opentweet/README.md`](opentweet/README.md). Keychain/CredMan wrappers
are in [`macos/README.md`](macos/README.md) and
[`powershell/README.md`](powershell/README.md).

---

## Security Model

| Layer | Mechanism |
|---|---|
| Network | Binds `127.0.0.1:8787` — no external exposure by design |
| Endpoint trust | `utils/endpoint_trust.py` allowlists where a generation client may talk, checked in `graph.py` itself. The local nodes accept loopback or an exact host from `models.local_llm.trusted_hosts` (ships `[]`) before any local context or soul text leaves the process; the online nodes pin Grok to `api.x.ai` and Claude to `api.anthropic.com`, so a tampered `base_url` cannot redirect a confirmed call, and an explicit `user_confirmed_online: false` is refused a second time here as a backstop to the triple gate. Denials surface as a typed `ENDPOINT_TRUST` error |
| Input | Config-driven injection filter (`policy.prompt_filter`) |
| Rate limit | 60 req/min per IP |
| Proxy bypass | All `httpx` clients set `trust_env=False` — ambient `HTTP(S)_PROXY`/`.netrc` cannot reroute local traffic, see the path-embedded Telegram bot token, or carry `GROK_API_KEY` / `ANTHROPIC_API_KEY` on a confirmed hybrid call (`utils/health.py`, `llm/client.py` local + Grok + Claude, `telegram/client.py`, `opentweet/client.py`). This reverses the old “operator proxy governs paid egress” exception. |
| Telemetry | Canonical kill maps (`utils/telemetry_kill.py`: telemetry + a visibly-separate update-check map, plus a removed-outright scrub set incl. the declarative-OTel config names) applied before any SDK import by every maintained Python chokepoint (invariant-guard G1 pins 14 orderings) AND delivered as literal environment before the interpreter starts at every process boundary — Docker ENV, the shipped launchers, generated launchd plists / Windows tasks / cron lines, and verifier/`gh` children via `build_telemetry_safe_env`; ONNX Runtime additionally gets the post-import `disable_telemetry_events()` call at its load seams (`utils/onnx_telemetry.py`). HF Hub network calls are also cut off once the embedding model is confirmed cached (`retrieval/embeddings.py`). Not a network kill switch: intentional policy-gated egress is classified separately in [SECURITY.md](SECURITY.md) |
| Audit | All paths log SHA-256 query hash + PII-redacted metadata |
| Grok gating | Triple gate: `mode=hybrid` AND `grok.enabled=true` AND `user_confirmed_online=true` |
| Claude gating | Same triple gate, independently: `mode=hybrid` AND `claude.enabled=true` AND `user_confirmed_online=true` |
| Soul writes | Explicit human reason string + enforced write-boundary scan + atomic write |
| Agentic writes | `pr_create` implemented; the source constant and two config gates ship open since 2026-08-07, so `agentic.enabled` (ships `false`) plus per-call reason/confirm is what refuses. `pr_comment`/`issue_comment` remain plan-only. Git-level writes (real-repo commit/push and draft-PR publish) are additionally gated on `deepagent_github.allow_git_write_tools`, which ships `false` |
| Filesystem connector | Reads scoped to `allowed_roots` (5 MiB cap) with POSIX held-fd descent and Windows same-handle containment; writes default-OFF and hard-refused on Windows, otherwise confined to separate `writable_roots`, gated by human `reason` + `--confirm`, and atomic; UNC/ADS/device-path/`..`/symlink escapes are denied |
| SQL connector | Read-only: SELECT/WITH-only query guard + session read-only + hard `allow_write: false`; DSN from env var only; disabled scaffold by default |
| Network connector | Passive only and disabled by default; explicit RFC1918/loopback CIDRs; `self` plus existing OS neighbor-cache reads; no ping, sweep, port probe, packet send, scheduler, or `/ops` route |
| Guardrails | Out-of-band, opt-in defense-in-depth; degrades to offline heuristic rails without `nemoguardrails`; never a routing authority; separate hash-only metrics stream |
| Telegram channel | Out-of-band, ships `enabled: false`; non-empty `allowed_chat_ids` allowlist required to arm; inbound chat reaches the pipeline only via loopback `POST /query` (never a direct `graph.py` call); T3 hybrid-confirm consent (`allow_hybrid_confirm`) ships off — only an explicit `/online on <grok|claude>` grants one TTL-capped per-request consent; T4 media staging off and confined to the fsconnect write path |
| OpenTweet channel | Out-of-band, ships `enabled: false`; answers only via loopback `POST /query` with `user_confirmed_online: false`; default write is a draft; schedulers generate-don't-load and never send `publish_now`; API key from env / Keychain / CredMan, never YAML or a plist `EnvironmentVariables` dict |
| launchd secrets (macOS) | Generated plists never embed tokens — `macos/cyclaw-keychain-env.sh` injects secrets from the macOS Keychain at exec time and fails closed when the item is missing; `cyclaw-keychain-set.sh` stores them via a no-echo `security` prompt so the secret never appears in argv or the plist; the supervised-service generator (`macos/generate_service_plist.py --service gate`, `windows/generate_service_task.py`) additionally requires `--confirm` + a non-empty `--reason` |
| `/ops/*` routes | Loopback-only, `require_api_key` gated, rate-limited (60/min), every call audited (`ops_sync_executed` / `ops_agentic_executed` / `ops_fsconnect_executed` / `ops_sqlconnect_executed`); shells out via `subprocess.run([...])` — never imports `sync/` or `agentic/` |
| `/auth/*` routes | Per-user auth design (`gate_auth.py`, `docs/AUTHENTICATION_DESIGN.md`); first-boot `GET /auth/setup-status` (no credential; same-origin-checked) and loopback-only `POST /auth/bootstrap-password`; session cookie + CSRF for browsers, bearer device tokens for programmatic clients; three roles (`admin`/`operator`/`audit`) gate the `/auth/users*` admin surface, with the last enabled `admin` protected from disable/delete/role-change; every `/auth/*` handler checks `auth.enabled` first and returns 503 (not 404) so route presence never discloses whether the feature is on. When `auth.enabled` is true, `POST /query` requires a session or named device token |
| `/memory/*` + `/query/export/html` routes | Optional, default-off memory admin surface (`gate_memory.py`); every `memory:` switch ships `false`; `require_api_key` gated, rate-limited; mutating routes (`propose`/`apply`/`reject`) require a non-empty `reason` string, with an injection scan on `apply` |
| Container | Non-root, `no-new-privileges`, `cap_drop: ALL`, read-only rootfs, seccomp, resource limits; optional eBPF/Falco detection (`deploy/falco/`, off by default) |

> **Docker / GHCR:** published runtime image `ghcr.io/cgfixit/cyclaw` (tag-triggered). Operator guide, pull/run commands, Falco opt-in notes, and explicit non-goals (no microVM): [`docs/DOCKER.md`](docs/DOCKER.md). Host publish remains `127.0.0.1` only.

> **Scope:** CyClaw is a trusted-operator, loopback-bound local server — one operator by default, a small set of mutually trusted operators with their own accounts and roles once `auth.enabled` is on, and single-tenant either way (everyone reaches the same corpus, soul, and model). LAN or WAN exposure is possible only through the threat model's documented bind exceptions (auth + TLS), never by default. The full threat model — what the sandbox does and does **not** cover (no microVM by design) and why — is documented in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md). The underlying design philosophy (telemetry kill, offline-first posture) lives in [`docs/security-philosophy/`](docs/security-philosophy/).

---

*designed and built by Chris Grady, with AI tooling used under human review / CI / invariant-guard*

*source-available - all rights reserved*
