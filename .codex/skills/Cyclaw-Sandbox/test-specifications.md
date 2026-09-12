# CyClaw sandbox acceptance map

Use with [SKILL.md](SKILL.md). Source baseline: `3d913754` (2026-09-12).
Derive exact values and tests from the selected candidate; this map contains
acceptance criteria, not previous PASS results. Run pytest commands with the
selected Python 3.12 environment and `GROK_API_KEY=dummy` in a disposable tree.

## Removed and retained surfaces

`eb5a855f` removed `harness/`, `static/harness.html`, the `cyclaw-harness`
entry point, harness launch/service targets, its `/api/*` endpoints and
`tests/test_harness*`. The old extractor HTML/JS was removed in `c9b6b866`.
Check the source inventory and packaging manifest instead of trying to boot
these features. On the isolated gateway, confirm the removed HTML path returns
404. Do not turn `agentic/harness_optimizer/`, `tests/test_agentic_harness*`, or the
retired-but-retained DeepAgents compatibility suite into false deletion claims.

The only shipped HTML console is `static/terminal.html`. It loads
`static/terminal.js` and `static/auth_admin.js`; inspect all three for browser
contracts. The UI's Users panel is not a second server. Memory's HTML export
is a conditional gateway route, not a resurrected coding console.

## Routing, retrieval and model fidelity

| Lane | Acceptance | Source and tests |
|---|---|---|
| Topology | Retrieve first; conditional routers only; every terminal route audits. Read the actual node/edge sets. | `graph.py`; `tests/test_graph.py`, `tests/test_graph_outcomes.py`, `tests/test_due_diligence_invariants.py`; invariant-guard |
| Three external gates | Mode and provider enablement control client construction in the gateway; graph requires fresh confirmation, selected available client. Reject each missing gate independently. Destination policy and pre-action hooks add checks; neither replaces consent. | `gate.py`, `graph.py`, `utils/endpoint_trust.py`; `tests/test_gate.py`, `tests/test_graph.py`, `tests/test_endpoint_trust.py` |
| Local destination | Both local answer paths reject malformed/untrusted destinations and accept explicit trusted hosts. Trusted hosts receive context and soul; this is an operator trust grant. | `utils/endpoint_trust.py`, `graph.py`; `tests/test_endpoint_trust.py` |
| Real retrieval | Synthetic corpus, real indexer/BM25/Chroma, expected document ranking and prompt-included sources; reject corpus escapes. BM25 remains JSON. | `retrieval/`; `tests/test_hybrid_search.py`, `tests/test_rag_integration.py`, `tests/test_indexer.py`, `tests/ci_rag_smoke.py` |
| RRF parity | Same corpus, chunking, fingerprint and config on each OS. RRF contributions use `1 / (rrf_k + rank)` with rank starting at 0; use its configured score threshold and the separate cosine floor. Explain differences rather than normalizing them away. | `retrieval/hybrid_search.py`, `config.yaml`; hybrid/retrieval tests |
| MCP | Stdio retrieval-only; sanitize inputs; no LLM imports/generation. Capability metadata alone is not enforcement. | `mcp_hybrid_server.py`; `tests/test_mcp_server.py`, `tests/test_mcp_manifest.py` |

The bundled driver's five queries are two vault hits, one denied-online miss,
and two provider-confirmation misses. Evaluate the expected outcome, not the
literal prompt string. Its separate provider phase uses mocked clients/HTTP;
external answers must not inherit soul or fabricate local sources.

Report the three fidelity levels separately: in-process mocks (Tier 0), an
owned socket mock with real HTTP clients (Tier 1), and actual local model
inference (Tier 2). A `/v1/models` response alone proves neither ownership nor
inference. `run_full_verification.py` uses Tier 0 regardless of listeners.
Run `tests/test_llm_client_ollama.py` for the socket contract. A real-model run
needs a separately recorded model ID, target process and successful response.

## Gateway, terminal and auth

Discover decorators in `gate.py`, `gate_ops.py`, `gate_auth.py`, and
`gate_memory.py` (including multiline and parameterized routes). Compare the
runtime route table with the static inventory after isolated startup. Inspect
response JSON as well as HTTP status: an ops HTTP 200 can carry a failed or
disabled subprocess result.

