# Repository Guidelines

Guidance for any AI agent working in CyClaw: Codex, Grok, Kimi, Perplexity, Claude, and CyClaw itself. Read `.codex/skills/fable-protocol/SKILL.md` (or the driver's `.claude/skills/` equivalent) before substantive work, then the relevant task skill. Explicit user instructions and existing authorization govern scope.

## Sources of truth

Running code and `config.yaml` determine behavior. `CLAUDE.md` is the detailed operating contract; `INVARIANTS.md`, `docs/THREAT_MODEL.md`, and `.github/SECURITY.md` cover security; `.codex/Codex_instructions.md` covers Codex Git/PR practice. Read active workflows for CI and `setup-guide.md` for installation. Treat dated audits, memory, issues, and draft PRs as leads, not current guarantees.

Before GitHub work, inspect the root, remote, branch, dirty state, and open PR overlap; fetch `origin/main`. Preserve unrelated edits and conflicts. Fast-forward only when safe; use an isolated checkout for divergent or dirty work. Never reset an unknown checkout.

## Project structure and current behavior

- `gate.py` exposes the FastAPI gateway; `gate_ops.py`, `gate_auth.py`, and `gate_memory.py` register route groups. `graph.py` owns answer routing. `retrieval/` implements ChromaDB/BM25 hybrid search and indexing; `llm/` owns model clients. `utils/` and `schemas/` hold shared contracts.
- `retrieval/rerank.py` runs the local cross-encoder behind the vault-hit gate. Shipped `retrieval.min_rerank_score: null` audits the best logit without vetoing a hit; a numeric threshold may only turn a semantic hit into a miss. An unavailable reranker records `rerank_degraded`. Cache both retrieval models for offline use. BM25 remains JSON, never pickle.
- `mcp_hybrid_server.py` exposes sanitized, retrieval-only MCP access; it has no generation or sampling path. Browser assets are in `static/`; tests are in `tests/`.
- `agentic/`, `sync/`, `guardrails/`, `telegram/`, and `opentweet/` are out of band. The six core modules named by I6 must not import them; use maintained bridges or subprocesses. `memory/` is a separate default-off subsystem.

Read live switches before claiming a feature is active. Shipped mode is hybrid with Grok and Claude enabled, but external answers still require per-request confirmation and an available selected client. Auth, memory, and agentic master switches ship off. Guardrails ships on with NeMo as a base dependency and deterministic checks on degradation. Numbat's NDJSON projection ships on; its pre-action hook and CEL monitor ship off and do not score the stream at runtime. Armed writer settings do not authorize a write.

Both local answer nodes allow loopback or an exact hostname/IP in `models.local_llm.trusted_hosts` (ships `[]`); malformed destinations fail with typed `ENDPOINT_TRUST` errors. This is operator trust for local model context, not cloud consent or DNS pinning.

`/query` requires session/device-token auth only when `auth.enabled` is literal true; same-origin checking always applies. API-key routes fail closed to Bearer keys and console cookies when `CYCLAW_API_KEY` is unset; an enabled admin login can still authorize them when auth is enabled. Console and admin cookies require their CSRF token on writes and are refused cross-site. `security.api_key_optional` ships false; when enabled it requires a loopback socket peer, no forwarding headers, and a non-cross-site request, without disabling auth/RBAC. `/index/build` is a special first-run route: it always requires loopback, no forwarding headers, and same origin; it requires an API-key credential once the key exists. Request bodies are capped by `security.max_request_body_bytes`.

## Six security invariants

1. Retrieval is the unconditional graph entry before generation.
2. Graph edges enforce routing; inspect current nodes and routers before changing topology.
3. External fallback requires hybrid mode and literal provider enablement at gateway client construction, then confirmation, selection, and availability in the graph. Destination checks and pre-action hooks can only narrow access.
4. Every graph path converges on `audit_logger`, then END.
5. `POST /soul/apply` requires a human reason, injection scan, and atomic replacement. Restore re-applies a vetted `.bak` without scanning; startup drift recovery and `/soul/reload` adopt on-disk content unscanned. Missing soul self-initializes at boot; read-only checks must not rewrite it.
6. Preserve core/out-of-band import isolation and retrieval-only MCP behavior.

Apply telemetry suppression before heavy imports, but do not describe it as a network firewall. Application, console, and Numbat logs have bounded writer queues; `audit.jsonl` remains synchronous and authoritative, so an audit-sink stall can hold a request. `/health` probes external providers only when `api.health_probe_external_providers` is true (ships false). Keep private corpus, raw queries, credentials, indexes, logs, and local databases out of commits and reports.

## Build, test, and coding conventions

Use Python 3.12 and inspect an existing environment first. Follow the platform-specific hashed `locks/` instructions in `setup-guide.md`: plain Torch on macOS, `+cpu` on Linux/Windows. `constraints.txt` remains the ceiling for editable installs and tooling. Do not invent extras or copy stale pins. Once per clone, run `bash scripts/ensure-githooks.sh`.

From the repository root, with the selected interpreter:

    python -m retrieval.indexer
    python gate.py
    python mcp_hybrid_server.py
    python -m ruff check --select F,B,S .
    python .claude/skills/invariant-guard/check_invariants.py
    python .claude/skills/dotenv-guard/check_dotenv.py
    python .claude/skills/doc-sync/doc_sync.py

Set `GROK_API_KEY=dummy` for isolated verification; never spend real provider tokens routinely. Use disposable personality, index, and log paths when execution needs them, preserving the committed soul. Directly exercise changed behavior and inspect output and side effects first. Then use relevant lint/static checks (`actionlint` for changed workflows); let draft-PR Actions run broad suites and the 80% coverage gate. Run one focused test file when direct execution and static/CI evidence cannot exercise a concrete risk or an applicable gate requires it. Do not run full local suites, CI-style coverage, or LoRA tests routinely. Four Python 3.12 platform test legs gate shared routing, retrieval, auth, and security changes on the exact PR head. Ruff F/B/S blocks; broader Ruff/WPS is advisory; mypy needs `--explicit-package-bases` and is best-effort. Distinguish local, mock, native, live-provider, and hosted-CI evidence.

Before drafting a moderate or larger PR, update the README, the `docs/*.md` pages, and the dependency/install files the change touches, and delete stale or duplicated statements while there (`doc-sync`, `dep-guard`, `verify-dep`).

Use four-space indentation, typed Python, snake_case, the existing 120-column style, named logging, and config-owned tunables. Docstrings begin modules/functions; use `#` for class or inline commentary.

## Skills and routines map

`.codex/README.md` mirrors the Codex skill map; update both when skills change. Each Codex skill has `.codex/skills/<name>/SKILL.md` and `agents/openai.yaml`. Other drivers use `.claude/skills/` equivalents where available; a skill missing from a local sandbox may still exist on GitHub `main`, so check there before declaring it absent. Live memory lives only in `docs/memories/`.

| Skill/directory | Use |
|---|---|
| `fable-protocol`, `cyclaw-project-guidance`, `chris-codex` | Evidence discipline, current sources, engineering continuity |
| `cyclaw-advisor`, `verification-specialist` | Read-only advice or independent verification |
| `add-comment`, `architecture-refactor`, `refactor`, `cyclaw-optimize` | Scoped documentation, refactoring, or warranted improvement |
| `dep-guard`, `verify-dep`, `doc-sync`, `invariant-guard` | Dependency, documentation, and invariant checks |
| `injection-redteam`, `otel-hardening` | Sanitizer and telemetry boundary checks |
| `cyclaw-run-cyclaw`, `cyclaw-sandbox-test`, `Cyclaw-Sandbox` | Setup, isolated smoke, or explicitly requested full sandbox verification |
| `cyclaw-command-status`, `cyclaw-command-run`, `cyclaw-command-audit`, `cyclaw-command-check-soul` | Read-only status, runtime, audit, and soul checks |

Use `.codex/routines/` for review, bugfix, feature, refactor, test/verify, PR, and security workflows; checklists and prompts live beside it.

## Git, reviews, and completion

Develop on `<driver>/<topic>` using the tracked hook allowlist (`grok/`, `claude/`, `codex/`, `kimi/`, `agent/`, `CyClaw/`, `cyclaw/`). Commit subjects use `[prefix] - subject` per the PR template. Preserve an existing PR branch when fixing it, even if another driver created it. Never commit or push `main` or merge without explicit authorization. Never bypass hooks or set their operator overrides. Commit as the runtime's own identity, never as `CyClaw Agent`, which belongs to CyClaw's agentic loop.

Map overlapping files before multiple PRs. Consolidate related edits or stack real dependencies, trial-merge in the intended order, and reverify after integration. Refresh `origin/main` and the PR head before publication or readiness claims. Rewrite published history only with authorization and an exact-SHA `--force-with-lease`; never overwrite concurrent remote work.

Validate review findings against the actual head and code path. A bot claim of a commit or PR is not remote evidence: check SHA, diff, reviews, mergeability, and CI separately. Use `.github/PULL_REQUEST_TEMPLATE.md` for authorized draft publication, stating invariant impact, directly run checks, CI-only checks, limits, risks, base, and merge order. Monitor the exact pushed head; report pending, skipped, disabled, and failed checks distinctly. Do not send comments or review requests without authorization.
