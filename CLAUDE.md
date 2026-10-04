# CLAUDE.md — CyClaw Operating Manual

This is the operating contract for every agent working in this repository. It is
written to be followed literally. Where a rule gives a number, use that number.
Where it says "never," there is no exception without explicit user approval.
Read it fully before acting. It **overrides** your default behavior.

---

## 1. Read Me First

**What CyClaw is.** A Python 3.12 FastAPI RAG server (`gate.py`) fronting a
LangGraph security topology (`graph.py`), with hybrid ChromaDB + BM25 retrieval,
a local LLM via Ollama, and triple-gated optional external fallbacks (Grok
and/or Claude, selected per-query via `online_provider`). It binds
**only** to `127.0.0.1:8787`. A separate retrieval-only MCP server
(`mcp_hybrid_server.py`) exposes search with no LLM path.

**Critical Python coding requirement.** Never use a docstring as a multi-line
comment except at the top of a Python file or a function definition. Anywhere
else, write multi-line comments with `#` at the start of each line.

**Where truth lives.** In priority order:
1. **Code** — the running behavior. When docs and code disagree, code wins.
2. **`config.yaml`** — the single source of truth for every tunable. No
   hardcoded tunables anywhere else.
3. **`docs/THREAT_MODEL.md`** — the security scope: trusted-operator (one
   by default, a small mutually trusted set behind `auth.enabled`),
   loopback-bound, single-tenant. Multi-operator is not multi-tenant (fifteenth
   amendment); not a sandbox for untrusted code. Read it before touching
   anything security-related.
4. This file and `.claude/rules/PROJECT_RULES.md` — the operating rules.
   `AGENTS.md` is the parallel guidance for other agents; keep them consistent.
5. `README.md` for the holistic view of the codebase; `docs/changelog.txt` for
   changes over time.

---

## 2. The Map

### Request flow

```
HTTP POST /query   (or MCP tools/call: hybrid_search)
        │
        ▼
   gate.py  — TrustedHost check → rate limit (60/min per IP) → injection filter
              → soul init → graph invoke (wrapped in 780s timeout)
        │
        ▼
   graph.py  (LangGraph 12-node state machine)
   retrieve → route_by_score
              ├─ best cosine ≥ min_semantic_score (RRF ≥ min_score if no cosine)
              │  AND, when models.reranker is on and min_rerank_score is set,
              │  best cross-encoder logit ≥ min_rerank_score (a veto: it only
              │  turns a hit into a miss; shipped null = shadow, audited only)
              │                       → guardrail_input (offline input rail; default on,
              │                       pass-through when guardrails.enabled=false)
              │                       ├─ blocked → audit_logger
              │                       └─ passed  → local_llm
              └─ else → user_gate
                                     ├─ confirmed + hybrid + selected provider usable
                                     │    → pre_action_hook_<provider> → grok_fallback |
                                     │      claude_fallback (NOT railed by guardrail_input —
                                     │      their gate is the triple gate; the pre-action hook
                                     │      can only shrink this reachable space, not expand
                                     │      it. The broker wraps the call with NeMo check(),
                                     │      or deterministic input/output checks on degradation.
                                     │      Both can only deny; grounding stays local-only)
                                     └─ declined / offline / no key → guardrail_input
                                            ├─ blocked → audit_logger
                                            └─ passed  → offline_best_effort
              ↓ (all four answer nodes converge)
              guardrail_output (offline output rail; default on, pass-through when
                                 guardrails.enabled=false; grounding check applies
                                 only to the local_llm answer, see Phase 4)
              ↓
              audit_logger → END
        │
        ▼
   HybridRetriever — ChromaDB (semantic) + BM25Okapi (keyword) → RRF fusion (k=60)
```

`retrieve` is the unconditional first node. Routing is graph edges, never an LLM
decision.

### All HTTP routes (gate.py)

| Method | Route | Auth | Notes |
|---|---|---|---|
| GET | `/` | none | serves `static/terminal.html` |
| GET | `/static/*` | none | static mount |
| POST | `/query` | **session or device token when `auth.enabled`**; **same-origin always** | rate-limited, sanitized; cross-site rejected (403 `CROSS_SITE_BLOCKED`) regardless of `auth.enabled`, and a request carrying neither `Origin` nor `Sec-Fetch-Site` is allowed; the `audit` role is denied (403 `AUTH_ROLE_DENIED`); 400/401/403/429/503/504/500. Unchanged (no credential) when auth is off |
| GET | `/health` | none | `degraded` without Ollama is NORMAL |
| POST | `/index/build` | **loopback peer + same-origin, no forwarding headers; plus API key once `CYCLAW_API_KEY` is set** | rate-limited; audited; starts a background index build; 403 off-box or when proxied; 401 `INDEX_BUILD_AUTH_REQUIRED` without a credential once the key is set; 409 while one is running. Not key-gated while the key is unset — that would fail closed and brick first-run |
| GET | `/index/status` | none | **not** rate-limited (the console polls it every 1.5s for the length of a build — 40 of the 60/min budget; same posture as `/health`); always 200 + `{state, elapsed_sec, chunks_done, chunks_total, error, index_ready}` |
| GET | `/soul` | **API key** | rate-limited |
| POST | `/soul/propose` | **API key** | advisory scan, never writes |
| POST | `/soul/apply` | **API key** | enforced scan + atomic write; requires `reason` |
| POST | `/soul/reload` | **API key** | |
| POST | `/soul/restore` | **API key** | from `.bak` |
| GET | `/audit/summary` | **API key** | rate-limited; aggregates only, no raw queries |
| GET | `/console/session` | none (same-origin) | rate-limited; whether this browser can use the API-key routes and how (`via`: `console_key`/`admin_session`/`api_key_optional`), plus the console CSRF token after a reload; cross-site 403 |
| POST | `/console/session` | **Bearer key or one-time pairing code** | rate-limited, same-origin, audited; sets the HttpOnly audience-bound console cookie (`__Host-cyclaw_console` under TLS) that satisfies `require_api_key` (`utils/console_session.py`); 401 when `CYCLAW_API_KEY` is unset |
| POST | `/console/session/end` | none (same-origin) | rate-limited, audited; deletes this browser's console cookie (cannot revoke a copy elsewhere: rotate the key for that) |
| POST | `/ops/sync` | **API key** | rate-limited; subprocess shim |
| POST | `/ops/agentic` | **API key** | rate-limited; subprocess shim |
| POST | `/ops/fsconnect` | **API key** | rate-limited; subprocess shim |
| POST | `/ops/sqlconnect` | **API key** | rate-limited; subprocess shim |
| GET | `/auth/setup-status` | same-origin (curl/MCP with no Origin still allowed) | rate-limited; `{enabled, needs_password, username}` when the bootstrap admin still has no password; 503 when `auth.enabled` is false |
| POST | `/auth/bootstrap-password` | loopback peer, no forwarding headers | first admin password; same-origin; 403 off-box or when proxied; 409 once set; 503 when auth off |
| POST | `/auth/login` | none | cross-site rejection precedes rate limiting; bounded password workers; session cookie + CSRF token on success; 503 when `auth.enabled` is false |
| POST | `/auth/logout` | **session cookie + CSRF** | rate-limited; 503 when `auth.enabled` is false |
| GET | `/auth/whoami` | **session cookie or bearer token** | rate-limited; returns `username` + `role`; 503 when `auth.enabled` is false |
| GET | `/auth/users` | **session; admin or operator** | list users, no hashes; 503 when auth off |
| POST | `/auth/users` | **session+CSRF or admin bearer** | create user; operator cannot create admin |
| POST | `/auth/password` | **session+CSRF or admin bearer** | self-service password change requires `current_password` plus the new `password`; revokes existing sessions |
| POST | `/auth/users/{username}/password` | **session+CSRF or admin bearer** | reset password; operator cannot touch admins |
| POST | `/auth/users/{username}/role` | **admin only** | set role; last-admin protected |
| POST | `/auth/users/{username}/disable` `/auth/users/{username}/enable` | **admin; operator on non-admins** | last-admin protected |
| DELETE | `/auth/users/{username}` | **admin only** | hard delete after revoke; last-admin protected |
| GET | `/auth/audit/summary` | **session; admin or audit** | reduced audit view; not the ops API key |
| GET | `/memory/status` | **API key** | rate-limited; always 200 + flags (default-off memory) |
| GET | `/memory/facts` | **API key** | rate-limited; 404 when `memory.enabled` is false |
| GET | `/memory/episodes` | **API key** | rate-limited; 404 when `memory.enabled` is false |
| GET | `/memory/proposals` | **API key** | rate-limited; 404 when propose/apply off |
| POST | `/memory/propose` | **API key** | rate-limited; requires non-empty `reason` |
| POST | `/memory/apply` | **API key** | rate-limited; reason + injection scan on apply |
| POST | `/memory/reject` | **API key** | rate-limited; requires non-empty `reason` |
| GET | `/query/export/html` | **API key** | rate-limited; 404 when `export_html.enabled` is false |