| Surface | Checks and boundary | Maintained tests |
|---|---|---|
| `/`, `/static/*`, `/health` | Terminal HTML/JS load; CSP and frame headers; index/graph readiness separately from liveness. `embeddings_local` health is not an embedding inference probe. | `tests/test_gate.py`, `tests/test_health.py`, `tests/test_terminal_contract.py` |
| `POST /query` | Schema 422, rate 429, injection rejection, correct routes/answers, timeout/error envelope. Same-origin always; session/device token and role checks only when auth enabled. API-key success is not session-auth proof. | `tests/test_gate.py`, `tests/test_gate_query_auth.py`, `tests/test_graph_outcomes.py` |
| `POST /index/build`, `GET /index/status` | Build requires loopback/same-origin, rate limit and one-build-at-a-time; no API key by design. Status is an unrate-limited progress probe, not corpus content. Use synthetic data and verify owned process completion. | `tests/test_gate_index_build.py` |
| `/soul`, `/soul/propose`, `/soul/apply`, `/soul/reload`, `/soul/restore` | API-key refusal, reason and scan on apply, atomic replacement. Restore uses a vetted backup; reload/drift adopt trusted disk content unscanned. Do not mutate the committed or operator soul. | `tests/test_gate.py`, `tests/test_personality.py`, `tests/test_due_diligence_invariants.py` |
| `/audit/summary`, `/ops/sync`, `/ops/agentic`, `/ops/fsconnect`, `/ops/sqlconnect` | Key gate, action schema and subprocess result; disabled/mocked connectors. Test optional-key bypass only with loopback peer, no forwarding headers, non-cross-site request. | `tests/test_gate.py`, `tests/test_gate_ops.py` |
| `/auth/*` | Off returns 503; bootstrap loopback/no-proxy rules; login/session+CSRF, logout/whoami, user/password/role/disable/enable/delete policies, last-admin protection, audit role and token revocation. CLI device-token lifecycle is distinct. | `tests/test_gate_auth.py`, `tests/test_gate_auth_admin.py`, `tests/test_authn_rbac.py`, `tests/test_authn_manager.py`, `tests/test_authn_cli.py` |
| `/memory/*`, `/query/export/html` | Key-gated status; default-off subfeature gating; isolated facts/episodes/proposals, reason+scan on apply and safe HTML export. No shared operator DB. | `tests/test_memory_routes.py`, `tests/test_memory_store.py`, `tests/test_memory_policy.py`, `tests/test_memory_fusion.py`, `tests/test_memory_metadata_prompt_isolation.py` |

Browser acceptance needs desktop and mobile screenshots, completed query/error
rendering, confirmation focus handling, health/index progress, and the current
soul/ops/Users panels. Assert safe DOM rendering, same-origin requests, masked
credentials, no uncaught errors, no unexpected network destinations and no
horizontal overflow. Use `tests/test_auth_admin_contract.py` and
`tests/test_terminal_confirm_focus_trap.py` alongside browser interaction.
`browser_render_check.py` supplies screenshots and a single terminal query;
its visible container check does not cover the full matrix above.

## Audit and optional subsystems

