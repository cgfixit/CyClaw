# CyClaw sandbox acceptance map

Use with [SKILL.md](SKILL.md) at the selected SHA. Use `CLAUDE.md` section 5 for local and hosted evidence. Listed tests identify owning coverage.

## Surface inventory

Inspect the route table and packaging manifest. The coding console, extractor, agentic coding loop and SQL connector were retired. On an isolated gateway, confirm the old harness HTML, `/ops/agentic` and `/ops/sqlconnect` return 404. The remaining connectors are `agentic/fsconnect/` and `agentic/netconnect/`.

The terminal uses `static/terminal.html`, `static/terminal.js` and `static/auth_admin.js`. Check Users as a terminal panel and memory HTML export as a conditional route.

## Routing, retrieval and model fidelity

| Lane | Acceptance | Source and tests |
|---|---|---|
| Topology | Retrieve first; conditional routers only; every terminal route audits. Read the actual node/edge sets. | `graph.py`; `tests/test_graph.py`, `tests/test_graph_outcomes.py`, `tests/test_due_diligence_invariants.py`; invariant-guard |
| Three external gates | Mode and provider enablement control client construction in the gateway; graph requires fresh confirmation, selected available client. Reject each missing gate independently. Destination policy and pre-action hooks add checks; neither replaces consent. | `gate.py`, `graph.py`, `utils/endpoint_trust.py`; `tests/test_gate.py`, `tests/test_graph.py`, `tests/test_endpoint_trust.py` |
| Local destination | Both local answer paths reject malformed/untrusted destinations and accept explicit trusted hosts. Trusted hosts receive context and soul; this is an operator trust grant. | `utils/endpoint_trust.py`, `graph.py`; `tests/test_endpoint_trust.py` |
| Real retrieval | Synthetic corpus, real indexer/BM25/Chroma, expected document ranking and prompt-included sources; reject corpus escapes. BM25 remains JSON. | `retrieval/`; `tests/test_hybrid_search.py`, `tests/test_rag_integration.py`, `tests/test_indexer.py`, `tests/ci_rag_smoke.py` |
| RRF parity | Same corpus, chunking, fingerprint and config on each OS. RRF contributions use `1 / (rrf_k + rank)` with rank starting at 0; use its configured score threshold and the separate cosine floor. Explain differences rather than normalizing them away. | `retrieval/hybrid_search.py`, `config.yaml`; hybrid/retrieval tests |
| MCP | Stdio retrieval-only; sanitize inputs; no LLM imports/generation. Capability metadata alone is not enforcement. | `mcp_hybrid_server.py`; `tests/test_mcp_server.py`, `tests/test_mcp_manifest.py` |

In the bundled query fixtures verify two vault hits, one denied-online miss and two confirmation misses. The provider phase is mocked. External answers must omit soul and fabricated local sources. Use `tests/test_llm_client_ollama.py` for the socket contract. Record real inference separately with model ID, owned process and successful response.

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
| `POST /index/build`, `GET /index/status` | Build always requires loopback peer, no forwarding headers and same origin; once `CYCLAW_API_KEY` is set it also requires API-key-route credentials. Verify rate limit, one-build-at-a-time and owned process completion with synthetic data. Status is an unrate-limited progress probe, not corpus content. | `tests/test_gate_index_build.py` |
| `/soul`, `/soul/propose`, `/soul/apply`, `/soul/reload`, `/soul/restore` | API-key refusal, reason and scan on apply, atomic replacement. Restore uses a vetted backup; reload/drift adopt trusted disk content unscanned. Do not mutate the committed or operator soul. | `tests/test_gate.py`, `tests/test_personality.py`, `tests/test_due_diligence_invariants.py` |
| `/audit/summary`, `/ops/sync`, `/ops/fsconnect` | Key gate, action schema and subprocess result; disabled/mocked connectors. Test optional-key bypass only with loopback peer, no forwarding headers, non-cross-site request. | `tests/test_gate.py`, `tests/test_gate_ops.py` |
| `/auth/*` | Off returns 503; bootstrap loopback/no-proxy rules; login/session+CSRF, logout/whoami, user/password/role/disable/enable/delete policies, last-admin protection, audit role and token revocation. CLI device-token lifecycle is distinct. | `tests/test_gate_auth.py`, `tests/test_gate_auth_admin.py`, `tests/test_authn_rbac.py`, `tests/test_authn_manager.py`, `tests/test_authn_cli.py` |
| `/memory/*`, `/query/export/html` | Key-gated status; default-off subfeature gating; isolated facts/episodes/proposals, reason+scan on apply and safe HTML export. No shared operator DB. | `tests/test_memory_routes.py`, `tests/test_memory_store.py`, `tests/test_memory_policy.py`, `tests/test_memory_fusion.py`, `tests/test_memory_metadata_prompt_isolation.py` |

