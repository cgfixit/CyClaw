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

**Critical Python coding requirement.** A docstring belongs only at the top of
a file or a function definition; every other multi-line comment uses `#` on
each line.

**Where truth lives.** In priority order:
1. **Code** — the running behavior. When docs and code disagree, code wins.
2. **`config.yaml`** — the single source of truth for every tunable.
3. **`docs/THREAT_MODEL.md`** — the security scope: trusted-operator (one by
   default, a small mutually trusted set behind `auth.enabled`),
   loopback-bound, single-tenant; multi-operator is not multi-tenant, and
   nothing here is a sandbox for untrusted code. Read it before security work.
4. This file and `.claude/rules/PROJECT_RULES.md` — the operating rules;
   `AGENTS.md` is the parallel guidance for other agents, kept consistent.
5. `README.md` for the holistic view; `docs/changelog.txt` for history.

---

## 2. The Map

### Request flow

```
HTTP POST /query   (or MCP tools/call: hybrid_search)
        │
        ▼
   gate.py  — body cap (security.max_request_body_bytes, 413) → TrustedHost check
              → rate limit (60/min per IP) → injection filter → soul init
              → graph invoke (wrapped in 780s timeout)
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
                                     ├─ confirmed=None (pause, needs_confirm) → audit_logger
                                     ├─ confirmed + hybrid + selected provider usable
                                     │    → pre_action_hook_<provider> → grok_fallback |
                                     │      claude_fallback (their gate is the triple gate, not
                                     │      guardrail_input; the hook can only shrink this space
                                     │      and a deny goes straight to audit_logger; the broker
                                     │      wraps the call with NeMo check() or deterministic
                                     │      checks on degradation — deny-only, grounding local)
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

`retrieve` is the unconditional first node; routing is graph edges, never an
LLM decision.

### All HTTP routes (gate.py)

| Method | Route | Auth | Notes |
|---|---|---|---|
| GET | `/` | none | serves `static/terminal.html` |
| GET | `/static/*` | none | static mount |
| POST | `/query` | **session or device token when `auth.enabled`**; **same-origin always** | rate-limited, sanitized; cross-site → 403 `CROSS_SITE_BLOCKED` regardless of `auth.enabled` (no `Origin`/`Sec-Fetch-Site` at all is allowed); `audit` role → 403 `AUTH_ROLE_DENIED`; 400/401/403/429/503/504/500 |
| GET | `/health` | none | not rate-limited; `degraded` without Ollama is NORMAL |
| POST | `/index/build` | **loopback peer + same-origin, no forwarding headers; plus API key once `CYCLAW_API_KEY` is set** | rate-limited; audited; background build; 403 off-box or proxied; 401 `INDEX_BUILD_AUTH_REQUIRED` without a credential once the key is set; 409 while running. Not key-gated while the key is unset (that would brick first-run) |
| GET | `/index/status` | none | not rate-limited (the console polls it every 1.5s during a build); always 200 + `{state, elapsed_sec, chunks_done, chunks_total, error, index_ready}` |
| GET | `/soul` | **API key** | rate-limited |
| POST | `/soul/propose` `/soul/apply` `/soul/reload` `/soul/restore` | **API key** | propose = advisory scan, never writes; apply = enforced scan + atomic write, requires `reason`; restore = from `.bak` |
| GET | `/audit/summary` | **API key** | rate-limited; aggregates only |
| GET | `/console/session` | none (same-origin) | rate-limited; whether and how this browser can use the API-key routes (`via`: `console_key`/`admin_session`/`api_key_optional`) plus the console CSRF token; cross-site 403 |
| POST | `/console/session` | **Bearer key or one-time pairing code** | rate-limited, same-origin, audited; sets the HttpOnly console cookie (`__Host-cyclaw_console` under TLS) that satisfies `require_api_key` (`utils/console_session.py`); 401 when `CYCLAW_API_KEY` is unset |
| POST | `/console/session/end` | none (same-origin) | rate-limited, audited; deletes this browser's console cookie (rotate the key to revoke copies) |
| POST | `/ops/sync` `/ops/agentic` `/ops/fsconnect` `/ops/sqlconnect` | **API key** | rate-limited; subprocess shims |
| GET | `/auth/setup-status` | same-origin (no-Origin curl/MCP allowed) | rate-limited; `{enabled, needs_password, username}` while the bootstrap admin has no password; 503 when auth off |
| POST | `/auth/bootstrap-password` | loopback peer, no forwarding headers, same-origin | first admin password; 403 off-box or proxied; 409 once set; 503 when auth off |
| POST | `/auth/login` | none | cross-site rejection precedes rate limiting; bounded password workers; session cookie + CSRF token on success; 503 when auth off |
| POST | `/auth/logout` | **session cookie + CSRF** | rate-limited; 503 when auth off |
| GET | `/auth/whoami` | **session cookie or bearer token** | rate-limited; `username` + `role`; 503 when auth off |
| GET | `/auth/users` | **session; admin or operator** | list users, no hashes; 503 when auth off |
| POST | `/auth/users` | **session+CSRF or admin bearer** | create user; operator cannot create admin |
| POST | `/auth/password` | **session+CSRF or admin bearer** | self-service change needs `current_password` + new `password`; revokes existing sessions |
| POST | `/auth/users/{username}/password` | **session+CSRF or admin bearer** | reset; operator cannot touch admins |
| POST | `/auth/users/{username}/role` | **admin only** | last-admin protected |
| POST | `/auth/users/{username}/disable` `/auth/users/{username}/enable` | **admin; operator on non-admins** | last-admin protected |
| DELETE | `/auth/users/{username}` | **admin only** | hard delete after revoke; last-admin protected |
| GET | `/auth/audit/summary` | **session; admin or audit** | reduced audit view; not the ops API key |
| GET | `/memory/status` | **API key** | rate-limited; always 200 + flags |
| GET | `/memory/facts` `/memory/episodes` | **API key** | rate-limited; 404 when `memory.enabled` is false |
| GET | `/memory/proposals` | **API key** | rate-limited; 404 when propose/apply off |
| POST | `/memory/propose` `/memory/reject` | **API key** | rate-limited; require non-empty `reason` |
| POST | `/memory/apply` | **API key** | rate-limited; reason + injection scan on apply |
| GET | `/query/export/html` | **API key** | rate-limited; 404 when `export_html.enabled` is false |

The four `/ops/*` endpoints reach out-of-band subsystems ONLY through
`utils/ops_runner.py` (a `subprocess.run([...])` shim); they never import them.

**API key routes** are gated by `gate.py`'s `require_api_key`, which fails
closed (401) while `CYCLAW_API_KEY` is unset and accepts, besides the Bearer
key, two cookies — the console cookie `cyclaw_console` (minted by
`POST /console/session` for the key or a launcher's one-time pairing code; a
stateless HMAC keyed off `CYCLAW_API_KEY`, so rotating the key revokes all;
header `X-CyClaw-Console-CSRF`) and, with `auth.enabled`, an **enabled admin**'s
login (`X-CyClaw-CSRF`), the one credential that works with the key unset.
Both are refused cross-site and need their CSRF token on a write (a bad token is
a 403, never a fall-through); `operator`/`audit` never pass. The one deliberate
bypass, `security.api_key_optional` (ships `false`), lets
`_api_key_bypass_allowed` skip the key only when **all four** hold: flag set,
**socket peer is loopback** (never the `Host` header or the bind address), **no
reverse-proxy forwarding header**, and **not cross-site** — never collapse it to
"loopback" alone. A remote caller always needs the real key, including under the
container `CMD` (`uvicorn gate:app --host 0.0.0.0`, no bind guard) and under
Docker NAT (set `CYCLAW_API_KEY` in the container). `_require_loopback_bind`
refuses a non-loopback `api.host` while the flag is `true` (config-guard C13);
`CYCLAW_ALLOW_NON_LOOPBACK_BIND` outranks the bind guard, never the peer check.
The daily launchers generate a missing key into the OS keystore (`gate.py` never
does). Full contract and tests: `INVARIANTS.md` Rule 6 and
`docs/THREAT_MODEL.md` (eighteenth amendment).

The bypass never touches the session/RBAC `/auth/*` system (`gate_auth.py`,
`docs/AUTHENTICATION_DESIGN.md`), which `auth.enabled` governs alone: every
`/auth/*` handler exists regardless and answers 503 (not 404) when it is off,
and only the literal boolean `true` makes Stage 3 attach
`require_session_or_token` to `POST /query` (session cookie or named device
token, no CSRF). The `/memory/*` and `/query/export/html` routes are the
default-off memory subsystem (`gate_memory.py` + `memory/`,
`docs/memory/README.md`): handlers 404 while off (or 200 + `enabled: false`
for `/memory/status`), and mutations need the API key, a non-empty `reason`,
and an injection scan on apply (parallel to soul I5).

### Key modules

Module docstrings are the detailed reference; this is the index.

| Path | Role |
|---|---|
| `gate.py` | FastAPI entry: auth, body cap, rate limit, sanitizer, security headers, telemetry kill |
| `utils/telemetry_kill.py` | Canonical maps: `TELEMETRY_KILL` (21 pairs), `UPDATE_CHECK_OPT_OUT` (4), `SCRUBBED_ENV_KEYS` (5 tracing names + 2 declarative-OTel config names, removed outright); `apply_telemetry_kill()`, `build_telemetry_safe_env(base)`, `scheduler_env_overlay()`, `--export {shell,powershell}`. Applied at import by every chokepoint (G1 pins 14 orderings). Stdlib-only; deliberately excludes `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` (§4) |
| `utils/onnx_telemetry.py` | `suppress_onnx_telemetry()`: post-import `disable_telemetry_events()`, idempotent and absent-safe, called at `retrieval/vector_store.py` and `guardrails/integration.py`; the env half (`ORT_DISABLE_TELEMETRY=1`) rides the kill map |
| `gate_ops.py` / `gate_auth.py` / `gate_memory.py` | Route groups registered onto gate.py's app with its auth/rate-limit/audit callables injected: the four `/ops/*` shims (never import `sync`/`agentic`); `/auth/*` (session cookie + CSRF for browsers, bearer device tokens for programs; Stage 3 attaches `require_session_or_token` to `/query` by name, `_AUTH_DEPENDENCY_NAME`, only when `auth_manager` is not None); the default-off memory surface (`/memory/*` + `/query/export/html`, lazy-imports `memory` inside handlers only; `docs/memory/README.md`) |
| `memory/` | Optional facts + episodes SQLite+FTS5 store, propose/apply governance, optional retrieval fusion (all switches false) |
| `graph.py` | 12-node LangGraph topology; all security policy lives in the edges |
| `retrieval/hybrid_search.py` | RRF fusion (k=60) over ChromaDB + BM25; BM25 top-k uses numpy `argpartition` + stable sort when scores are finite, `heapq.nlargest` otherwise (#1491, hence the direct numpy import) |
| `retrieval/indexer.py` | Corpus ingestion, chunk sanitization (`cyclaw-index`) |
| `retrieval/embeddings.py` | Local embeddings, CPU-only (`EMBED_DEVICE`, cross-platform determinism); triple `lru_cache`; `embedding_fingerprint()` for index staleness |
| `retrieval/rerank.py` | Local cross-encoder (`models.reranker`, shipped `cross-encoder/ms-marco-MiniLM-L6-v2`, CPU, raw logits) behind the vault-hit veto (#1456): `route_by_score_node` compares the best logit to `retrieval.min_rerank_score` (shipped `null` = shadow, audited as `rerank_best`). Fail-soft (`rerank_degraded`); not called by `hybrid_search`, so MCP never pays for it; same offline rule as the embedder |
| `retrieval/stemmer.py` / `vector_store.py` / `clear_cache.py` | Porter stemmer + custom vocab (no NLTK punkt); pluggable embedded ChromaDB (default) or pgvector store; dry-run-by-default embedding-cache cleaner (`cyclaw-clear-cache`) |
| `llm/client.py` | `LocalLLMClient` + `GrokClient` + `ClaudeClient`; bounded-retry `_post_with_retry` honors `Retry-After` and caps every POST at the remaining `api.graph_timeout_sec` budget (`set_graph_deadline` ContextVar, #1359) |
| `utils/sanitizer.py` | Injection filter; patterns in `config.yaml` |
| `utils/personality.py` / `personality_db.py` | Soul versioning, SHA-256 drift detection, injection gate on write; DB backend SQLite by default, Postgres via `CYCLAW_DB_URL` |
| `utils/logger.py` | Audit JSONL (written on the caller's thread, I4): keyed HMAC-SHA256 query fingerprints (key from `CYCLAW_QUERY_FINGERPRINT_KEY` or the private file at `policy.privacy.query_fingerprint_key_file`, created on first use), recursive PII redaction, then a fail-soft projection of the **already-redacted** record into the Numbat stream. The app log and gateway console write from one bounded writer thread (`logging.max_queued_records`, `logging.drain_wait_sec`; a full queue drops and counts) |
| `utils/numbat_emitter.py` | Derived NDJSON stream `logs/numbat-events.ndjsonl` (`numbat:` ships **enabled** — this file only; the hook and CEL monitor ship off and nothing scores it at runtime, #1458). Action plane (`emit_numbat_event`/`emit_numbat_command`) + mainline plane (`project_audit_record`); keep `_AUDIT_ACTION_PLANE_EVENTS` in step with the emit sites. Stdlib-only, never raises; one bounded writer thread (`numbat.write_wait_sec`, `numbat.max_queued_writes`) |
| `utils/ratelimit.py` | Per-IP rate limiting; in-memory / SQLite / Postgres |
| `utils/errors.py` / `config_validation.py` / `ops_runner.py` | Typed exception hierarchy rooted at `RAGError`; boot-time config validation that fails fast; the subprocess shim behind `/ops/*` |
| `utils/health.py` | `check_all()` behind `/health`; probes Grok/Claude only when `api.health_probe_external_providers` (ships **false**) and the key is set. Concurrent calls share one probe set, snapshots cache 2 s (`_status_ttl_sec`, #1490); probe errors are fixed strings (`_public_probe_error`, #1492) |
| `utils/guardrail_bridge.py` | Builds the `guardrail_input`/`guardrail_output` callables and Phase 3 `generate_guard`, or `None` when disabled; the only path from `graph.py` to `guardrails/` |
| `utils/endpoint_trust.py` | Destination allowlist for generation clients: `assert_local_destination` (loopback or `models.local_llm.trusted_hosts`, ships `[]`); `assert_online_destination` pins `api.x.ai`/`api.anthropic.com` and re-refuses `confirmed is False` — an I3 backstop, not a replacement. Denials are typed `ENDPOINT_TRUST:` errors |
| `utils/external_pre_hook.py` | Deny-only pre-action hook after the I3 gate allows a call (`policy.fallback.pre_action_hook`, ships off). Engines `command` (JSON on stdin, exit 0 allow / 2 deny) or `numbat`; enabled, anything but an explicit allow denies, each verdict audited with a `reason_code`; `verdict_mode` accepts only `enforce` (#1458) |
| `utils/numbat_gate.py` | The hook's `numbat` engine: a schema-0.3.0 `network.indicator` event through the pinned `numbat 0.2.0` CLI (`rules test --no-builtin-rules`, `policy.fallback.pre_action_hook.numbat.rules_dirs`); an `enforce: true` match or any engine failure denies. Subprocess only; `docs/security-philosophy/numbat_pre_action_gate.md` |
| `utils/authn.py` / `authn_store.py` / `authn_manager.py` / `authn_cli.py` | Pure auth primitives (scrypt, lockout arithmetic, session/CSRF/device-token ids); SQLite/Postgres `users`/`sessions`/`device_tokens` under its own `CYCLAW_AUTH_DB_URL`; `AuthManager` (bootstrap, login/logout, sessions, device tokens, no HTTP awareness); `cyclaw-user` CLI (`add`/`list`/`role`/`disable`/`enable`/`passwd`/`token …`), local-only by construction |
| `utils/console_session.py` | Console operator session: stateless HMAC cookie keyed off `CYCLAW_API_KEY` plus its CSRF token, minted for the key or a launcher's single-use pairing code (`CYCLAW_CONSOLE_PAIRING_CODE`, popped at gate import). Stdlib only; `require_api_key` is the only consumer |
| `utils/gen_cert.py` / `schemas/api.py` | `cyclaw-gen-cert` openssl wrapper for a self-signed cert with hostname/LAN SAN; Pydantic models (`extra='forbid', strict=True`) |
| `metrics.py` | `cyclaw-metrics`: `audit.jsonl` analyzer, Spend section from `logs/spend.jsonl` (tokens, no query text), offline Sequences section (`utils/sequence_detect.py`). Forensic only — not imported by the core six |
| `mcp_hybrid_server.py` | MCP server: `hybrid_search` only, no LLM, `sampling: None` |
| `sync/` | Out-of-band Dropbox corpus sync (`python -m sync.cli`) |
| `agentic/` | Out-of-band GitHub context + governed skills registry (`python -m agentic.cli`); connectors `fsconnect/` (local/SMB filesystem, POSIX held-fd core; macOS installer enables list/stat/read for `~/CyClaw-FS` only), `sqlconnect/` (SELECT/WITH-only guard), `netconnect/` (passive LAN inventory over explicit RFC1918/loopback CIDRs, no active probes) |
| `agentic/real_repo_loop.py` | Plan → patch → verify → (human decides) → commit against a jailed clone. CLI-only (`real-repo-run*`; `OpsAgenticRequest.action` rejects them, so no HTTP route; `docs/agentic/AGENTIC_README.md` §9). Push/PR gated (`allow_git_write_tools` and `agentic.enabled` ship false) |
| `agentic/executor/` | Verification in disposable gitless copies (no copyback, scrubbed env, bounded duration) under a required `production_sandbox()`: Darwin Seatbelt or Linux bubblewrap namespaces; Windows and missing capabilities fail closed. Not a microVM or host-read isolation boundary (`docs/THREAT_MODEL.md`) |
| `agentic/deepagent_github/` | Live: `RepoWorkspaceTools` (jailed clone/read/write/commit/push) and the cloud planner; **retired** 2026-07-31: `builder.py`'s DeepAgents subgraph. Both gated off by default |
| `guardrails/` | Enabled by default with required but soft-imported NeMo: offline rails guard local input and output, and the broker wraps every answer node with `check()` or deterministic input/soul-leak checks on degradation. Grounding stays `local_llm` only; no LLM-backed rail is active |
| `telegram/` / `opentweet/` | Out-of-band channels (`python -m telegram.cli`, `python -m opentweet.cli`), both shipped off and reaching the RAG only via loopback `POST /query`. Telegram: only `/online on <grok\|claude>` (with `allow_hybrid_confirm`) can set `user_confirmed_online`. OpenTweet: always `user_confirmed_online: false`, default write is a draft. `docs/channels/` |

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
verifies all six statically; run it after any core-file change.

| # | Invariant | Enforced in | Locked by test | You violate it if you… |
|---|---|---|---|---|
| I1 | **RAG-first** — `retrieve` is the unconditional entry; no LLM call precedes retrieval | `graph.py` `set_entry_point("retrieve")` | `test_graph` | answer before `retrieve` runs |
| I2 | **Topology = policy** — routing is graph edges only, never an LLM or ad-hoc `if` | `graph.py` `score_router`/`guardrail_router`/`user_gate_router`/`pre_action_hook_router` | `test_graph` | decide routing outside the four routers |
| I3 | **Triple-gated external fallback** — a Grok or Claude call needs `mode=="hybrid"` AND `<provider>.enabled` AND `user_confirmed_online` for the selected `online_provider` | `gate.py` construction + `graph.py` `user_gate_router` | `test_graph`, `test_gate` | reach `grok_fallback`/`claude_fallback` without all three |
| I4 | **Audit convergence** — all eleven upstream paths reach `audit_logger` before END | `graph.py` edges | `test_graph` | add a path to END that skips `audit_logger` |
| I5 | **Soul governance** — soul mutation requires a human `reason`; writes are atomic | `utils/personality.py` `apply_evolution` | `test_personality` | write `soul.md` without a `reason`, or bypass `PersonalityManager` |
| I6 | **Module isolation** — the core six (`gate.py`/`gate_ops.py`/`gate_auth.py`/`gate_memory.py`/`graph.py`/`mcp_hybrid_server.py`) never import `agentic`/`sync`/`guardrails`/`telegram`/`opentweet`, and vice versa | import graph | invariant-guard I6; `test_agentic_isolation` (AST, both directions) | `import agentic` (etc.) in the core six |

Supporting guards (also checked by `invariant-guard`): telemetry-kill ordering
across 14 files (G1 — gate.py's `_TELEMETRY_KILL` anchor, the five out-of-band
package `__init__.py` files, and eight module-level appliers all apply the kill
before any third-party import); unset `CYCLAW_API_KEY` fails **closed** (G2);
the sanitizer contract phrases stay caught (G3); BM25 stays JSON — pickle = RCE
(G4); MCP declares `sampling: None` (G5).

**Before touching `gate.py`, `soul.md` handling, or the scanner, read
`INVARIANTS.md`.** It records which guarantees are code vs. convention (two of
the three external-provider gates live in `gate.py` construction; the soul scan
is write-path-only) and names the test that pins each
(`tests/test_due_diligence_invariants.py`).

## 4. Mistakes You Will Make Here (and the rule that prevents each)

### Environment & install
- **Trap:** installing Torch from the general dependency input pulls a CUDA build.
  **Rule:** install `torch==2.13.0+cpu` from the PyTorch CPU index **first**,
  then the hashed runtime lock and constrained test tools (§8).
- **Trap:** running that torch line on macOS, or "fixing" the `+cpu` pin when
  it 404s there. **Rule:** macOS needs **plain** `torch==2.13.0` (no `+cpu`
  wheel for Apple Silicon); use the §8 macOS block and its hashed lock.
- **Trap:** moving the torch pin and touching only `requirements.txt`/
  `constraints.txt`. **Rule:** `environment.yml` (conda, `pytorch=2.13.0=cpu*`)
  is a fourth surface, CI-gated by `python-package-conda.yml` and dep-guard D9;
  bump it in the same commit.
- **Trap:** running `cyclaw-server`/`cyclaw-index`/`cyclaw-metrics` after only
  `pip install -r requirements.txt`. **Rule:** those `[project.scripts]` shims
  exist only after `pip install -e .`; the `python -m …` forms always work.
- **Trap:** running `pytest` in a fresh container, or assuming its `python3` is
  3.12. **Rule:** a fresh clone has NO Python deps, and on `sandbox-ccr-default`
  bare `python3`/`pip3`/`pytest` resolve to 3.11, under which `test_agentic_*`
  fails 142 tests (`shutil.rmtree(onexc=...)` is 3.12+) — easy to mistake for a
  red `main`. Build a venv outside the repo each session
  (`python3.12 -m venv /root/.venv-cyclaw-312`, install with its `pip`, run
  `/root/.venv-cyclaw-312/bin/python -m pytest ...`); `driver.sh venv` (the
  `cyclaw-gotchas` skill) does this and handles a proxy-denied
  `download.pytorch.org`. Never change the system `python3`
  (`update-alternatives`): the runtime's own hooks resolve through it.
- **Trap:** assuming the server refuses to boot without `GROK_API_KEY`, or
  treating `status: degraded` in `/health` or `TELEMETRY KILL` on startup as
  errors. **Rule:** it boots with Grok unavailable (tests only need
  `GROK_API_KEY=dummy`); both messages are normal (no Ollama; intentional env
  blocking).

### Boot semantics
- **Trap:** adding a hard failure when `data/personality/soul.md` is missing.
  **Rule:** it **self-heals** — `PersonalityManager._load_soul` writes a default
  and records a version. The baseline is the newest `soul_versions` DB row
  (there is no `soul_hash` constant).
- **Trap:** expecting the server to build the index on first run.
  **Rule:** a missing index is fail-soft (`/query` → 503 `INDEX_NOT_FOUND`);
  build it with `python -m retrieval.indexer`.
- **Trap:** assuming no `CYCLAW_API_KEY` means soul endpoints are open.
  **Rule:** unset key = **fail closed (401)** for every key-based credential,
  compared with `hmac.compare_digest`; only an enabled admin's login (with
  `auth.enabled`) passes without it (`INVARIANTS.md` Rule 6).
- **Trap:** reordering imports in `gate.py` "to tidy them," or dropping the
  `_TELEMETRY_KILL = ...` assignment. **Rule:** that block MUST stay above the
  heavy imports (`graph`, `retrieval`, `langchain`, `chromadb`);
  `test_telemetry_kill` locks it and G1 finds the name by **AST**. Same for
  `mcp_hybrid_server.py`'s `apply_telemetry_kill()` — its `# noqa: E402`
  imports are load-bearing.
- **Trap:** assuming `Settings(anonymized_telemetry=False)` covers ChromaDB.
  **Rule:** it covers only PostHog; chromadb's separate `otel_init()` needs
  `CHROMA_OTEL_GRANULARITY="none"`. Neither defense is redundant.
- **Trap:** "completing" `TELEMETRY_KILL` with `HF_HUB_OFFLINE`/
  `TRANSFORMERS_OFFLINE` (they appear in
  `docs/security-philosophy/cyclaw_telemetry_kill.env`). **Rule:** excluded on
  purpose: `huggingface_hub` latches `HF_HUB_OFFLINE` at import, which breaks
  the first-run model fetch. `retrieval/embeddings.py`'s `_load_model` goes
  offline (`local_files_only=eligible`) only when `_model_offline_eligible`
  finds the model cached, **or** `models.embeddings.offline_after_index`
  (default `false`) is on and the BM25 sidecar exists (`_index_or_bm25_present`,
  not the Chroma dir). `retrieval/rerank.py` applies the identical rule, so
  "cache both retrieval models" is the operator statement.
- **Trap:** treating `ORT_TELEMETRY_OPT_OUT` as a kill switch, or ORT telemetry
  as Windows-only. **Rule:** onnxruntime never reads it; since v1.29.0
  non-Windows builds carry 1DS telemetry too. The controls are
  `ORT_DISABLE_TELEMETRY=1` pre-init plus `disable_telemetry_events()`
  post-import (#1135). On Windows (ETW) absolute suppression needs a
  `--no_telemetry` build — never claim it.

### Retrieval & config
- **Trap:** "fixing" `min_score: 0.028` upward toward a cosine-like 0.5, or
  above the hybrid ceiling ~0.033. **Rule:** it is on the **RRF scale** (dual
  rank-0 with `rrf_k=60` is `2/60`) and gates only the keyword-only degrade;
  hybrid queries are decided by `min_semantic_score` on the best semantic hit.
  Do not reinstate "a chunk must rank in both legs' top-k": measured, it
  rejected answerable paraphrases (`graph.py` `route_by_score_node`).
- **Trap:** raising `min_semantic_score` to stop look-alikes (*The Medium*
  horror film matches the McLuhan chunk at cosine 0.46). **Rule:** no cosine
  floor separates them from real paraphrases; that is the cross-encoder veto's
  job (`retrieval.min_rerank_score`, **logit** scale, shipped `null`), and
  `tests/ci_rag_smoke.py` fails if it vetoes an asserted answerable probe.
- **Trap:** unifying the test mock's `min_score` (0.75) with production (0.028).
  **Rule:** both are load-bearing: mock scores straddle 0.75, production RRF
  scores straddle 0.028.
- **Trap:** a config key for the embedding cache size. **Rule:** fixed at
  import via `lru_cache`; only `CYCLAW_EMBED_CACHE_SIZE` changes it.
- **Trap:** editing `config.yaml` in a running process and expecting new
  patterns. **Rule:** the sanitizer `lru_cache`s by config path; restart
  (`enabled: true` + zero patterns silently degrades to length-only).

### Testing
- **Trap:** changing conftest `test_config` to a shallow `.copy()`.
  **Rule:** it MUST stay a deepcopy (`test_conftest_fixtures` guards it).
- **Trap:** `import gate` at a test module's top level.
  **Rule:** that triggers full app init; use a subprocess
  (`test_telemetry_kill`) or module-level patching (`test_gate`).
- **Trap:** seeing local `pytest` green and assuming coverage passed.
  **Rule:** bare `pytest` runs **no** coverage; the 80% `fail_under` applies
  only with CI's explicit `--cov=` flags, one per `[tool.coverage.run] source`
  entry. A new **top-level** package/module must be added to `pyproject.toml`
  and both CI lanes (`tests/test_ci_coverage_flag_contract.py` fails on drift);
  new test files auto-discover.
- **Trap:** assuming `pytest tests/` ran `tools/lora_finetune/tests/`.
  **Rule:** `testpaths = ["tests"]` excludes it (CI: `lora-finetune.yml`); run
  it when that tree is in the diff (§8).
- **Trap:** renaming `ci_rag_smoke.py` to `test_ci_rag_smoke.py`.
  **Rule:** it is deliberately not `test_*`-named: it is its own CI step, and
  renaming drags ChromaDB into the unit lane.
- **Trap:** a fresh `MockGrokClient` to simulate "no API key."
  **Rule:** it defaults `available=True`; pass `available=False`.
- **Trap:** a unit test building a real `HybridRetriever` from the **shipped**
  `config.yaml`. **Rule:** that enables `models.reranker`, so `retrieve_node`
  downloads the real cross-encoder (~91MB). Fake
  `retrieval.rerank._load_cross_encoder` or turn the reranker off, as
  `tests/test_rag_integration.py` and conftest's `TEST_CONFIG` do.
- **Trap:** trimming `banned_patterns` and expecting a count test to catch it.
  **Rule:** no test asserts `== 40`; `TestShippedConfigContract` runs specific
  **phrases** against the real config. Adding patterns is safe.
- **Trap:** adding a state-changing POST route without touching the console
  contract. **Rule:** `test_terminal_contract` extracts routes from
  `terminal.html`; add new POST endpoints to its `_POST_PATHS`.
- **Trap:** treating `mypy --strict` as clean or as a CI gate. **Rule:** it is
  neither: only `lint.yml` runs ruff (F/B/S blocks) and no workflow runs mypy.
  The bare repo-root run errors on `utils/errors.py` ("found twice") because
  `utils/` has no `__init__.py` — add `--explicit-package-bases` — and legacy
  untyped code remains. Check only the lines you wrote.

### Code conventions
- **Trap:** `raise Exception(...)` or a bare `except:`.
  **Rule:** raise a typed error from `utils/errors.py` (rooted at `RAGError`
  with `.code`/`.message`/`.details`); out-of-band subsystems use their own
  subtrees. `RcloneTimeoutError` deliberately bypasses its parent `__init__`
  to keep its sub-code.
- **Trap:** changing an error `code` string or the `"{code}: {message}"` stamp.
  **Rule:** asserted verbatim in `test_graph`. Success paths never emit an
  `error` key (it would clobber an upstream error).
- **Trap:** a generic `sys.exit(1)` from a CLI.
  **Rule:** exit codes are an API: agentic `0` ok · `2` failed · `3`
  env/config · `4` write refused; sync `10` = corpus changed → reindex;
  `clear_cache` `0`/`2`/`3`.
- **Trap:** "optimizing" the BM25 store to pickle.
  **Rule:** BM25 stays JSON (`index/bm25.json`); pickle is RCE. `test_security`
  guards it.
- **Trap:** logging raw query text "for debugging."
  **Rule:** the audit log stores keyed HMAC fingerprints only (while
  `include_query_hash: true`); `test_gate` enforces it.
- **Trap:** treating MCP `hybrid_search` as unsanitized.
  **Rule:** it runs `check_input` before retrieval (E3, #974; same patterns and
  `max_input_chars` as `/query`) and audits `prompt_injection_blocked`.
- **Trap:** re-reading `config.yaml` inside a module, or cwd-relative paths.
  **Rule:** config is loaded once and passed down as `cfg`; paths anchor to
  `_BASE_DIR`/`_REPO_ROOT`, never cwd.

### Dependencies
- **Trap:** bumping `pydantic-core` alone, or adding `[standard]` to the uvicorn
  constraint. **Rule:** `pydantic` and `pydantic-core` are lock-step
  (2.13.5 ↔ 2.46.5); the `uvicorn` constraint carries no extras (pip ≥26.1.2
  rejects extras in a constraints file).
- **Trap:** letting numpy float to 2.x. **Rule:** numpy is pinned `<2`
  (dependabot ignores `numpy>=2.0.0`; numpy 2 breaks chromadb/onnxruntime) and
  is a direct import since #1491, so `verify-deps` E7 treats it as runtime.
- **Trap:** "fixing" the chromadb CVE. **Rule:** it is risk-accepted,
  embedded-`PersistentClient`-only per the threat model. Do not switch to the
  HTTP client or file a fix PR.

### Git & PR
- **Trap:** pushing to `main` via the GitHub MCP while a feature branch + open PR
  exist, or force-pushing after a rebase without asking. **Rule:** never —
  branch → draft PR → human merges, and `--force-with-lease` needs explicit
  user sign-off (the session runtime and the tracked pre-push hook both block
  it otherwise).
- **Trap:** a commit refused by the tracked `.githooks/` (branch prefix,
  `[prefix] - subject` title, a secret or private path in the diff, a protected
  path such as `utils/sanitizer.py` or `gate_auth.py`). **Rule:** that gate is
  working as designed (`docs/GITHOOKS.md`). Fix the branch name, subject, or
  diff; never set its operator overrides (`HOOK_OPERATOR_ACK`,
  `ALLOW_MAIN_PUSH`, `ALLOW_FORCE_WITH_LEASE`) or pass `--no-verify` yourself —
  stop and ask.
- **Trap:** two branches editing the same shared file (`ci.yml`, `config.yaml`,
  manifests, `CLAUDE.md`) from the same base. **Rule:** trial-merge the pair
  locally before opening PRs.
- **Trap:** diagnosing a child PR's red CI as the PR's fault.
  **Rule:** a red `main` poisons every branch cut from it. Check `main` first.
- **Trap:** opening a draft PR and going dark, or polling beside a live
  subscription. **Rule:** subscribe to its activity events at creation when the
  runtime offers it (`subscribe_pr_activity`) and drive it to green until
  merged or closed; runtimes without event delivery (e.g. Kimi via `gh`) check
  CI once after push, then hand the watch to the operator. Events are the
  signal: at most one long-fuse (4–6h), non-re-arming safety sweep per session,
  and every agent dedups against open PRs before implementing.

---

## 5. Conventions

### Code
- **Python 3.12** (`requires-python >=3.12`). Fully type-annotated; PEP 604
  unions (`str | None`), builtin generics, `TypedDict`/`Protocol`/`Literal` over
  `Any`. `from __future__ import annotations` in new modules.
- **Lint:** `lint.yml` blocks on `ruff check --select F,B,S .`; the broader
  `--select E,F,I,B,C4,UP,S --ignore E501` pass and WPS are advisory, but keep
  them clean locally (line length 120, `.claude` excluded; always pass
  `--ignore E501` with `--select E`). **Types:** `mypy --strict
  --python-version 3.12 --explicit-package-bases` on the lines you write
  (best-effort, §4).
- **No `print`** in library code — `logging.getLogger("cyclaw.<module>")` with
  lazy `%s` formatting. Audit is a separate JSONL stream.
- **No `shell=True`** with user input; always `subprocess.run([...])` list-form.
- **No secrets in code** — env vars only. **No TODO/FIXME comments**; encode
  intent in "why, with PR reference" comments.
- Data-modifying scripts default to a safe dry-run (`--apply` to act).

### Verification policy (run code, lint, let Actions run the suites)
Owner decision, 2026-10-08, for local and cloud sessions alike. Verify a
change in this order and stop at the first step that actually exercises it:
1. **Run the code.** Execute the changed function, script, or endpoint
   directly (`python -I -c ...`, a small probe script, `bash script.sh` against
   a scratch repo, `curl` against a running `gate.py`) and look at the real
   output. A failing-then-passing probe is the evidence.
2. **Lint and static checks.** `ruff`, `bash -n`/`shellcheck`, `actionlint`,
   and the `.claude/skills/*/check_*.py` checkers (§8).
3. **GitHub Actions.** Push the draft PR and let CI run the suites and the
   coverage gate; read the result instead of reproducing it locally.
4. **One targeted test file**, only when steps 1-3 cannot exercise the path.

Do **not** run the full suite (`pytest tests/`), the CI-style `--cov` run, or
`tools/lora_finetune/tests/` as a routine step. This changes how agents verify,
not what is enforced: CI still runs the full suites, the 80% `fail_under` and
the four test legs as release gates. Say plainly in the PR body which checks
you ran directly and which only CI has run.

### Commits, branches, PRs
- **Commit subjects** follow the PR template's title format, enforced by the
  tracked `commit-msg` hook: `[prefix] - Short descriptive sentence` with
  `prefix` one of `invariant`, `governance`, `fsconnect`, `agentic`, `rag`,
  `harness`, `security`, `docs`, `infra`, `fix`, `feat`. Dependabot/Renovate
  `chore(deps)`/`build(deps)`/`ci(deps)` subjects and merge/revert/fixup
  subjects pass as-is.
- **Branches:** short-lived, vendor-prefixed (§10 table), deleted after merge;
  never develop on `main`.
- **PRs are draft**, one reviewable concern each, body populated from
  `.github/PULL_REQUEST_TEMPLATE.md`. A human decides when to merge.
- **Watch what you open — by events, not polls** (§4 Git & PR).

### Docs
- Dated audit/report docs go in `docs/audits/`; live memory lives ONLY in
  `docs/memories/` (do not re-create `.claude/memory/`, deleted in #1351).
- Every `##` section must be self-contained — the corpus is chunked and
  searched section-by-section.