The four `/ops/*` endpoints reach out-of-band subsystems ONLY through
`utils/ops_runner.py` (a `subprocess.run([...])` shim). They never import those
subsystems.

Every route marked **API key** is gated by `gate.py`'s `require_api_key`;
unset `CYCLAW_API_KEY` fails closed (401). `security.api_key_optional` (ships
`false`) is the one deliberate bypass, and `_api_key_bypass_allowed` grants it
only when **all four** hold: the flag is set, the **socket peer is loopback**,
**no reverse-proxy forwarding header** is present, and the request is **not
cross-site**. Each condition closes a hole the previous ones left, so never
collapse it to "loopback" alone; it is keyed on the peer, never the `Host`
header or `security.allowed_hosts`/`allowed_origins`. A remote caller always
needs the real key, including under `uvicorn gate:app --host 0.0.0.0` (the
container `CMD`, no bind guard). Defence in depth: `_require_loopback_bind`
refuses a non-loopback `api.host` while the flag is `true` (config-guard C13
warns on the pair); `CYCLAW_ALLOW_NON_LOOPBACK_BIND` outranks the bind guard,
never the peer check. Under Docker NAT the peer is the bridge gateway, so set
`CYCLAW_API_KEY` in the container. The full contract and its tests are
`INVARIANTS.md` Rule 6.

The bypass never touches the session/RBAC `/auth/*` system
(`gate_auth.py`, `docs/AUTHENTICATION_DESIGN.md`), which `auth.enabled`
governs alone. Every `/auth/*` handler exists regardless of the flag and
answers 503 (not 404) when it is off, so a route's presence never discloses
the feature. When `auth.enabled` is the literal boolean `true`, Stage 3
attaches `require_session_or_token` to `POST /query` (session cookie or named
device token, no CSRF); the shipped default leaves `/query` unauthenticated.

**Credentials, not bypasses.** Besides Bearer `CYCLAW_API_KEY`,
`require_api_key` accepts two cookies, each refused cross-site and each needing
its CSRF token on a write (a bad token is a 403, never a fall-through): the
console cookie `cyclaw_console` (`POST /console/session` mints it for the key
or a launcher's one-time pairing code; a stateless HMAC keyed off
`CYCLAW_API_KEY`, so it validates nothing while the key is unset and rotating
the key revokes all; header `X-CyClaw-Console-CSRF`), and, with
`auth.enabled`, an **enabled admin**'s login (`X-CyClaw-CSRF`), the one
credential that works with the key unset; `operator`/`audit` never pass. The
console no longer keeps the key in the page, and the daily launchers generate a
missing key into the OS keystore (`gate.py` never does). See
`docs/THREAT_MODEL.md` (eighteenth amendment) and `INVARIANTS.md` Rule 6.

The `/memory/*` and `/query/export/html` routes are the optional memory
subsystem (`gate_memory.py` + `memory/`, `docs/memory/IMPLEMENTATION_PLAN.md`).
Every `memory:` switch ships **false**: handlers 404 (or 200 + `enabled: false`
for `/memory/status`). Mutations need the API key and a non-empty `reason`,
with an injection scan on apply (parallel to soul I5).

### Key modules

Module docstrings are the detailed reference; this table is the index.

