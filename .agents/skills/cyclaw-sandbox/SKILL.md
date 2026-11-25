---
name: cyclaw-sandbox
description: "Run an explicitly requested CyClaw sandbox audit on a pinned baseline or PR head. Record mock, real inference, browser, native and hosted CI evidence separately."
---

# Audit CyClaw in a Sandbox

Use the [acceptance map](test-specifications.md) and current workflows. Record SHA, effective config, OS, Python and toolchain. Use an owned disposable checkout, synthetic corpus, sanitized environment and unique ports with PID-bound readiness. Resolve all soul/index/log/DB/report paths. `CYCLAW_HOME` alone is insufficient. Leave operator stores, services and credentials untouched.

Run invariant, dependency and doc-sync guards first. Use `setup-guide.md` and hashed `locks/` for real install evidence. Follow `CLAUDE.md` section 5 for direct probes, focused tests and exact-head Actions. Use separate authorization for paid calls or native state changes.

## Evidence lanes

| Lane | Evidence |
| --- | --- |
| Tier 0 | `run_full_verification.py` uses real LangGraph with stubbed heavy dependencies, selected graph paths and synthetic audit/Numbat checks. |
| Tier 1 | Owned socket mock with real gateway, indexer and HTTP clients. Check PID and requests. |
| Tier 2 | Requested real local inference with cached models, measured outputs and recorded model/process. |
| UI | `browser_render_check.py` submits a query and captures desktop/mobile. It fails on a query error or unexpected console error; auth-off `/auth/*` 503 is expected. Pass `--browser` to `.claude/skills/CyClaw-Sandbox/local_audit.py` to include it. Inspect screenshots, controls, assets and overflow separately. |
| Native/CI | Matching OS installer, keystore, scheduler and confinement evidence plus exact-head jobs/skips. |

Run Tier 0 from a prepared candidate with an owned external results directory:

```bash
CYCLAW_REPO="$PWD" CYCLAW_SKIP_ENSURE=1 GROK_API_KEY=dummy   CYCLAW_RESULTS_FILE="$CYCLAW_AUDIT_TEMP/query-results.json"   python .agents/skills/cyclaw-sandbox/run_full_verification.py
```

Tier 0 writes synthetic corpus, index and logs. Rebuild a real synthetic index before gateway probes. Inspect helper arguments, credentials and side effects. The shared runners and terminal probes delegate to `.claude/skills/CyClaw-Sandbox/`. `cyclaw-sandbox-test` has a separate provider-protocol mock.

## Legacy helper limits

`verify.sh` may delete `VENV_DIR`, creates an environment, rewrites fixture soul and runs a full suite. `smoke.sh` also writes fixtures and runs broad tests. Use them only for their intended isolated lifecycle. Set `CYCLAW_REPORT_DIR` to keep smoke reports in owned storage. Direct Uvicorn bypasses `gate.main()`. Authenticated terminal probes need disabled or mocked connectors and disposable DBs. PowerShell 7 smoke covers a gateway subset; native installer acceptance includes PowerShell 5.1.

## Report

Use the evidence format in `$verification-specialist`. Record PASS/FAIL/SKIP/NOT RUN by lane. Treat missing dependencies as gaps even if a legacy helper returns zero. Report overall PARTIAL for missing required evidence. Keep redacted results outside the checkout, and clean only owned processes and state.