- Don't duplicate another doc's authority; link to it. `config.yaml` owns the
  numbers — cite, don't copy-and-drift.

### Kimi Code agents
- This manual applies verbatim to Kimi Code sessions; branches use
  `kimi/<topic>`, and the PR body is the template, not an ad hoc
  What/Why/Verification shape (root-caused 2026-07-28).
- **`gh` trap (Windows operator machine):** bare `gh` on PATH is a py3dot12
  shim, NOT GitHub CLI. Call `"/c/Program Files/GitHub CLI/gh.exe"`
  (authenticated as `cgfixit`). Kimi has no GitHub MCP tools and no session
  stop-hook — use `gh` and the user's own git identity.
- **Optimize skill:** the Kimi port of `.claude/skills/CyClaw-Optimize/` lives
  at `~/.agents/skills/cyclaw-optimize/`; the in-repo skill is canonical.

---

## 6. Quality Bar per Deliverable (checkable criteria, not adjectives)

A deliverable is done only when its box is fully checked.

**Code change**
- [ ] `ruff check --select F,B,S .` clean (CI-blocking); the broader
      `E,F,I,B,C4,UP,S --ignore E501` set clean locally (advisory)
- [ ] `mypy --strict --python-version 3.12 --explicit-package-bases` clean on
      the lines you wrote (best-effort, §4)