Browser acceptance includes desktop/mobile screenshots, completed queries and errors, the offline choice's initial focus and focus trap, and health/index progress. Check that a reload or second tab follows a running build through `/index/status`. Check soul/ops/Users panels, safe DOM, credential masking, same-origin requests, console errors, unexpected destinations and horizontal overflow. See `tests/test_auth_admin_contract.py`, `tests/test_terminal_confirm_focus_trap.py` and `tests/test_gate_index_build.py`. The browser helper exercises a single query at each viewport. Inspect other interactions separately.

## Audit and optional subsystems

| Lane | Required evidence |
|---|---|
| Audit/privacy | Hashed queries under shipped `include_query_hash: true`; redacted secrets, audit convergence, no raw corpus. Turning hashing off changes that guarantee. `tests/test_logger.py`, `tests/test_metrics.py`, `tests/test_due_diligence_invariants.py`. |
| Spend/Numbat/sequences | Separate ledgers/projections, correct provider counts, no duplicate projection, fail-soft Numbat, hashed joins. `tests/test_spend.py`, `tests/test_metrics_spend.py`, `tests/test_numbat_emitter.py`, `tests/test_numbat_audit_projection.py`, `tests/test_sequence_detect.py`. |
| Guardrails | Disabled pass-through and enabled input/output/hook behavior; bridge runs in process. Distinguish real NeMo engine checks from heuristic mocks. Follow current guardrails workflow/jobs. |
| Connectors | fsconnect (`/ops/fsconnect` plus its CLI) and netconnect (CLI only): denied writes by default, jailed paths, passive-only LAN inventory with a fail-closed scope. `tests/test_agentic_isolation.py` and the relevant `test_fsconnect*`, `test_netconnect*` groups. No live publication. |
| Channels and sync | Telegram/OpenTweet/sync remain default-off out-of-band paths; mock service calls. Neither channel bypasses gateway consent. Native scheduler tests require the matching platform. |
| Optional services/kit | PostgreSQL/pgvector jobs need their selected profiles. `tests/judge_eval.py` is paid opt-in evaluation, not routine smoke. `tools/lora_finetune/tests/` is outside root pytest discovery; use its own workflow. |

## Installation and platform evidence

Use `setup-guide.md`, `locks/README.md` and the actual installer. Record interpreter, platform hash locks, entry points, layout, synthetic index and gateway results per claimed profile.

| Startup or OS lane | What must be established |
|---|---|
| `python gate.py` / `python -m gate` / `cyclaw-server` | Calls `gate.main()`; validate configured binding and optional auth/TLS before serving. Console scripts require installing the project, not only requirements. |
| `macos/invoke-cyclaw.sh` | Runs `gate.py` through the selected venv (not `uvicorn gate:app`) so `main()` applies the loopback bind guard, TLS options, and `proxy_headers=False`. `--gate-port` still works. Test its actual command. |
| `powershell/Invoke-CyClaw.ps1` | Runs `gate.py`; validate launcher env/home and resulting main/TLS behavior on native Windows. Installer PowerShell 5.1 syntax and the bundled smoke helper's PowerShell 7 requirement are separate. |
| Docker/Compose | Docker listens on `0.0.0.0` inside the container; Compose publishes loopback. Inspect mounts, non-root, readonly rootfs, resource limits, capabilities/seccomp and direct-uvicorn TLS behavior. No general egress firewall is implied. |
| Storage | Resolve each consumer, not just `CYCLAW_HOME`: default corpus/index/soul/auth/log paths anchor to the repo. Memory's DB path expands `~` and anchors relative paths to the repo (`memory/store.py`); use explicit absolute temporary paths in fixtures. Docker mounts determine host locations. |
| Native macOS | Plain Torch via platform hash locks; installer layout, launchd/Keychain wrappers, dotenv modes, BSD stat under shadowed PATH, allexport and failed-source behavior; APFS and `/Volumes` tests on Darwin. Simulation is not native acceptance. |
| Native Windows | CPU Torch via platform hash locks, installer/shims, Task Scheduler/CredMan, ACL/path checks. A Linux or macOS pass cannot establish these. |

Use focused installer, launcher and filesystem tests for unresolved claims. Use matching native hosts for OS behavior. Authorize credential creation, service registration and real inference separately from mocked audits.

## Completion record

Record lane, SHA, command, interpreter/profile, host, fidelity, result, sanitized evidence and gaps. Link verified exact-head CI. Use SKIP for unavailable required services or platforms and FAIL for observed assertion failures. Historical counts belong to their original revision.
