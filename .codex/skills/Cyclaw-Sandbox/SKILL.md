---
name: cyclaw-sandbox
description: Run full, evidence-backed CyClaw sandbox verification for a baseline or exact PR head, covering RAG, gateway/terminal, security contracts, installers, native platforms, and CI. Use for an explicit full sandbox audit; use the narrower runtime skill for a quick smoke.
metadata:
  short-description: Full current-source CyClaw sandbox verification
  tailored-for: "codex"
---

# CyClaw Sandbox

Invoke as `$cyclaw-sandbox` (or `/cyclaw-sandbox` where slash skills are
supported). Preserve the historical directory spelling `Cyclaw-Sandbox` and
its explicit-only invocation policy. This is the Codex workflow; the Claude
bundle is `.claude/skills/CyClaw-Sandbox/` (capital **C** in **Claw**).

## Current scope

Reconciled against `3d9137542546e196ea939f0009b794b09f8d4553` on 2026-09-12.
Refresh the source before each run; this revision is evidence, not a pin to keep.

The Python coding console was removed in `eb5a855f` (#1367). Do not start
`harness.server`, require port 8790, request `static/harness.html`, or test the
removed `/api/keys`, `/api/web`, `/api/memory`, `/api/tools`, `/api/skills`,
`/api/chat`, session/cancel or harness agent routes. The `cyclaw-harness`
entry point, harness config block, launch targets, and `test_harness*` suite
are gone. The older static extractor (`static/extractor.html` and
`static/extractor.js`) was also removed; do not restore it for verification.

What remains must still be covered:

- `gate.py` with `gate_ops.py`, `gate_auth.py`, and `gate_memory.py`;
  `static/terminal.html`, `static/terminal.js`, and `static/auth_admin.js`.
- RAG graph, retrieval, model clients, soul, auth, optional memory/export,
  audit, spend, Numbat and sequence analysis; retrieval-only MCP over stdio.
  The optional Unslop bridge remains a log-only agentic prose-quality check.
- Out-of-band connectors and channels, installers and OS glue. `agentic/`
  and its governed `real-repo-run` CLI remain. `agentic/harness_optimizer/` is
  retained optimizer code: its fixture loop is retired, while governance and
  model-adapter modules still serve the real-repo CLI. Its `mcp/` directory
  contains Python workspace tools, not an MCP server.
- The retired DeepAgents builder still has code/tests/CI. Distinguish that
  compatibility lane from the live `real_repo_loop.py` consumer; do not
  silently delete either because the browser console was removed.

Use [test-specifications.md](test-specifications.md) for the source/test map,
current trust boundaries, and platform acceptance. `NEW_SKILL.md` is only a
redirect. `sandbox-findings-report.md` is an unchanged historical Windows
report for `57e052ed`; none of its PASS counts describe today's checkout.

## Guardrails

- Read `AGENTS.md`, `CLAUDE.md`, `INVARIANTS.md`, `SECURITY.md`, and
  `docs/THREAT_MODEL.md`. Preserve retrieval-first entry, topology policy,
  all three external gates, audit convergence, governed soul writes, and I6.
- I6 is direct-import isolation. The ops shim uses subprocesses; enabled
  guardrails cross a bridge **in process**, and memory is in process too.
  Neither I6 nor telemetry suppression is an OS or network sandbox.
- Use a disposable checkout, synthetic corpus, unique ports, temp state and
  dummy provider credentials. Clear inherited real credentials/DB DSNs in the
  child environment. Inspect every effective storage path: `CYCLAW_HOME`
  alone does not relocate repo-relative corpus, indexes, soul, logs or DBs.
  Keep the operator's checkout, soul, Keychain and existing services intact.
- Never reuse an unknown listener as a mock. Tie readiness to the child PID,
  checkout, port and expected mock response. Stop only processes this run owns.
- No real cloud calls, paid evaluation, SQL writes, agentic publication,
  connector upload or credential-store mutation in a mock verification run.
  An armed writer is not authorization. Use isolated fixtures for mutations.
- Record `PASS`, `FAIL`, `SKIP`, or `NOT RUN` per lane with command, SHA,
  environment and reason. A skip or stub is not a runtime pass. Reports contain
  aggregate/redacted evidence, never private corpus, raw logs or credentials.

## Verification workflow

1. **Pin the candidate and inspect prerequisites.** From the selected checkout:

   ```bash
   git status --short --branch
   git fetch origin main
   git rev-parse origin/main
   python3.12 --version
   SANDBOX_ROOT=$(mktemp -d)
   git worktree add --detach "$SANDBOX_ROOT/repo" origin/main
   ```

   For a PR, detach at its fetched exact head instead. Run subsequent commands
   from that disposable checkout with its selected Python 3.12 environment.
   Record source SHA, config switches, package availability and OS. Do not let
   any runner switch a candidate to main. In PowerShell use `py -3.12` and a
   uniquely created temporary directory for the equivalent commands.

2. **Static baseline and installation.** Run before runtime testing:

   ```bash
   python .claude/skills/invariant-guard/check_invariants.py
   python .claude/skills/dep-guard/check_deps.py --strict
   python .claude/skills/doc-sync/doc_sync.py
   ```

   The invariant/dependency guards use stdlib; doc-sync needs PyYAML. Resolve
   missing prerequisites separately from failing assertions. Follow
   `setup-guide.md`, `requirements*.txt`, `constraints.txt`, `environment.yml`
   and the actual workflows for Python/Torch pins. Compare manual, native
   installer and one-shot clone profiles; include conda and Docker when
   reporting all supported install surfaces. Use temp filtered manifests for
   macOS's plain Torch wheel. Never run `FULL_DEPS=1` as a replacement for the
   constrained platform install, and never delete an existing venv to rebuild it.

3. **Application tests and coverage.** With dependencies installed:

   ```bash
   GROK_API_KEY=dummy python -m pytest tests/ -q --tb=short
   GROK_API_KEY=dummy python -m tests.ci_rag_smoke
   python -m ruff check --select F,B,S .
   ```

   Also run the focused groups in [test-specifications.md](test-specifications.md).
   Copy coverage flags from current `.github/workflows/ci.yml`; bare pytest
   does not exercise the coverage gate. `lint.yml` owns blocking F/B/S and
   advisory broader Ruff/WPS. Include actionlint/Zizmor and the applicable
   service/platform workflow jobs. The LoRA kit's tests live outside `tests/`.

4. **In-process verification.** After preparing the disposable checkout and
   child environment, leave `FULL_DEPS` unset and run:

   ```bash
   CYCLAW_REPO="$PWD" CYCLAW_SKIP_ENSURE=1 GROK_API_KEY=dummy \
     CYCLAW_RESULTS_FILE="$SANDBOX_ROOT/query-results.json" \
     python .codex/skills/Cyclaw-Sandbox/run_full_verification.py
   ```

   This runner writes synthetic corpus/index/log/report files. It stubs heavy
   dependencies and uses `MockLocalLLMClient`: always **Tier 0**. Its manual
   five-query node walkthrough is distinct from compiled-graph tests. Read
   `verification_report.json` phase results, not an old aggregate count.
   Socket mocks and real inference require separate lanes.

5. **Gateway, browser and platforms.** Rebuild the synthetic index with the real
   indexer (`python -m retrieval.indexer`) and the selected cached embedding
   model before starting the gateway. Tier 0 overwrites BM25 and only creates
   an in-memory Chroma collection; it cannot supply the real gateway's index.
   Keep its results before rebuilding, and mark this lane `SKIP` if the real
   dependencies/model cache are unavailable. Start an owned loopback mock and
   gateway with dummy auth and synthetic data. Derive routes from all four gateway
   modules and browser calls from both JS files. Follow the concrete checks in
   [test-specifications.md](test-specifications.md), including index/auth/memory
   surfaces and removed-console absence. Use `--no-proxy-headers` when starting
   uvicorn directly. Direct uvicorn does not execute `gate.main()`'s TLS/bind
   policy; verify the actual startup path on each platform.

   ```bash
   python .codex/skills/Cyclaw-Sandbox/gate_runtime_check.py
   python .codex/skills/Cyclaw-Sandbox/terminal_emulation.py http://127.0.0.1:8787
   python .codex/skills/Cyclaw-Sandbox/browser_render_check.py \
     --gateway http://127.0.0.1:8787/ --out "$SANDBOX_ROOT/screenshots"
   ```

   Substitute the owned gateway port. The browser helper captures desktop and
   mobile terminal views and submits one query. Supplement it with readiness,
   answer-completion, panel/auth/error and overflow assertions; visible
   `#results` alone is not proof an answer arrived. Missing Playwright returns
   2 (`SKIP`); a browser failure returns nonzero (`FAIL`). Inspect screenshots.
   Native Windows/macOS, model inference and hosted CI require their own
   evidence. Mark unavailable lanes explicitly; never infer them from mocks.

6. **Report and clean up.** Record the exact tested SHA, full commands/results,
   install profile and platform, graph/consent/audit checks, fixture RRF parity,
   REST/browser evidence, optional-layer and native skips, and current-head CI
   URLs when checked. Report remaining failures and their scope. Preserve
   privacy-safe artifacts outside the candidate; remove only owned temporary
   processes/worktrees. A full audit request does not itself authorize a PR.

## Gotchas in bundled runners

- `run_full_verification.py` defaults to a shared temp clone and checkout/pull
  unless `CYCLAW_REPO` and `CYCLAW_SKIP_ENSURE=1` are supplied. Its dependency
  stubs and heuristic corpus do not prove real package or embedding parity.
- `verify.sh` is a legacy Linux lifecycle helper: it removes `VENV_DIR` during
  provisioning, uses fixed report paths, downloads NLTK data and temporarily
  rewrites the sandbox soul. `smoke.sh` also builds/writes data. Read their
  setup/cleanup and isolate them before use; they are not read-only checks or
  proof the whole product works. Prefer current CI commands for install proof.
- `test_terminal_consoles.py` issues authenticated ops, including sync dry-run
  and SQL probes. Use disabled/mocked connectors and a disposable database;
  do not point it at the operator's service. `terminal_emulation.py` needs
  httpx; its missing-dependency zero exit is a `SKIP`, not a pass.
- `macos-smoke.sh` and `windows-smoke.ps1` cover a gateway subset (only fsconnect
  status among ops). They do not prove all REST routes, Keychain/CredMan, APFS,
  Windows ACLs, TLS, or real model behavior. The Windows helper uses
  `-SkipHttpErrorCheck` and needs PowerShell 7; installer compatibility with
  Windows PowerShell 5.1 is a separate acceptance check.
- Do not blindly mirror historical Claude resources into this bundle. Preserve
  shared contracts, inspect current callers, and validate any changed helper:

  ```bash
  python -m unittest discover -s .codex/skills/Cyclaw-Sandbox \
    -p test_verification_contract.py
  ```