- [ ] the changed code was run directly and its real output checked (§5); no
      full-suite run is expected locally
- [ ] CI is green on the pushed head (full suites, plus
      `tools/lora_finetune/tests/` when that tree is in the diff) and the 80%
      coverage gate was not lowered
- [ ] no new dependency without an exact pin in `pyproject.toml` AND
      `constraints.txt`; the diff touches only files named in the task
- [ ] each of the six invariants is untouched, OR the change is argued
      explicitly in the PR body; `check_invariants.py` exits 0

**Test**
- [ ] uses `tests/conftest.py` fixtures; starts no live service
- [ ] asserts behavior/contract, not incidental implementation detail
- [ ] deterministic — no real `sleep` racing a timeout, no network, no clock
- [ ] discovered by pytest without editing `ci.yml`

**Pull request**
- [ ] draft; `[prefix] - subject` title; body follows the PR template; one
      concern, reviewable in one sitting
- [ ] if it shares a file with another open PR, a local trial-merge was verified
- [ ] CI green, or each failure explained against `main`'s own state

**Documentation**
- [ ] every number sourced from `config.yaml`/`pyproject.toml`; `##` sections
      self-contained; dated if it is a report
- [ ] `python3 .claude/skills/doc-sync/doc_sync.py` shows no new drift it caused