| Lane | Required evidence |
|---|---|
| Audit/privacy | Hashed queries under shipped `include_query_hash: true`; redacted secrets, audit convergence, no raw corpus. Turning hashing off changes that guarantee. `tests/test_logger.py`, `tests/test_metrics.py`, `tests/test_due_diligence_invariants.py`. |
| Spend/Numbat/sequences | Separate ledgers/projections, correct provider counts, no duplicate projection, fail-soft Numbat, hashed joins. `tests/test_spend.py`, `tests/test_metrics_spend.py`, `tests/test_numbat_emitter.py`, `tests/test_numbat_audit_projection.py`, `tests/test_sequence_detect.py`. |
| Guardrails | Disabled pass-through and enabled input/output/hook behavior; bridge runs in process. Distinguish optional NeMo engine tests from heuristic mocks. Follow current guardrails workflow/jobs. |
| Agentic and connectors | Remaining CLI/ops surface, denied writes by default, jailed paths, SQL read-only guards, approval/apply/verify/commit/push boundaries. `tests/test_agentic_real_repo_run_smoke.py`, `tests/test_agentic_executor.py`, `tests/test_agentic_hard_sandbox.py`, and relevant `test_agentic*`, `test_fsconnect*`, `test_sqlconnect*`, `test_netconnect*` groups. No live publication. |
| Optimizer | `agentic/harness_optimizer/` retains a retired fixture loop plus governance/model-adapter code used by the real-repo CLI. Its `mcp/` contains Python tools, not a server; use `tests/test_agentic_harness_optimizer.py` and its dedicated source/tests for history, lock and workspace contracts. The deleted console is not a prerequisite. |
| Unslop | `agentic/unslop_bridge.py` remains default-off, log-only and non-blocking in the local real-repo loop; it grants no execution authority. Use `tests/test_unslop_bridge.py` and `tests/test_unslop_suggest.py`; verify hashed metrics. |
| Channels and sync | Telegram/OpenTweet/sync remain default-off out-of-band paths; mock service calls. Neither channel bypasses gateway consent. Native scheduler tests require the matching platform. |
| Optional services/kit | PostgreSQL/pgvector and DeepAgents compatibility jobs need their selected profiles. `tests/judge_eval.py` is paid opt-in evaluation, not routine smoke. `tools/lora_finetune/tests/` is outside root pytest discovery; use its own workflow. |

## Installation and platform evidence

Read `setup-guide.md` and live manifests; do not copy pins from a past report.
Manual/core, native installer and one-shot clone are distinct workflows. Conda
(`environment.yml`) and Docker are additional supported surfaces when claiming
installation parity. Compare Python, constrained packages, console scripts,
config/layout, synthetic index creation and the same gateway checks.

| Startup or OS lane | What must be established |
|---|---|
| `python gate.py` / `python -m gate` / `cyclaw-server` | Calls `gate.main()`; validate configured binding and optional auth/TLS before serving. Console scripts require installing the project, not only requirements. |
| `macos/invoke-cyclaw.sh` | Runs uvicorn directly on loopback with its selected gate port and `--no-proxy-headers`; it does not apply `gate.main()` TLS options. Test its actual command. |
| `powershell/Invoke-CyClaw.ps1` | Runs `gate.py`; validate launcher env/home and resulting main/TLS behavior on native Windows. Installer PowerShell 5.1 syntax and the bundled smoke helper's PowerShell 7 requirement are separate. |
| Docker/Compose | Docker listens on `0.0.0.0` inside the container; Compose publishes loopback. Inspect mounts, non-root, readonly rootfs, resource limits, capabilities/seccomp and direct-uvicorn TLS behavior. No general egress firewall is implied. |
| Storage | Resolve each consumer, not just `CYCLAW_HOME`: default corpus/index/soul/auth/log paths anchor to the repo. Memory's relative DB path is CWD-relative (`memory/store.py`); use an explicit absolute temporary path in fixtures. Docker mounts determine host locations. |
| Native macOS | Plain Torch via constrained temporary manifests; installer layout, launchd/Keychain wrappers, dotenv modes, BSD stat under shadowed PATH, allexport and failed-source behavior; APFS and `/Volumes` tests on Darwin. Simulation is not native acceptance. |
| Native Windows | Constrained CPU Torch, installer/shims, Task Scheduler/CredMan, ACL/path checks. A Linux or macOS pass cannot establish these. |
| Executor containment | Darwin denies network and restricts writes but permits reads; Linux uses a network namespace; Windows uses Job Object process-tree control with sockets still available. Missing required backend fails closed. Do not call these equivalent isolation. |

Use the relevant installer/launcher tests under `tests/`, including
`tests/test_setup_from_clone.py`, `tests/test_setup_cyclaw_keys.py`,
`tests/test_generate_service_plist.py`, `tests/test_generate_service_task.py`,
`tests/test_fsconnect_macos_real.py`, and
`tests/test_fsconnect_pathsafe_windows.py`. Native credential creation,
service registration and physical model inference are separate user-authorized
lanes, not side effects of a mock audit.

## Completion record

Record each lane's SHA, command, interpreter/dependency profile, host, fidelity,
status, sanitized evidence path and concrete gap. Include current-head hosted
CI URLs/states only when verified. Missing native hardware/service is `SKIP`;
an assertion failure is `FAIL`. Do not total unlike lanes into a blanket
"full functionality" verdict or reuse historical pass counts.
