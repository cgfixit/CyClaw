# `utils/` — shared server-side helpers

Support modules for the core request path (`gate.py`, `graph.py`,
`mcp_hybrid_server.py`) and its operator endpoints. Deliberately **not** a
package — there is no `__init__.py`, which is why a bare repo-root
`mypy --strict .` errors with "source file found twice"; add
`--explicit-package-bases` (see `CLAUDE.md` §4 "Testing").

The authoritative one-line-per-module map lives in `CLAUDE.md` §2 "Key
modules"; this file groups them by concern.

## Security / policy

| Module | Role |
|---|---|
| `sanitizer.py` | Shared injection filter for `/query`, retrieval-only MCP, and ingestion, with the normalizer also used by soul/memory scanning and scheduled OpenTweet screening. Patterns come from `config.yaml` (`banned_patterns`), cached by config path — restart to pick up edits. Raw, Unicode-normalized, and separator-folded inspection copies are checked while accepted content stays unchanged. Malformed/non-string patterns warn and are skipped; an empty effective list leaves only the length check. `_unicode_confusables.py` is the generated Unicode table; see [`unicode_data/README.md`](unicode_data/README.md). |
| `secret_policy.py` | Reads the inert, versioned `utils/secret-policy.tsv` (exact names → keystore service, plus classified suffixes) shared with the bash and PowerShell loaders, so one file decides what counts as a secret everywhere. |
| `child_environment.py` | Explicit capability environments for trusted helper subprocesses: a child starts from an empty env and receives only the named variables, so a credential in the gateway never leaks to a helper by inheritance. Limits inheritance; not process isolation. |
| `public_errors.py` | Keeps filesystem layout and credentials out of HTTP diagnostics: maps internal errors to the generic bodies the gateway returns. |
| `external_budget.py` | Durable UTC daily/monthly attempt ceilings shared by the Grok and Claude transports (`policy.external_call_limits`, shipped 100/1,000, SQLite ledger at `ledger_path`); a reservation precedes every POST attempt, retries included, zero denies all, and unavailable storage refuses egress. |
| `authn.py` | Per-user authentication primitives (scrypt hash/verify, lockout arithmetic, session/CSRF/token id generation). Pure functions — no DB, no HTTP. |
| `authn_store.py` | SQLite/Postgres backend for users/sessions/device tokens (`CYCLAW_AUTH_DB_URL`). |
| `authn_manager.py` | `AuthManager` gluing `authn.py` + `authn_store.py`; no HTTP awareness. |
| `authn_cli.py` | `cyclaw-user` console script — local-only user/token admin. |
| `console_session.py` | Stateless `cyclaw_console` cookie and CSRF primitives. The cookie is signed from `CYCLAW_API_KEY`; pairing codes are single-use and expire. `gate.py` owns the HTTP routes. |
| `gen_cert.py` | `cyclaw-gen-cert` console script — wraps `openssl req -x509` to write a self-signed TLS cert with hostname/LAN SAN (Stage 4 of `docs/AUTHENTICATION_DESIGN.md`); no new runtime dependency. |
| `telemetry_kill.py` | Canonical telemetry-kill env mapping. Stdlib-only; must be applied **before** heavy imports (`invariant-guard` G1). `verify_telemetry_contract()` runs at `gate.py` boot: hash-pins the three kill maps (SHA-256 `CONTRACT_DIGEST`, independent of this file's prose) and AST-verifies every ChromaDB `PersistentClient` call in `retrieval/vector_store.py` passes `Settings(anonymized_telemetry=False)` — fails closed (raises) on drift in either. |
| `onnx_telemetry.py` | `suppress_onnx_telemetry()` — post-import ONNX Runtime API suppression at the two load seams; the env half (`ORT_DISABLE_TELEMETRY=1`) rides the kill map. |
| `guardrail_bridge.py` | I6 inversion shim supplying offline input/output checks and the generation broker to the graph. `guardrails.enabled` ships true; explicit false or an absent block returns `None` before importing the package. The broker retains deterministic checks on missing/failed NeMo verdicts and records degradation. See the [NeMo reference](../docs/NeMo/README.md). |
| `endpoint_trust.py` | Destination allowlist for the generation clients' base URLs (local → loopback, or an explicitly configured `models.local_llm.trusted_hosts` entry; Grok/Claude → their official API hosts). Defense in depth behind the triple gate — not a substitute for I3. |
| `numbat_cel.py` | Optional CEL monitor after the HTTP `/query` graph call (`numbat-cel` extra; `numbat.cel.enabled`, default-off). Evaluates already-hashed/structured result fields — never raw prompt text — and emits a low-confidence Numbat event on match when the stream is enabled; it never blocks or changes `/query`. `/health` reports evaluator/compilation readiness. `max_rule_ms` reports slow evaluation after completion; it is not a timeout. `cel-python` is lazy-imported only when enabled. |
| `external_pre_hook.py` | Synchronous pre-action hook runner behind the `pre_action_hook_grok`/`pre_action_hook_claude` graph nodes (ships off). Engine `command` runs the configured argv (exit 0 allows, exit 2 denies) or engine `numbat` delegates to `numbat_gate.py`. Once enabled, anything but an explicit allow denies, an empty command included. Every verdict carries a fixed `reason_code` (audit `pre_action_hook_reason`, `cyclaw-metrics`, optional Numbat verdict event); `hook_readiness()` feeds `/health`. |
| `numbat_gate.py` | The hook's `numbat` engine: the proposed call as a schema-0.3.0 `network.indicator` event, evaluated by the pinned `numbat 0.2.0` CLI's `rules test` against operator rule dirs. An `enforce: true` match denies; any engine failure denies. See `docs/security-philosophy/numbat_pre_action_gate.md`. |
| `numbat_emitter.py` | Derived NDJSON at `logs/numbat-events.ndjsonl`: direct action events and redacted mainline audit projections, deduplicated by `_AUDIT_ACTION_PLANE_EVENTS`. One writer thread; callers wait at most `numbat.write_wait_sec` (1 s). Full queues (`numbat.max_queued_writes`, 1,000) drop/count events. Never raises; authoritative audit remains separate. |

## Soul / audit / errors

| Module | Role |
|---|---|
| `personality.py` | Soul versioning, SHA-256 drift detection, injection scan + human-`reason` gate on write (invariant I5), atomic writes. |
| `personality_db.py` | Soul DB backend: SQLite default, Postgres via `CYCLAW_DB_URL`. |
| `logger.py` | Authoritative JSONL with recursive redaction and default HMAC-SHA256 query fingerprints; `include_query_hash: false` stores redacted text. `CYCLAW_QUERY_FINGERPRINT_KEY` overrides the private key at `policy.privacy.query_fingerprint_key_file`, atomically created on first use, never at boot. Setup rejects short env keys, invalid files/names. `hash_query` remains plain SHA-256 for integrity IDs. Redacted records project fail-soft to Numbat. Application file/stderr use a bounded writer: full queues drop/count, shutdown waits `logging.drain_wait_sec`, handlers reopen after uvicorn configuration. Agentic CLI console stays synchronous. |
| `errors.py` | Typed exception hierarchy rooted at `RAGError` (`.code`/`.message`/`.details`). Never raise bare `Exception`. |
| `spend.py` | Append-only Grok/Claude token ledger (`logs/spend.jsonl`, `logging.spend_file`). Tokens are ground truth; dollars derived at read time by `metrics.py`. Separate stream from `audit.jsonl`; never persists query/prompt content. See [`spend/README.md`](../spend/README.md). |
| `sequence_detect.py` | CLI-only audit/spend correlation by persistent HMAC `query_hash`: blocked injections followed by cloud calls within 15 minutes. Only `source == "query"`; excludes historical agentic rows. Findings contain fingerprints, events, timestamps, provider/model tags, never query/IP/soul/secret content. Core must not import it; no request policy. |

## Serving / ops

| Module | Role |
|---|---|
| `ratelimit.py` | Per-IP rate limiting; in-memory / SQLite / Postgres backends. |
| `bounded_executor.py` | Runs blocking work with a deadline that still holds after the caller gives up: the worker is bounded until it finishes, so a timed-out call cannot leave an unbounded thread behind. |
| `health.py` | `check_all()` behind `/health` probes the gateway's loaded config, including the resolved local backend and model pin. Its short-lived status cache is keyed by that config. Restart after config edits. `degraded` without the local model is normal; external-provider probes require `api.health_probe_external_providers: true` (ships false). |
| `config_validation.py` | Boot-time config validation; fails fast on a broken `config.yaml`. |
| `gateway_url.py` | Shared launcher console URL resolver: configured host/TLS plus the effective port; wildcard binds map to loopback browser destinations. Reads YAML without importing or starting the gateway. |
| `ops_runner.py` | `subprocess.run([...])` shim behind the two `/ops/*` endpoints (`/ops/sync`, `/ops/fsconnect`) — core never imports `sync`/`agentic` (I6). |
| `launchd_plist.py` | Plist helpers shared by every launchd generator: `macos/`, `telegram`, `opentweet`, `fsconnect`, and `sync/scheduler.py`'s `LaunchdScheduler`. `write_job()` builds the standard CyClaw LaunchAgent (env overlay, `RunAtLoad: false`, shared log file) and writes it atomically. Imports only the stdlib and `utils.telemetry_kill`. |
| `win_schtasks.py` | Stdlib-only Windows Task Scheduler XML helper shared by `agentic.fsconnect`/`telegram`/`opentweet`/`windows/generate_service_task.py`; never calls `schtasks /Create` itself — returns the command an operator runs by hand. (`sync/scheduler.py`'s `WindowsTaskScheduler` is separate and drives `schtasks.exe` directly, but borrows `bat_quote()` and `python_executable()` from here.) |
| `selftest.py` | Shared self-test plumbing used by the out-of-band subsystems' `test` subcommands. |
| `mcp_manifest.py` | Pure compare/verify layer for the committed MCP tools manifest pin: fingerprints the registered `TOOLS` list so drift against `mcp_manifest.json` fails closed in `mcp_hybrid_server.py`. |

## Related

- Which invariant each guarantee belongs to: repo-root `INVARIANTS.md`
- Threat model and scope: `docs/THREAT_MODEL.md`