**Skill**
- [ ] YAML frontmatter (`name`, `description`); numbered steps with exact
      commands; a Guardrails section restating the relevant invariants; a
      Gotchas section
- [ ] a self-contained `verify.sh` if it ships an executable (CI auto-runs it,
      non-blocking) — exits 0 when healthy and skips cleanly without deps

---

## 7. When Uncertain — Escalation Rules

| Tier | Concrete triggers | Required action |
|---|---|---|
| **Low** | Local, reversible, narrow: format, add a test, fix a doc typo, read code, run a documented command | Proceed |
| **Medium** | Shared code path, recoverable: edit a module's logic, change a fixture, refactor within one subsystem | Proceed; expand tests; state the rollback path in the PR body |
| **High** | Irreversible or broad: destructive command, force-push, `soul.md` mutation, a graph edge / auth / sanitizer pattern, weakening any test, a new runtime dependency, any security invariant | **Stop and ask first** |

When unsure which tier, choose the higher one.

**Always ask first (High):** deleting/overwriting files you didn't create;
force-push; `git push` to `main`; mutating `soul.md`; changing graph edges,
`banned_patterns`, or auth; loosening a test or the coverage gate; adding a
runtime dependency; wiring a new hook in `settings.json`; setting a
`.githooks` operator override or passing `--no-verify`.