| Path | Role |
|---|---|
| `gate.py` | FastAPI entry, auth, rate limit, sanitizer, security headers, telemetry kill |
| `utils/telemetry_kill.py` | Canonical maps: `TELEMETRY_KILL` (21 pairs), separate `UPDATE_CHECK_OPT_OUT` (4), `SCRUBBED_ENV_KEYS` (5 tracing credentials/endpoints + 2 declarative-OTel config names, removed outright); `apply_telemetry_kill()`, `build_telemetry_safe_env(base)`, `scheduler_env_overlay()`, and `python -m utils.telemetry_kill --export {shell,powershell}`. Applied at import by every chokepoint (invariant-guard G1 pins 14 orderings). Stdlib-only; deliberately excludes `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` (§4) |
| `utils/onnx_telemetry.py` | `suppress_onnx_telemetry()`: post-import `disable_telemetry_events()`, idempotent and absent-safe, called at `retrieval/vector_store.py` and `guardrails/integration.py`. The env half (`ORT_DISABLE_TELEMETRY=1`) rides the kill map |
| `gate_ops.py` | The four `/ops/*` endpoints, registered onto gate.py's app with its auth/rate-limit/audit callables injected; never imports `sync`/`agentic` |
| `gate_auth.py` | The `/auth/*` endpoint set (login/logout/whoami + RBAC/admin), registered like `gate_ops.py`. Session cookie + CSRF for browsers, bearer device tokens for programs; Stage 3 attaches `require_session_or_token` to `/query` by name (`_AUTH_DEPENDENCY_NAME`) only when `auth_manager` is not None |
| `gate_memory.py` | Default-off memory admin surface (`/memory/*` + `/query/export/html`), registered the same way; lazy-imports `memory` inside handlers only. See `docs/memory/README.md` |
| `memory/` | Optional facts + episodes SQLite+FTS5 store with propose/apply governance and optional retrieval fusion (all switches false) |
| `graph.py` | 12-node LangGraph topology; all security policy lives in the edges |
| `retrieval/hybrid_search.py` | RRF fusion (k=60) over ChromaDB + BM25. BM25 top-k is vectorized with numpy `argpartition` + stable sort when scores are finite, `heapq.nlargest` otherwise (#1491) — hence the direct numpy import (§4 numpy trap) |
| `retrieval/indexer.py` | Corpus ingestion, chunk sanitization (`cyclaw-index`) |
| `retrieval/embeddings.py` | Local embeddings, device hardcoded to CPU (`EMBED_DEVICE`, cross-platform determinism); triple `lru_cache`; `embedding_fingerprint()` for index staleness |
| `retrieval/rerank.py` | Local cross-encoder (`models.reranker`, shipped `cross-encoder/ms-marco-MiniLM-L6-v2`, CPU, raw logits) behind the vault-hit veto (#1456). `graph.retrieve_node` scores the `LOCAL_CONTEXT_CHUNKS` window; `route_by_score_node` compares the best logit to `retrieval.min_rerank_score` (shipped `null` = shadow, audited as `rerank_best`). Fail-soft (`rerank_degraded`); not called by `hybrid_search`, so MCP never pays for it. Loads under the embedder's offline rule (same `cache_dir`, `offline_after_index`, index probe) |
| `retrieval/stemmer.py` | Porter stemmer + custom vocab; avoids NLTK punkt (CVE) |
| `retrieval/vector_store.py` | Pluggable reader/writer: embedded ChromaDB (default) or pgvector |
| `retrieval/clear_cache.py` | Dry-run-by-default embedding-cache cleaner (`cyclaw-clear-cache`) |
| `llm/client.py` | `LocalLLMClient` + `GrokClient` + `ClaudeClient`; shared bounded-retry `_post_with_retry` honors `Retry-After` and caps every POST at the remaining `api.graph_timeout_sec` budget via the `set_graph_deadline` ContextVar (#1359) |
| `utils/sanitizer.py` | Injection filter; patterns in `config.yaml` |
| `utils/personality.py` | Soul versioning, SHA-256 drift detection, injection gate on write |
| `utils/personality_db.py` | Soul DB backend: SQLite default, Postgres via `CYCLAW_DB_URL` |
| `utils/logger.py` | Audit JSONL (written on the caller's thread, I4): keyed HMAC-SHA256 query fingerprints, recursive PII redaction, then a lazy fail-soft projection of the **already-redacted** record into the Numbat stream. The key comes from `CYCLAW_QUERY_FINGERPRINT_KEY` or the private persistent file configured at `policy.privacy.query_fingerprint_key_file`; ordinary `hash_query` SHA-256 remains for content-integrity identifiers. `setup_logging` writes the app log (and gateway console, `background_console=True`) from one bounded writer thread (`logging.max_queued_records`, `logging.drain_wait_sec`; full queue drops and counts); closed handlers reopen after uvicorn's `dictConfig` |
| `utils/numbat_emitter.py` | Derived NDJSON stream `logs/numbat-events.ndjsonl` (`numbat:` ships **enabled** — this file only; the pre-action hook and CEL monitor ship off, and nothing scores it at runtime, #1458). Action plane (`emit_numbat_event`/`emit_numbat_command` from `agentic/*`, `ops_runner`, hook verdicts, CEL) + mainline plane (`project_audit_record`); keep `_AUDIT_ACTION_PLANE_EVENTS` in step with the emit sites. Stdlib-only, never raises; one bounded writer thread (`numbat.write_wait_sec`, `numbat.max_queued_writes`) |
| `utils/ratelimit.py` | Per-IP rate limiting; in-memory / SQLite / Postgres |
| `utils/health.py` | `check_all()` behind `/health`. Probes Grok/Claude only when `api.health_probe_external_providers` (ships **false**) and the key is set. Concurrent calls share one in-flight probe set, snapshots cache 2 s (`_status_ttl_sec`, #1490); probe errors surface only as fixed strings (`_public_probe_error`, #1492) |
| `utils/errors.py` | Typed exception hierarchy rooted at `RAGError` |
| `utils/config_validation.py` | Boot-time config validation; fails fast |
| `utils/ops_runner.py` | Subprocess shim behind the four `/ops/*` endpoints |
| `utils/guardrail_bridge.py` | Builds the `guardrail_input`/`guardrail_output` callables and Phase 3 `generate_guard`, or `None` when disabled; the only path from `graph.py` to `guardrails/` |
| `utils/endpoint_trust.py` | Generation-client destination allowlist (`graph.py`, `utils/health.py`): `assert_local_destination` (loopback or `models.local_llm.trusted_hosts`, ships `[]`); `assert_online_destination` pins `api.x.ai`/`api.anthropic.com` and re-refuses `confirmed is False` — an I3 backstop, not a replacement. Denials are typed `ENDPOINT_TRUST:` errors |
| `utils/external_pre_hook.py` | Pre-action hook after the I3 gate allows a call (`policy.fallback.pre_action_hook`, ships off); deny-only. Engines `command` (JSON on stdin, exit 0 allow / 2 deny) or `numbat`. Enabled, anything but an explicit allow denies; each verdict carries a `reason_code` (audit `pre_action_hook_reason`). `verdict_mode` accepts only `enforce` (#1458) |
| `utils/numbat_gate.py` | The hook's `numbat` engine: a schema-0.3.0 `network.indicator` event through the pinned `numbat 0.2.0` CLI (`rules test --no-builtin-rules`, `numbat.rules_dirs`); an `enforce: true` match or any engine failure denies. Subprocess only. Guide: `docs/security-philosophy/numbat_pre_action_gate.md` |
| `utils/authn.py` | Auth primitives: scrypt hash/verify, lockout arithmetic, session/CSRF/device-token ids. Pure functions |
| `utils/authn_store.py` | SQLite/Postgres `users`/`sessions`/`device_tokens`; own `CYCLAW_AUTH_DB_URL`, not shared with `CYCLAW_DB_URL` |
| `utils/authn_manager.py` | `AuthManager`: bootstrap, login/logout, sessions, device tokens. No HTTP awareness |
| `utils/authn_cli.py` | `cyclaw-user` (`add`/`list`/`role`/`disable`/`enable`/`passwd`/`token …`), local-only by construction |
| `utils/console_session.py` | Console operator session: stateless HMAC cookie keyed off `CYCLAW_API_KEY`, minted by `POST /console/session` for the key or a launcher's one-time pairing code (`CYCLAW_CONSOLE_PAIRING_CODE`, popped at gate import, single-use), plus its CSRF token. Stdlib only; `require_api_key` is the only consumer |
| `utils/gen_cert.py` | `cyclaw-gen-cert` — openssl wrapper for a self-signed cert with hostname/LAN SAN |
| `schemas/api.py` | Pydantic models (`extra='forbid', strict=True`) |
| `metrics.py` | `cyclaw-metrics`: `audit.jsonl` analyzer, Spend section from `logs/spend.jsonl` (tokens as ground truth, no query text), offline Sequences section (`utils/sequence_detect.py`). Forensic only — not imported by the core six |
| `mcp_hybrid_server.py` | MCP server: `hybrid_search` only, no LLM, `sampling: None` |
| `sync/` | Out-of-band Dropbox corpus sync (`python -m sync.cli`) |
| `agentic/` | Out-of-band GitHub context + governed skills registry (`python -m agentic.cli`) |
| `agentic/fsconnect/` | Out-of-band local/SMB filesystem connector; POSIX held-fd core; macOS installer enables list/stat/read for `~/CyClaw-FS` only |
| `agentic/sqlconnect/` | Out-of-band SQL connector; SELECT/WITH-only guard |
| `agentic/netconnect/` | Out-of-band passive LAN inventory; explicit RFC1918/loopback CIDRs, no active probes |
| `agentic/real_repo_loop.py` | Plan → patch → verify → (human decides) → commit against a jailed clone. CLI-only (`real-repo-run*` subcommands; `OpsAgenticRequest.action` rejects them, so no HTTP route). `real-repo-run-plan` is the one-shot cloud-planner recipe; `--provider` means something different per subcommand (`docs/agentic/AGENTIC_README.md` §9). Push/PR gated (`allow_git_write_tools` and `agentic.enabled` ship false) — `docs/agentic/GITHUB_WRITE_ENABLEMENT.md` |
| `agentic/executor/` | Sandboxed verification of caller-declared checks in a jailed worktree with scrubbed env and per-check timeout, always through `hard_sandbox.production_sandbox()` (Windows Job Object, Darwin `sandbox-exec`, Linux `unshare --net`); a missing capability raises `HardSandboxUnavailable`, never a silent fallback (`run_verification`'s `sandbox=` is test-only). Not a kernel boundary (no microVM; Windows kills the process tree but keeps sockets) — see `docs/THREAT_MODEL.md` |
| `agentic/deepagent_github/` | Live: `RepoWorkspaceTools` (jailed clone/read/write/commit/push) and the cloud planner `real_repo_loop.py` uses. **Retired** 2026-07-31: `builder.py`'s DeepAgents subgraph (kept, not developed). Both gated off by default |
| `guardrails/` | Enabled by default, with required but soft-imported NeMo. Offline graph rails guard local input and output. The broker wraps every answer node with `check()`, or deterministic input and soul-leak checks on degradation. Grounding remains `local_llm` only. A refusal can also be audited as degraded. No LLM-backed rail is active |
| `telegram/` | Out-of-band Telegram channel (`python -m telegram.cli`), ships off. Inbound text reaches the RAG only via loopback `POST /query`; only `/online on <grok|claude>` (with `allow_hybrid_confirm`) can set `user_confirmed_online`. See `docs/channels/TELEGRAM_DESIGN.md` |
| `opentweet/` | Out-of-band OpenTweet X channel (`python -m opentweet.cli`), ships off. Generation is loopback `POST /query` with `user_confirmed_online: false`; default write is a draft. See `docs/channels/OPENTWEET_DESIGN.md` |

### Load-bearing numbers (all from `config.yaml`/`pyproject.toml` — do not invent)

| Value | Setting | Note |
|---|---|---|
| `127.0.0.1:8787` | `api.host`/`api.port` | loopback only, never a public interface |
| `0.028` | `retrieval.min_score` | **RRF scale**, not cosine. Gates only when no hit has a cosine (keyword-only degrade). Dual rank-0 ceiling is `2/60 ≈ 0.0333` |
| `0.30` | `retrieval.min_semantic_score` | Cosine floor on the **best** semantic hit; the vault-hit gate whenever cosines are present |
| `null` | `retrieval.min_rerank_score` | Shadow mode (logit audited, nothing vetoed). `0.0` was measured and rejected (PR #1463: it dropped 10 answerable questions); a five-model bake-off found no passing threshold (`docs/audits/2026-09-26-reranker-bakeoff.md`) |
| `60` | `retrieval.rrf_k` | RRF fusion constant |
| `780` | `api.graph_timeout_sec` | must exceed `local_llm.timeout_sec` (720) |
| `720` / `4096` | `local_llm.timeout_sec` / `max_tokens` | sized for dense ~27B MLX on M5 Pro class (307 GB/s, 48 GB). Decode tok/s is not config; measure with `scripts/measure_local_llm_throughput.py` |
| `8000` | `personality.soul_max_chars` | soul is capped |
| `16000` | `retrieval.max_context_tokens` | 16000+4096+~1500 = 21,596 ≤ Ollama num_ctx 32768 |
| `256` / `32` | `indexing.chunk_size` / `chunk_overlap` | **embedder tokens** (`chunk_unit: tokens`); 256 = all-MiniLM-L6-v2's `max_seq_length`, so every chunk embeds whole. Overlap `< chunk_size` |
| `60` per `60`s | `api.rate_limit` | per-IP |
| `40` | `banned_patterns` length | **documentary count**; the *phrases* are contractual (see §4) |
| `80` | `coverage fail_under` | in `pyproject.toml`, not `ci.yml` |
| `qwen3.8:27b-mlx` | `local_llm.model` | Ollama |
| `grok-4.5` | `grok.model` | `grok.enabled: true` since 2026-08-07 (`docs/THREAT_MODEL.md` eighth amendment); still triple-gated, `user_confirmed_online` is per-request |
| `claude-sonnet-5` | `claude.model` | `claude.enabled: true` since 2026-08-07 (same amendment); same triple gate |

---

## 3. The Six Invariants

Five are enforced by graph topology, the sixth by import structure — wiring,
not prompts. `python3 .claude/skills/invariant-guard/check_invariants.py`
verifies all six statically; run it after any change to the core files.

| # | Invariant | Enforced in | Locked by test | You violate it if you… |
|---|---|---|---|---|
| I1 | **RAG-first** — `retrieve` is the unconditional entry; no LLM call precedes retrieval | `graph.py` `set_entry_point("retrieve")` | `test_graph` | add a node/edge that answers before `retrieve` runs |
| I2 | **Topology = policy** — routing is graph edges only, never an LLM or ad-hoc `if` | `graph.py` `score_router`/`guardrail_router`/`user_gate_router`/`pre_action_hook_router` | `test_graph` | add a runtime branch that decides routing outside the four routers |
| I3 | **Triple-gated external fallback** — a call to Grok or Claude needs `mode=="hybrid"` AND `<provider>.enabled` AND `user_confirmed_online`, all three, for whichever provider is selected (`online_provider`) | `gate.py` construction + `graph.py` `user_gate_router` | `test_graph`, `test_gate` | route to `grok_fallback`/`claude_fallback` without all three conditions for that provider |
| I4 | **Audit convergence** — all eleven upstream paths reach `audit_logger` before END | `graph.py` edges | `test_graph` | add a node with a path to END that skips `audit_logger` |
| I5 | **Soul governance** — soul mutation requires a human `reason` string; writes are atomic | `utils/personality.py` `apply_evolution` | `test_personality` | write `soul.md` without a non-empty `reason`, or bypass `PersonalityManager` |
| I6 | **Module isolation** — `gate.py`/`gate_ops.py`/`gate_auth.py`/`gate_memory.py`/`graph.py`/`mcp_hybrid_server.py` never import `agentic`/`sync`/`guardrails`/`telegram`/`opentweet`, and those never import the core six | import graph | invariant-guard I6; `test_agentic_isolation` (AST, both directions) | `import agentic` (etc.) anywhere in the core six to "reuse" something |

Supporting guards (also checked by `invariant-guard`): telemetry-kill ordering
across 14 files (G1 — gate.py's `_TELEMETRY_KILL` anchor precedes its heavy
imports; each out-of-band package `__init__.py` — agentic, guardrails,
telegram, opentweet, sync — applies the kill before any other import; the eight
module-level appliers — MCP server, metrics, vector_store, indexer,
clear_cache, guardrails/integration, gen_cert, authn_cli — apply it before any
third-party import); unset `CYCLAW_API_KEY` fails **closed** (G2); the sanitizer contract
phrases stay caught (G3); BM25 stays JSON — pickle = RCE (G4); MCP declares
`sampling: None` (G5).

**Before touching `gate.py`, `soul.md` handling, or the scanner, read
`INVARIANTS.md`** (repo root). It records which guarantees are enforced by code
vs. by convention (two of the three external-provider gates live in `gate.py`
construction, not the graph; the soul injection scan is write-path-only), and
names the test that pins each. `tests/test_due_diligence_invariants.py` is the
regression harness.

## 4. Mistakes You Will Make Here (and the rule that prevents each)

Real traps in *this* codebase, verified against the code, each paired with the
rule that prevents it.

### Environment & install
- **Trap:** `pip install -r requirements.txt` fails or pulls a CUDA torch.
  **Rule:** install `torch==2.13.0+cpu` from the PyTorch CPU index **first**,
  then `pip install -r requirements.txt -r requirements-test.txt -c constraints.txt --ignore-installed PyYAML`.
- **Trap:** running that torch line on macOS, or "fixing" the `+cpu` pin when
  it 404s there. **Rule:** macOS needs **plain** `torch==2.13.0` (no `+cpu`
  wheel exists for Apple Silicon); both manifests hardcode `+cpu` **by design**
  (dependency-confusion-proof on Linux/Windows). Use the §8 macOS block, which
  strips torch from the requirements copy but only drops `+cpu` in the
  constraints copy. Do **not** strip torch from constraints:
  `--ignore-installed` reinstalls everything, and unconstrained torch floats to
  PyPI's newest (reproduced 2026-09-06: 2.14.0). `ci.yml`'s `macos-latest` leg
  and `macos/install-cyclaw.sh` do the same.
- **Trap:** moving the torch pin and touching only `requirements.txt`/
  `constraints.txt`. **Rule:** `environment.yml` (conda, `pytorch=2.13.0=cpu*`)
  is a fourth surface, CI-gated by `python-package-conda.yml` and dep-guard D9.
  Bump it in the same commit.
- **Trap:** running `cyclaw-server`/`cyclaw-index`/`cyclaw-metrics` after only
  `pip install -r requirements.txt`. **Rule:** those `[project.scripts]` shims
  exist only after `pip install -e .`. The `python -m …` forms always work and
  are what both launchers use.
- **Trap:** running `pytest` in a fresh container. **Rule:** a fresh clone has
  NO Python deps. Install first (`/CyClaw-Sandbox` Quick Mode, or the
  `cyclaw-gotchas` skill's `driver.sh venv`).
- **Trap:** assuming the cloud sandbox's `python3` is 3.12, or `apt install`ing
  one. **Rule:** on `sandbox-ccr-default` (Ubuntu 24.04) Python 3.10–3.13 are
  all at `/usr/bin/python3.NN`, but bare `python3`/`pip3`/`pytest` resolve to
  3.11, and no interpreter has the deps. Under 3.11, `test_agentic_*` fails 142
  tests (`shutil.rmtree(onexc=...)` is 3.12+) — easy to mistake for a red
  `main`. Build a venv outside the repo each session (the container is
  reclaimed): `python3.12 -m venv /root/.venv-cyclaw-312`, install with that
  venv's `pip` (torch line, then requirements as above), and run tests via
  `/root/.venv-cyclaw-312/bin/python -m pytest ...`. `driver.sh venv` also
  handles a proxy-denied `download.pytorch.org`. Never change the system
  `python3` (`update-alternatives`): the runtime's own hooks resolve through it.
- **Trap:** assuming the server refuses to boot without `GROK_API_KEY`.
  **Rule:** it boots; Grok reports unavailable. Tests only need
  `GROK_API_KEY=dummy`.
- **Trap:** treating `status: degraded` in `/health` or `TELEMETRY KILL` on
  startup as errors. **Rule:** both are normal (no Ollama; intentional env
  blocking).

### Boot semantics
- **Trap:** adding a hard failure when `data/personality/soul.md` is missing.
  **Rule:** it **self-heals** — `PersonalityManager._load_soul` writes a default
  and records a version. The baseline is the newest `soul_versions` DB row
  (there is no `soul_hash` constant).
- **Trap:** expecting the server to build the index on first run.
  **Rule:** a missing index is fail-soft — `/query` returns 503
  `INDEX_NOT_FOUND`. Build it with `python -m retrieval.indexer`.
- **Trap:** assuming no `CYCLAW_API_KEY` means soul endpoints are open.
  **Rule:** unset key = **fail closed (401)**, compared with `hmac.compare_digest`, for every key-based credential (Bearer,
  console cookie). The deliberate exception: with `auth.enabled`, an enabled
  admin's login satisfies `require_api_key` without the key (`INVARIANTS.md` Rule 6).
- **Trap:** reordering imports in `gate.py` "to tidy them."
  **Rule:** the `_TELEMETRY_KILL` env block MUST stay above the heavy imports
  (`graph`, `retrieval`, `langchain`, `chromadb`); `test_telemetry_kill` locks
  it. Same for `mcp_hybrid_server.py`'s `apply_telemetry_kill()` — its
  `# noqa: E402` imports are load-bearing.
- **Trap:** "simplifying" `gate.py` to `apply_telemetry_kill()` without the
  `_TELEMETRY_KILL = ...` assignment. **Rule:** G1 finds that name by **AST**;
  drop it and G1 reports `kill at None` and fails.
- **Trap:** assuming `Settings(anonymized_telemetry=False)` covers ChromaDB.
  **Rule:** it covers only PostHog. OTel is separate: chromadb's `otel_init()`
  early-returns only when `CHROMA_OTEL_GRANULARITY` is `"none"`. Both defenses
  live in `utils/telemetry_kill.py`; neither is redundant.
- **Trap:** "completing" `TELEMETRY_KILL` with `HF_HUB_OFFLINE`/
  `TRANSFORMERS_OFFLINE` (they appear in
  `docs/security-philosophy/cyclaw_telemetry_kill.env`). **Rule:** excluded on
  purpose: `huggingface_hub` latches `HF_HUB_OFFLINE` at import, so forcing it
  breaks the first-run model fetch. `retrieval/embeddings.py`'s `_load_model`
  goes offline only when `_model_offline_eligible` finds the model cached
  (`try_to_load_from_cache`, network-free), **or** `models.embeddings.offline_after_index`
  (default `false`) is on and the BM25 sidecar exists (`_index_or_bm25_present`;
  not the Chroma dir, which `_ChromaWriter.reset()` creates early). The real gate
  is `local_files_only=eligible` on `SentenceTransformer(...)`, not the env vars.
  `retrieval/rerank.py` applies the identical rule, so "cache both retrieval
  models" is the operator statement.
- **Trap:** treating `ORT_TELEMETRY_OPT_OUT` as a kill switch, or ORT telemetry
  as Windows-only. **Rule:** onnxruntime never reads `ORT_TELEMETRY_OPT_OUT`
  (an inert legacy marker; never count it as protection). Since v1.29.0
  non-Windows builds carry 1DS telemetry too; the pre-init control is
  `ORT_DISABLE_TELEMETRY=1` (in `TELEMETRY_KILL`), with
  `disable_telemetry_events()` as the post-import second layer (#1135). On
  Windows (ETW) absolute suppression needs a `--no_telemetry` build — never
  claim it.

### Retrieval & config
- **Trap:** "fixing" `min_score: 0.028` upward toward a cosine-like 0.5, or
  above the hybrid ceiling ~0.033. **Rule:** it is on the **RRF scale**
  (zero-based ranks: dual rank-0 with `rrf_k=60` is `2/60`), and gates only the
  keyword-only degrade. Hybrid queries are decided by `min_semantic_score` on
  the best semantic hit. Do not reinstate "a chunk must rank in both legs'
  top-k": measured, it rejected answerable paraphrases (see `graph.py`'s
  `route_by_score_node`).
- **Trap:** raising `min_semantic_score` to stop look-alikes (*The Medium*
  horror film matches the McLuhan chunk at cosine 0.46). **Rule:** no cosine
  floor separates them from real paraphrases; that is the cross-encoder veto's
  job (`retrieval.min_rerank_score`, **logit** scale, shipped `null`). The veto
  can only drop hits; `tests/ci_rag_smoke.py` fails if it vetoes an asserted
  answerable probe.
- **Trap:** unifying the test mock's `min_score` (0.75) with production (0.028).
  **Rule:** both are load-bearing: mock scores straddle 0.75, production RRF
  scores straddle 0.028.
- **Trap:** a config key for the embedding cache size. **Rule:** fixed at
  import via `lru_cache`; only `CYCLAW_EMBED_CACHE_SIZE` changes it.
- **Trap:** editing `config.yaml` in a running process and expecting new
  patterns. **Rule:** the sanitizer `lru_cache`s by config path; restart.
  (`enabled: true` + zero patterns silently degrades to length-only.)

### Testing
- **Trap:** changing conftest `test_config` to a shallow `.copy()`.
  **Rule:** it MUST stay a deepcopy (shallow leaks mutations across tests);
  `test_conftest_fixtures` guards it.
- **Trap:** `import gate` at a test module's top level.
  **Rule:** that triggers full app init (FastAPI + ChromaDB + retriever). Use a
  subprocess (`test_telemetry_kill`) or module-level patching (`test_gate`).
- **Trap:** seeing local `pytest` green and assuming coverage passed.
  **Rule:** bare `pytest` runs **no** coverage; the 80% `fail_under` applies
  only with CI's explicit `--cov=` flags, one per `[tool.coverage.run] source`
  entry at package granularity. A new module in a listed package is measured
  automatically; a new **top-level** package/module must be added to
  `pyproject.toml` and both CI lanes —
  `tests/test_ci_coverage_flag_contract.py` fails on drift. New test files
  auto-discover.
- **Trap:** assuming `pytest tests/` ran `tools/lora_finetune/tests/`.
  **Rule:** `testpaths = ["tests"]` excludes it; its CI is
  `.github/workflows/lora-finetune.yml`. When that tree is in the diff, run
  `GROK_API_KEY=dummy pytest tools/lora_finetune/tests/ -q --tb=short`.
- **Trap:** renaming `ci_rag_smoke.py` to `test_ci_rag_smoke.py`.
  **Rule:** it is deliberately not `test_*`-named; it runs as its own CI step.
  Renaming double-runs it and drags ChromaDB into the unit lane.
- **Trap:** a fresh `MockGrokClient` to simulate "no API key."
  **Rule:** it defaults `available=True`; pass `available=False`.
- **Trap:** a unit test building a real `HybridRetriever` from the **shipped**
  `config.yaml` and running the graph. **Rule:** the shipped config enables
  `models.reranker`, so `retrieve_node` downloads the real cross-encoder
  (~91MB). Fake `retrieval.rerank._load_cross_encoder` or turn the reranker off
  (as `tests/test_rag_integration.py` does); conftest's `TEST_CONFIG` and
  `MockRetriever` leave it off.
- **Trap:** trimming `banned_patterns` and expecting a count test to catch it.
  **Rule:** no test asserts `== 40`, but `TestShippedConfigContract` runs
  specific **phrases** against the real config. Adding patterns is safe;
  removing coverage is not.
- **Trap:** adding a state-changing POST route without touching the console
  contract. **Rule:** `test_terminal_contract` extracts routes from
  `terminal.html`; add new POST endpoints to its `_POST_PATHS`.
- **Trap:** treating `mypy --strict` as clean or as a CI gate. **Rule:** it is
  neither. Only `lint.yml` runs ruff (F/B/S blocks; the broader set and WPS are
  advisory); `ci.yml` runs no ruff and no workflow runs mypy. The bare
  repo-root run errors on `utils/errors.py` ("found twice") because `utils/`
  has no `__init__.py` — add `--explicit-package-bases` — and legacy untyped
  code remains. Check only the lines you wrote.

### Code conventions
- **Trap:** `raise Exception(...)` or a bare `except:`.
  **Rule:** raise a typed error from `utils/errors.py` (rooted at `RAGError`
  with `.code`/`.message`/`.details`); out-of-band subsystems use their own
  subtrees. (`RcloneTimeoutError` deliberately bypasses its parent `__init__` to
  keep its sub-code — do not "simplify" it.)
- **Trap:** changing an error `code` string or the `"{code}: {message}"` stamp.
  **Rule:** asserted verbatim in `test_graph`. Success paths must NOT emit an
  `error` key (it would clobber an upstream error).
- **Trap:** a generic `sys.exit(1)` from a CLI.
  **Rule:** exit codes are an API. Agentic: `0` ok · `2` failed · `3` env/config
  · `4` write refused. Sync uses `10` = corpus-changed → reindex. `clear_cache`:
  `0`/`2`/`3`.
- **Trap:** "optimizing" the BM25 store to pickle.
  **Rule:** BM25 stays JSON (`index/bm25.json`); pickle is RCE. `test_security`
  guards it.
- **Trap:** logging raw query text "for debugging."
  **Rule:** the audit log stores keyed HMAC fingerprints by default; `test_gate` enforces it.
- **Trap:** treating MCP `hybrid_search` as unsanitized.
  **Rule:** it runs `check_input` before retrieval (E3, #974; same patterns and
  `max_input_chars` as `/query`) and audits `prompt_injection_blocked`.
- **Trap:** re-reading `config.yaml` inside a module, or cwd-relative paths.
  **Rule:** config is loaded once and passed down as `cfg`. Paths anchor to
  `_BASE_DIR`/`_REPO_ROOT`, never cwd (Windows double-click breaks cwd).

### Dependencies
- **Trap:** bumping `pydantic-core` alone, or adding `[standard]` to the uvicorn
  constraint. **Rule:** `pydantic` and `pydantic-core` are lock-step
  (2.13.5 ↔ 2.46.5); the `uvicorn` constraint carries no extras (pip ≥26.1.2
  rejects extras in a constraints file).
- **Trap:** letting numpy float to 2.x. **Rule:** numpy is pinned `<2`
  (dependabot ignores `numpy>=2.0.0`; numpy 2 removes `np.float_` and breaks
  chromadb/onnxruntime). It is also a direct import since #1491
  (`retrieval/hybrid_search.py`), so `verify-deps` E7 no longer treats it as
  transitive-only.
- **Trap:** "fixing" the chromadb CVE. **Rule:** it is risk-accepted,
  embedded-`PersistentClient`-only per the threat model. Do not switch to the
  HTTP client or file a fix PR.

### Git & PR
- **Trap:** pushing to `main` via the GitHub MCP while a feature branch + open PR
  exist. **Rule:** never — it creates add/add rebase conflicts. Branch → draft
  PR → human merges.
- **Trap:** force-pushing after a rebase without asking.
  **Rule:** `--force-with-lease` needs explicit user sign-off (the session
  runtime blocks it otherwise).
- **Trap:** two branches editing the same shared file (`ci.yml`, `config.yaml`,
  manifests, `CLAUDE.md`) from the same base. **Rule:** trial-merge the pair
  locally before opening PRs.
- **Trap:** diagnosing a child PR's red CI as the PR's fault.
  **Rule:** a red `main` poisons every branch cut from it. Check `main` first.
- **Trap:** opening a draft PR and going dark. **Rule:** subscribe to its
  activity events at creation when the runtime offers it
  (`subscribe_pr_activity`) and drive it to green until merged or closed.
  Runtimes without event delivery (e.g. Kimi via `gh`) check CI once after
  push, then hand the watch to the operator explicitly.
- **Trap:** the over-correction — a recurring poll beside a live subscription.
  **Rule:** events are the signal; no polling loop duplicates them. At most one
  long-fuse (4–6h), non-re-arming safety sweep per session; in a multi-agent
  fleet one agent owns it, and every agent dedups against open PRs
  (`list_pull_requests`) before implementing.

---

## 5. Conventions

### Code
- **Python 3.12** (`requires-python >=3.12`). Fully type-annotated; PEP 604
  unions (`str | None`), builtin generics, `TypedDict`/`Protocol`/`Literal` over
  `Any`. `from __future__ import annotations` in new modules.
- **Lint:** `lint.yml` blocks on `ruff check --select F,B,S .`; its broader
  `--select E,F,I,B,C4,UP,S --ignore E501` pass and WPS are advisory, but keep
  them clean locally. Line length 120, `.claude` excluded. Always pass
  `--ignore E501` with `--select E` (CLI select outranks the config ignore).
  **Types:** `mypy --strict --python-version 3.12 --explicit-package-bases` on
  the lines you write (best-effort, §4).
- **No `print`** in library code — `logging.getLogger("cyclaw.<module>")` with
  lazy `%s` formatting. Audit is a separate JSONL stream.
- **No `shell=True`** with user input; always `subprocess.run([...])` list-form.
- **No secrets in code** — env vars only. **No TODO/FIXME comments**; encode
  intent in explanatory comments ("why, with PR reference", matching the
  surrounding density).
- Data-modifying scripts default to a safe dry-run (`--apply` to act).

### Commits, branches, PRs
- **Conventional commits:** `feat:`/`fix:`/`perf:`/`chore:`/`test:`/`docs:`/`ci:`
  (`feat(scope):` when scoped).
- **Branches:** short-lived, vendor-prefixed (§10 table), deleted after merge;
  never develop on `main`.
- **PRs are draft**, one reviewable concern each, body populated from
  `.github/PULL_REQUEST_TEMPLATE.md`. A human decides when to merge.
- **Watch what you open — by events, not polls** (§4 Git & PR).

### Docs
- Dated audit/report docs go in `docs/audits/`. Live memory lives ONLY in
  `docs/memories/` (do not re-create `.claude/memory/`, deleted in #1351).
- Every `##` section must be self-contained (no pronoun references to earlier
  sections) — the corpus is chunked and searched section-by-section.
- Don't duplicate another doc's authority; link to it. `config.yaml` owns the
  numbers — cite, don't copy-and-drift.

### Kimi Code agents
- This manual applies verbatim to Kimi Code sessions — same invariants, test
  gate, and draft-PR flow; branches use `kimi/<topic>`.
- **`gh` trap (Windows operator machine):** bare `gh` on PATH is a py3dot12
  shim, NOT GitHub CLI. Call `"/c/Program Files/GitHub CLI/gh.exe"`
  (authenticated as `cgfixit`).
- Kimi has no GitHub MCP tools and no session stop-hook — use `gh` and the
  user's own git identity.
- **Optimize skill:** the Kimi port of `.claude/skills/CyClaw-Optimize/` lives
  at `~/.agents/skills/cyclaw-optimize/`; the in-repo skill is canonical, keep
  them in step.
- **PR body = the template:** read `.github/PULL_REQUEST_TEMPLATE.md` and
  populate its sections, not an ad hoc What/Why/Verification shape (root-caused
  2026-07-28; `~/.agents/` should point at the template as
  `.codex/Codex_instructions.md` does).

---

## 6. Quality Bar per Deliverable (checkable criteria, not adjectives)

A deliverable is done only when its box is fully checked.

**Code change**
- [ ] `ruff check --select F,B,S .` clean (CI-blocking in `lint.yml`)
- [ ] `ruff check --select E,F,I,B,C4,UP,S --ignore E501 .` clean (advisory — keep it clean locally)
- [ ] `mypy --strict --python-version 3.12 --explicit-package-bases` clean on
      the lines you wrote (best-effort, §4)
- [ ] `GROK_API_KEY=dummy pytest tests/ -q --tb=short` green
- [ ] if the diff touches `tools/lora_finetune/`, also
      `GROK_API_KEY=dummy pytest tools/lora_finetune/tests/ -q --tb=short`
- [ ] CI-style coverage run ≥ 80% and the gate not lowered
- [ ] no new dependency without an exact pin in `pyproject.toml` AND
      `constraints.txt`
- [ ] the diff touches only files named in the task (no drive-by edits)
- [ ] each of the six invariants is untouched, OR the change is argued
      explicitly in the PR body and `invariant-guard` re-run
- [ ] `python3 .claude/skills/invariant-guard/check_invariants.py` exits 0

**Test**
- [ ] uses `tests/conftest.py` fixtures; starts no live service
- [ ] asserts behavior/contract, not incidental implementation detail
- [ ] deterministic — no real `sleep` racing a timeout, no network, no clock
- [ ] discovered by pytest without editing `ci.yml`

**Pull request**
- [ ] draft; conventional-commit title; body follows the PR template
- [ ] one concern; diff reviewable in one sitting
- [ ] if it shares a file with another open PR, a local trial-merge was verified
- [ ] CI green, or each failure explained against `main`'s own state

**Documentation**
- [ ] every number sourced from `config.yaml`/`pyproject.toml` (none invented)
- [ ] `##` sections self-contained; dated if it is a report
- [ ] `python3 .claude/skills/doc-sync/doc_sync.py` shows no new drift it caused

**Skill**
- [ ] YAML frontmatter (`name`, `description`); numbered steps with exact commands
- [ ] a Guardrails section restating the relevant invariants
- [ ] a Gotchas section
- [ ] a self-contained `verify.sh` if it ships an executable (CI auto-runs it,
      non-blocking) — must exit 0 when healthy and skip cleanly without deps

---

## 7. When Uncertain — Escalation Rules

Classify every action before doing it.

| Tier | Concrete triggers | Required action |
|---|---|---|
| **Low** | Local, reversible, narrow: format, add a test, fix a doc typo, read code, run a documented command | Proceed. Standard checks. |
| **Medium** | Shared code path, recoverable: edit a module's logic, add a dependency, change a fixture, refactor within one subsystem | Proceed; expand tests; state the rollback path in the PR body |
| **High** | Irreversible or broad: destructive command, force-push, `soul.md` mutation, editing a graph edge / auth / sanitizer pattern, weakening any test, a new runtime dependency, anything touching a security invariant | **Stop and ask first** |

When unsure which tier, choose the higher one.

**Always ask first (High):** deleting/overwriting files you didn't create;
force-push; `git push` to `main`; mutating `soul.md`; changing graph edges,
`banned_patterns`, or auth; loosening a test or the coverage gate; adding a
runtime dependency; wiring a new hook in `settings.json`.

**Never ask (just do it):** running the documented test/lint/run commands;
reading anything; adding tests; fixing doc typos; `ruff format`; running any of
the `.claude/skills/*/check_*.py` or `verify.sh` checkers.

**Mid-task ambiguity with two reasonable readings:** state your assumption,
proceed on the **smallest reversible** interpretation, and flag it in the PR
body — do not stall. Ask only when the readings diverge on something
irreversible or a matter of user taste.

**Blocked:** record it in `docs/work/SESSION_NOTES.md` and escalate —
`#cyclaw-dev` for undefined behavior, a private GitHub security issue for
security concerns, `/CyClaw-Sandbox` for suspected config drift.

Do NOT: re-ask a question already answered; ask the user to reveal a secret;
change code behavior to make a stale doc "true" (fix the doc, or flag the
behavior gap).

---

## 8. Commands That Work

Skills reference this section; keep it as the single canonical copy.

```bash
# Install — Linux/Windows (order matters — torch CPU FIRST)
pip install torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r requirements-test.txt -c constraints.txt --ignore-installed PyYAML

# Install — macOS (Apple Silicon): PLAIN torch; strip torch/index lines from the
# requirements copy, drop only the +cpu suffix in the constraints copy (§4).
pip install "torch==2.13.0"
grep -v -e '^torch==' -e '^--extra-index-url https://download.pytorch.org' \
    requirements.txt > /tmp/requirements-macos.txt
sed 's/^\(torch==[0-9][0-9.]*\)+cpu$/\1/' constraints.txt > /tmp/constraints-macos.txt
pip install -r /tmp/requirements-macos.txt -r requirements-test.txt -c /tmp/constraints-macos.txt --ignore-installed PyYAML

# Install — conda (fourth surface; conda-forge names torch `pytorch`)
conda env create -f environment.yml

# Console scripts (cyclaw-*) need the project itself installed
pip install -e . -c constraints.txt

# Build the retrieval index (required before /query returns hits)
python -m retrieval.indexer            # or: cyclaw-index

# Tests (GROK_API_KEY must be any non-empty value)
GROK_API_KEY=dummy pytest tests/ -q --tb=short
GROK_API_KEY=dummy pytest tests/test_graph.py -q --tb=short   # single file
GROK_API_KEY=dummy pytest tests/test_agentic_*.py -q          # agentic only
GROK_API_KEY=dummy python tests/ci_rag_smoke.py               # real-index RAG smoke
GROK_API_KEY=dummy pytest tools/lora_finetune/tests/ -q --tb=short  # not under testpaths

# Lint / types (Ruff F/B/S blocks in CI; the rest is advisory/best-effort)
ruff check --select E,F,I,B,C4,UP,S --ignore E501 .
mypy --strict --python-version 3.12 --explicit-package-bases "<touched files>"

# Run the server + probe health
python gate.py            # or: cyclaw-server   (binds 127.0.0.1:8787)
curl -s http://127.0.0.1:8787/health

# Run the retrieval-only MCP server (stdio; no LLM path)
python mcp_hybrid_server.py                    # or: cyclaw-mcp

# Metrics / cache
python -m metrics                              # or: cyclaw-metrics
python -m retrieval.clear_cache                # dry-run; add --apply to delete

# Invariant / config / deps / doc / retrieval / sanitizer health (skills)
python3 .claude/skills/invariant-guard/check_invariants.py
python3 .claude/skills/dotenv-guard/check_dotenv.py     # secrets out of dotenv files; stdlib + git + bash
python3 .claude/skills/config-guard/check_config.py     # add --strict to lock shipped defaults
python3 .claude/skills/dep-guard/check_deps.py          # pure stdlib; runs pre-install
python3 .claude/skills/verify-deps/extract_pins.py      # requirements.txt cross-check; add --json
python3 .claude/skills/verify-deps/check_env_drift.py   # non-manifest drift E1-E7 incl. the Docker surface; add --strict
python3 .claude/skills/doc-sync/doc_sync.py
python3 .claude/skills/index-doctor/doctor.py --rebuild
python3 .claude/skills/injection-redteam/redteam.py
```

CI targets Python 3.12 on ubuntu + windows + macos; all three `test` legs are
release gates. In `ci.yml` only `verify-skills` carries `continue-on-error`.
Advisory lanes elsewhere: `numbat-rules.yml`'s hand-fixture job (its
`numbat-stream-contract` and `numbat-cel` jobs block, #1458), `lint.yml`'s
broader-Ruff and WPS steps, and best-effort steps in the
nemo-guardrails/pr-review/conda/trivy workflows. Coverage sources: `gate`,
`gate_ops`, `gate_auth`, `gate_memory`, `graph`, `mcp_hybrid_server`,
`metrics`, `llm`, `retrieval`, `utils`, `sync`, `agentic`, `guardrails`,
`telegram`, `opentweet`, `memory`, `schemas`. `tests/conftest.py` mocks all
external deps. `tests/` holds 217 auto-collected `test_*.py` files (including
two under `tests/nemo_runtime/`).

---

## 9. Skills

Skills live at `.claude/skills/<name>/SKILL.md`. When a skill is not present in
the local sandbox, **check GitHub main before declaring it absent**
(`mcp__github__get_file_contents` on `.claude/skills/<name>/SKILL.md`).

Skills marked `disable-model-invocation: true` are reachable only as slash
commands (`.claude/commands/<name>.md`) — Claude never auto-routes to them —
but CI and other skills still run their scripts directly; the flag gates only
model-initiated `Skill` calls.

### CyClaw-specific security & health skills (built on the invariants)

| Skill | Type | Purpose | Runs pre-install? |
|---|---|---|---|
| `/invariant-guard` | check, user-invoked only | Static-assert the six invariants + guards against a diff | Yes (stdlib) |
| `/dotenv-guard` | check, user-invoked only | Keep secrets out of dotenv files, gitignored or not: no runtime dotenv load, tracked env files, `.gitignore` coverage, a sandboxed `setup-cyclaw-keys.sh` run (fake Keychain), script/doc line checks; baseline ratchet. Blocking CI job | Yes (stdlib + git + bash) |
| `/config-guard` | check, user-invoked only | Static-validate config.yaml's relational/value/threat-model contract (graph_timeout>llm_timeout, chunk_overlap<chunk_size, RRF-scale min_score, loopback host, shipped provider posture, `api_key_optional` vs. the bind address) | Needs PyYAML |
| `/dep-guard` | check | Dependency-pin invariants across pyproject + constraints + environment.yml (pydantic lock-step, numpy<2, torch +cpu, uvicorn no-extras, cross-file agreement) | Yes (stdlib) |
| `/verify-deps` | check | Extends dep-guard: requirements.txt cross-check, non-manifest drift E1–E7 (workflow pins, Python version, undeclared imports, install scope, Dockerfile/compose/GHCR coherence, unused runtime pins), an install dry-run per surface, and a PyPI currency + CVE sweep. Reports only — never auto-bumps | extract_pins.py + check_env_drift.py yes; sweep needs network |
| `/injection-redteam` | loop | Adversarial probe corpus vs the sanitizer; close bypasses | Needs venv |
| `/index-doctor` | check, user-invoked only | Rebuild + validate ChromaDB/BM25/RRF; probe retrieval health | Needs venv |
| `/doc-sync` | check, user-invoked only | Detect code↔docs drift; reconcile the docs | Needs PyYAML |
| `/otel-hardening` | check + task | Telemetry-kill contract: independent oracle over both maps + scrub set, staleness, pin drift, reference-`.env`, Docker/launcher/generator delivery, bypass sweep, ONNX seams, and a category-1–5 egress classification (strict fails on an unclassified component); then a live vendor-doc sweep. Mutation self-test in `verify.sh`. A new `subprocess` spawn site must add its binary to `check_otel.py`'s `KNOWN_EXTERNAL_COMPONENTS` | Static half yes; sweep needs network |

### Operational & workflow skills

| Skill | Type | Purpose |
|---|---|---|
| `/babysit-github-pr` | loop, user-invoked only | Watch a PR end-to-end — triage CI/review, stop on rebase conflicts, require explicit `ALLOW_FORCE_WITH_LEASE=true` before rewriting a behind branch |
| `/CyClaw-Optimize` | task, user-invoked only | Scan main for optimizations; open focused draft PRs |
| `/CyClaw-Sandbox` | task, user-invoked only | Clone/current-checkout audit: six verification ladders, in-process RAG checks, live gate/platform probes, JSON/tmp reports. Opens no PR by itself. `/run` = Quick Mode |
| `/architecture-refactor` `/speed-refactor` `/tests-refactor` `/logging-refactor` | loop | Iterative refactor loops |
| `/add-comment` | task | Comment-only pass adding ELI5-toned WHY comments to under-documented code |
| `/karpathy-guidelines` | mode | Anti-overcomplication guardrails: surgical diffs, surfaced assumptions, verifiable success criteria |
| `/cyclaw-privacy` | mode, user-invoked only | "Legal" persona for privacy/DPA/DSR/breach review of CyClaw changes (distinct from `.codex/skills/cyclaw-advisor`) |
| `/cyclaw-gotchas` | reference + driver | Session-tested sandbox traps (proxy-denied torch/HF hosts, the 3.12 venv, silent pytest summary, PR/review-bot process) plus `driver.sh` (`inventory`/`venv`/`serve`/`probe`/`stop`/`test`/`checks`). Model-invocable on purpose: load it before installing deps, running tests, launching `gate.py`, or driving a PR |

### Standalone commands and agent skills

`/audit`, `/check-soul`, `/conversation-summary`, `/run`, and `/status` are
inline procedures wired only as `.claude/commands/*.md`, with no skill folder
(tracked in `.claude/README.md`). `/verification-specialist` and
`/documentation-guide` are `.claude/skills/*/SKILL.md` agent skills.

The session-hygiene wrappers, the memory-lifecycle trio, and
`/python-coding-agent` were deleted in #1351 (2026-09-16) along with the hooks
that invoked them, so nothing persists session memory to `docs/memories/`
automatically.

### Cross-repo behavioral skill

`/fable-protocol` — reasoning-discipline, epistemic-calibration, and
knowledge-handoff layer (mark speculation, verify stale knowledge, security
lens on every artifact, anti-sycophancy, model routing, the owner's
communication contract, and CyClaw facts to know cold). Registered both here and
at user level (`~/.claude/skills/fable-protocol/SKILL.md`), so it activates in
any repo. It carries no independent authority: `CLAUDE.md` and `config.yaml`
remain the source of truth, and nothing in it overrides §3. It is
`disable-model-invocation: true`; the `fable-protocol-loader.sh` SessionStart
hook injects it for Sonnet-tier models only (§10), every other model reaches it
via explicit `/fable-protocol`.

---

## 10. Session Protocol

**Start.** Two SessionStart hooks run. `session-start-sync-check.sh` reports
local↔remote divergence without mutating anything (never resets, rebases,
pushes, or deletes; always exits 0). `fable-protocol-loader.sh` injects
`/fable-protocol` only when the stdin model id contains `sonnet` (an opt-in
allowlist; Opus, Haiku, Fable, and unknown ids are skipped). A mid-session
`/model` switch fires no hook — run `/fable-protocol` by hand if wanted.

**Commit identity.** Claude Code commits as the runtime's identity, never as
`CyClaw Agent` (owner decision, 2026-09-26): `Claude <noreply@anthropic.com>`
in the cloud (runtime-signed, so GitHub shows it Verified; the runtime's stop
hook flags any other committer as Unverified), the operator's own identity
locally. The sync-check hook removes the old `CyClaw Agent` pin while it still
holds the old default and pins nothing. Before committing,
`git var GIT_COMMITTER_IDENT` should show the runtime identity; if a stale pin
remains:

```bash
git config --local --unset user.email; git config --local --unset user.name
```

CyClaw's own agentic loop is different: its identity source is
`utils/agent_identity.py`, with **driver-agnostic** defaults (that loop is
often a local model), read by both repo_workspace commits and writer PR heads.
`CYCLAW_AGENT_COMMIT_NAME` / `CYCLAW_AGENT_COMMIT_EMAIL` override it (defaults
`CyClaw Agent` / `cyclaw-agent@users.noreply.github.com`) and never apply to a
Claude Code session. To commit Claude Code work under another identity, set
git's own `GIT_AUTHOR_*`/`GIT_COMMITTER_*` for that session (Unverified in the
cloud).

**Branch namespaces** follow `.github/PULL_REQUEST_TEMPLATE.md` — validation
accepts every listed vendor (and `agent/`):

| Driver | Branch form |
|--------|-------------|
| Claude Code | `claude/{feature}` |
| Codex | `codex/{feature}` |
| Grok Build | `grok/{feature}` |
| Kimi / Kimi Code | `kimi/{feature}` |
| CyClaw direct / MCP | `CyClaw/{feature}-{date}` (also `cyclaw/`) |
| Unknown / generic | `agent/{feature}` |

`CYCLAW_AGENT_BRANCH_PREFIX` (default `agent`) sets only the *preferred*
prefix; it does not revoke the allowlist.

The cloud **session runtime** applies a stop hook (not wired in repo
`settings.json`) that flags commits whose committer email is not
`noreply@anthropic.com` and blocks `--force-with-lease` without explicit
authorization. Re-authoring an unpushed commit
(`git commit --amend --no-edit --reset-author`) is fine; rewriting a published
one is a force-push and needs the owner's sign-off.

**During.** Track compact memory: Goal, Constraints, Decisions (with one-line
rationale), Open questions, Verification state. Prefer file-backed facts over
inference. Expire stale assumptions when new evidence appears.

**End.** Durable project conventions → this file or `.claude/rules/`.
Session-scoped discoveries → `docs/memories/`, written by hand. Run `/doc-sync`
to reconcile this file against the code before you consider the session done.

---

## Reference

- Multi-agent work: you (coordinator) own synthesis and final correctness;
  workers gather evidence and produce artifacts, they do not make architectural
  decisions. Dispatch read-only research in parallel; serialize write-heavy work
  per file set; give each worker a fully self-contained prompt.
- Threat model & security scope: `docs/THREAT_MODEL.md`.
- Agentic layer governance: `docs/agentic/AGENTIC_README.md`,
  `docs/agentic/SKILLS_REGISTRY_GOVERNANCE.md`.