**Never ask:** the documented test/lint/run commands; reading anything; adding
tests; fixing doc typos; `ruff format`; the `.claude/skills/*/check_*.py` or
`verify.sh` checkers.

**Mid-task ambiguity:** state your assumption, proceed on the **smallest
reversible** interpretation, and flag it in the PR body — do not stall. Ask
only when the readings diverge on something irreversible or a matter of taste.

**Blocked:** record it in `docs/work/SESSION_NOTES.md` and escalate
(`#cyclaw-dev`; a private GitHub security issue for security concerns;
`/CyClaw-Sandbox` for suspected config drift).

Do NOT: re-ask an answered question; ask the user to reveal a secret; change
code behavior to make a stale doc "true" (fix the doc, or flag the gap).

---

## 8. Commands That Work

Skills reference this section; keep it the single canonical copy.

```bash
# Install — Linux (order matters — torch CPU FIRST)
pip install --require-hashes --no-deps -r requirements-torch-lock-linux.txt --index-url https://download.pytorch.org/whl/cpu
pip install --require-hashes -r requirements-lock-linux.txt
pip install -r requirements-test.txt -c constraints.txt

# Install — Windows (both lock files are platform-specific)
pip install --require-hashes --no-deps -r requirements-torch-lock-windows.txt --index-url https://download.pytorch.org/whl/cpu
pip install --require-hashes -r requirements-lock-windows.txt
pip install -r requirements-test.txt -c constraints.txt

# Install — macOS (Apple Silicon): plain torch, then the arm64 macOS lock.
pip install --require-hashes --no-deps -r requirements-torch-lock-macos.txt
pip install --require-hashes -r requirements-lock-macos.txt
pip install -r requirements-test.txt -c constraints.txt

# Install — conda (fourth surface)
conda env create -f environment.yml

# Console scripts (cyclaw-*) need the project itself installed
pip install -e . -c constraints.txt

# Once per clone: point git at the tracked hooks (the cloud SessionStart hook runs it)
bash scripts/ensure-githooks.sh

# Build the retrieval index (required before /query returns hits)
python -m retrieval.indexer            # or: cyclaw-index

# Tests (GROK_API_KEY must be any non-empty value). Per §5 agents do NOT run
# the full suite or the --cov run; these are for the owner, CI, or step 4.
GROK_API_KEY=dummy pytest tests/ -q --tb=short   # full suite: CI/owner only
GROK_API_KEY=dummy pytest tests/test_graph.py -q --tb=short   # single file
GROK_API_KEY=dummy pytest tests/test_agentic_*.py -q          # agentic only
GROK_API_KEY=dummy python tests/ci_rag_smoke.py               # real-index RAG smoke
GROK_API_KEY=dummy pytest tools/lora_finetune/tests/ -q --tb=short  # not under testpaths

# Lint / types (Ruff F/B/S blocks in CI; the rest is advisory)
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

CI targets Python 3.12 on four `test` legs (ubuntu-latest, ubuntu-22.04 for the
AppArmor-profiled bwrap policy, windows, macos), all release gates. In `ci.yml`
only `verify-skills` carries `continue-on-error`; advisory lanes elsewhere are
`lint.yml`'s broader-Ruff and WPS steps and best-effort steps in the
nemo-guardrails/pr-review/conda/trivy workflows, while every `numbat-rules.yml`
job blocks (#1458). Coverage sources: `gate`, `gate_ops`, `gate_auth`,
`gate_memory`, `graph`, `mcp_hybrid_server`, `metrics`, `llm`, `retrieval`,
`utils`, `sync`, `agentic`, `guardrails`, `telegram`, `opentweet`, `memory`,
`schemas`. `tests/conftest.py` mocks all external deps; `tests/` holds about
230 auto-collected `test_*.py` files, including `tests/nemo_runtime/` and
`tests/security/`.

---

## 9. Skills

Skills live at `.claude/skills/<name>/SKILL.md`; when one is missing from the
local sandbox, **check GitHub main before declaring it absent**. Skills marked
`disable-model-invocation: true` ("user-invoked only" below) are reachable only
as slash commands (`.claude/commands/<name>.md`); CI and other skills still run
their scripts directly.

### CyClaw-specific security & health skills (built on the invariants)

| Skill | Type | Purpose | Runs pre-install? |
|---|---|---|---|
| `/invariant-guard` | check, user-invoked only | Static-assert the six invariants + guards against a diff | Yes (stdlib) |
| `/dotenv-guard` | check, user-invoked only | Keep secrets out of dotenv files, gitignored or not (no runtime dotenv load, tracked env files, `.gitignore` coverage, a sandboxed `setup-cyclaw-keys.sh` run, script/doc line checks; baseline ratchet). Blocking CI job | Yes (stdlib + git + bash) |
| `/config-guard` | check, user-invoked only | Static-validate config.yaml's relational/value/threat-model contract (graph_timeout>llm_timeout, chunk_overlap<chunk_size, RRF-scale min_score, loopback host, shipped posture, `api_key_optional` vs. the bind address) | Needs PyYAML |
| `/dep-guard` | check | Dependency-pin invariants across pyproject + constraints + environment.yml (pydantic lock-step, numpy<2, torch +cpu, uvicorn no-extras, cross-file agreement) | Yes (stdlib) |
| `/verify-deps` | check | Extends dep-guard: requirements.txt cross-check, non-manifest drift E1–E7, an install dry-run per surface, and a PyPI currency + CVE sweep. Reports only — never auto-bumps | extract_pins.py + check_env_drift.py yes; sweep needs network |
| `/injection-redteam` | loop | Adversarial probe corpus vs the sanitizer; close bypasses | Needs venv |
| `/index-doctor` | check, user-invoked only | Rebuild + validate ChromaDB/BM25/RRF; probe retrieval health | Needs venv |
| `/doc-sync` | check, user-invoked only | Detect code↔docs drift; reconcile the docs | Needs PyYAML |
| `/otel-hardening` | check + task | Telemetry-kill contract: independent oracle over both maps + scrub set, process-boundary delivery, ONNX seams, and a category-1–5 egress classification (strict fails on an unclassified component); then a live vendor-doc sweep. A new `subprocess` spawn site must add its binary to `check_otel.py`'s `KNOWN_EXTERNAL_COMPONENTS` | Static half yes; sweep needs network |

### Operational & workflow skills

| Skill | Type | Purpose |
|---|---|---|
| `/babysit-github-pr` | loop, user-invoked only | Watch a PR end-to-end: triage CI/review, stop on rebase conflicts, never rewrite a behind branch without explicit `ALLOW_FORCE_WITH_LEASE=true` |
| `/CyClaw-Optimize` | task, user-invoked only | Scan main for optimizations; open focused draft PRs |
| `/CyClaw-Sandbox` | task, user-invoked only | Clone/current-checkout audit: six verification ladders, in-process RAG checks, live gate/platform probes. Opens no PR by itself. `/run` = Quick Mode |
| `/architecture-refactor` `/speed-refactor` `/tests-refactor` `/logging-refactor` | loop, user-invoked only | Iterative refactor loops |
| `/add-comment` | task, user-invoked only | Comment-only pass adding ELI5-toned WHY comments to under-documented code |
| `/karpathy-guidelines` | mode | Anti-overcomplication guardrails: surgical diffs, surfaced assumptions, verifiable success criteria |
| `/cyclaw-privacy` | mode, user-invoked only | "Legal" persona for privacy/DPA/DSR/breach review of CyClaw changes (distinct from `.codex/skills/cyclaw-advisor`) |
| `/cyclaw-gotchas` | reference + driver | Session-tested sandbox traps plus `driver.sh` (`inventory`/`venv`/`serve`/`probe`/`stop`/`test`/`checks`). Model-invocable on purpose: load it before installing deps, running tests, launching `gate.py`, or driving a PR |

### Standalone commands and agent skills

`/audit`, `/check-soul`, `/conversation-summary`, `/run`, and `/status` are
inline procedures wired only as `.claude/commands/*.md` (tracked in
`.claude/README.md`). `/verification-specialist` and `/documentation-guide`
are agent skills. The session-hygiene wrappers, memory-lifecycle trio, and
`/python-coding-agent` were deleted in #1351 with the hooks that invoked them,
so nothing persists session memory to `docs/memories/` automatically.

### Cross-repo behavioral skill

`/fable-protocol` — reasoning-discipline, epistemic-calibration, and
knowledge-handoff layer, registered here and at user level
(`~/.claude/skills/fable-protocol/SKILL.md`). It carries no independent
authority: `CLAUDE.md` and `config.yaml` remain the source of truth, and
nothing in it overrides §3. It is `disable-model-invocation: true`; the
`fable-protocol-loader.sh` SessionStart hook injects it for Sonnet-tier models
only (§10), every other model reaches it via explicit `/fable-protocol`.

---

## 10. Session Protocol

**Start.** Three SessionStart hooks run. `session-start-sync-check.sh` points
`core.hooksPath` at the tracked `.githooks/` (via `scripts/ensure-githooks.sh`,
idempotent, never overriding a deliberate hooks path), drops a stale
`CyClaw Agent` identity pin, and reports local↔remote divergence; it never
resets, rebases, pushes, or deletes, and always exits 0.
`fable-protocol-loader.sh` injects `/fable-protocol` only when the stdin model
id contains `sonnet` (Opus, Haiku, Fable, and unknown ids are skipped; a
mid-session `/model` switch fires no hook). In the cloud only,
`session-start-venv.sh` starts `driver.sh venv` in the background; a manual
`driver.sh venv` waits for that build instead of starting a second one.

**Git hooks.** The tracked `.githooks/` (`pre-commit`, `commit-msg`, `pre-push`,
all sourcing `_security.sh` + `security.conf`) enforce the branch-prefix
allowlist, the `[prefix] - subject` title, fresh-`origin/main` ancestry on push,
and a secrets/private-data/protected-path/main-and-force-push gate
(`docs/GITHOOKS.md`). A refusal is a finding to fix, not a hook to bypass (§7).

**Commit identity.** Claude Code commits as the runtime's identity, never as
`CyClaw Agent` (owner decision, 2026-09-26): `Claude <noreply@anthropic.com>`
in the cloud (runtime-signed, shown Verified), the operator's own identity
locally. `git var GIT_COMMITTER_IDENT` should show it before committing; a
stale pin is cleared with `git config --local --unset user.email` (and
`user.name`). CyClaw's own agentic loop uses `utils/agent_identity.py` instead,
with **driver-agnostic** defaults (`CyClaw Agent` /
`cyclaw-agent@users.noreply.github.com`, overridden by
`CYCLAW_AGENT_COMMIT_NAME` / `CYCLAW_AGENT_COMMIT_EMAIL`) that never apply to a
Claude Code session.

**Branch namespaces** (`.github/PULL_REQUEST_TEMPLATE.md`; the hooks and
`utils/agent_identity.py` accept every row):

| Driver | Branch form |
|--------|-------------|
| Claude Code | `claude/{feature}` |
| Codex | `codex/{feature}` |
| Grok Build | `grok/{feature}` |
| Kimi / Kimi Code | `kimi/{feature}` |
| CyClaw direct / MCP | `CyClaw/{feature}-{date}` (also `cyclaw/`) |
| Unknown / generic | `agent/{feature}` |

`CYCLAW_AGENT_BRANCH_PREFIX` (default `agent`) sets only the *preferred*
prefix.

The cloud **session runtime** applies a stop hook (not wired in repo
`settings.json`) that flags commits whose committer email is not
`noreply@anthropic.com` and blocks `--force-with-lease` without explicit
authorization. Re-authoring an unpushed commit is fine; rewriting a published
one is a force-push and needs the owner's sign-off.

**During.** Track compact memory: Goal, Constraints, Decisions (with one-line
rationale), Open questions, Verification state. Prefer file-backed facts over
inference.

**End.** Durable project conventions → this file or `.claude/rules/`;
session-scoped discoveries → `docs/memories/`, written by hand. Run `/doc-sync`
before you consider the session done.

---

## Reference

- Multi-agent work: the coordinator owns synthesis and final correctness;
  workers gather evidence and produce artifacts, never architectural decisions.
  Dispatch read-only research in parallel, serialize write-heavy work per file
  set, and give each worker a self-contained prompt.
- Threat model: `docs/THREAT_MODEL.md`. Agentic governance:
  `docs/agentic/AGENTIC_README.md`, `docs/agentic/SKILLS_REGISTRY_GOVERNANCE.md`.
