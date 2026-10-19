---
name: cyclaw-sandbox
description: "Run an explicitly requested full CyClaw sandbox audit of a baseline or exact PR head. Distinguish in-process mocks, socket mocks, real inference, native platforms and hosted CI; use narrower skills for ordinary verification."
---


# Audit CyClaw in a Sandbox

Use [test-specifications.md](test-specifications.md) for the acceptance map and
the candidate's current source/workflows for commands. This entry point is
explicit-only. Ordinary changes follow `CLAUDE.md` section 5; a full audit does
not make every local suite mandatory or authorize cloud calls/publication.

## Candidate and isolation

Record exact base/head, config, Python 3.12, OS and installed tools. For PR
acceptance pin its exact head, not whatever main later becomes. Use an owned
disposable checkout, synthetic corpus and sanitized child environment. Redirect
every soul/index/log/DB/report path; `CYCLAW_HOME` alone is insufficient.
Keep operator credentials, key stores, services and protected soul untouched.
Use unique ports and PID-bound readiness. Never reuse an unknown listener.

Run invariant, dependency and doc-sync guards before expensive setup. Follow
`setup-guide.md` and platform hashed `locks/` profiles for real install evidence.
Use current-head Actions for broad suites, coverage and platform gates. Run
direct probes for the relevant acceptance lanes and one focused local test file
when required evidence remains absent. Report unavailable lanes rather than
starting paid/cloud or host-mutating checks.

## Evidence lanes

| Lane | Evidence and limits |
| --- | --- |
| Tier 0 | `run_full_verification.py` stubs heavy dependencies and walks selected nodes. Its results are in-process synthetic evidence, never real inference or a complete compiled-graph proof. |
| Tier 1 | An owned socket mock plus real client/gateway/indexer proves exercised HTTP behavior. A model-list response does not prove process ownership, consent or destination allowlists. |
| Tier 2 | Explicitly requested real local inference with cached models and measured outputs. Separate from mocked correctness. |
| UI | `browser_render_check.py` captures views and submits a query. Independently assert completed answers, errors, controls, asset requests and mobile overflow; inspect screenshots. |
| Native/CI | Matching OS installer, keystore, scheduler and confinement evidence; read current-head jobs/skips. Windows executor refusal is separate from supported Windows gateway behavior. |

For a prepared disposable candidate, Tier 0 can run from its root:

```bash
CYCLAW_REPO="$PWD" CYCLAW_SKIP_ENSURE=1 GROK_API_KEY=dummy \
  CYCLAW_RESULTS_FILE="$CYCLAW_AUDIT_TEMP/query-results.json" \
  python .agents/skills/cyclaw-sandbox/run_full_verification.py
```

Create `CYCLAW_AUDIT_TEMP` as an owned external temp directory first. Tier 0
writes corpus/index/log state; rebuild a real synthetic index before a gateway
lane. For an isolated running gateway, helpers include `gate_runtime_check.py`,
`terminal_emulation.py` and `browser_render_check.py`; inspect their arguments,
credentials and side effects before execution. Missing dependencies are skips,
even when a legacy helper returns zero. Direct uvicorn skips `gate.main()`.
The terminal probe and `mock_ollama.py` delegate to the maintained Claude
implementations; update those implementations rather than restoring copies.

## Legacy helper limits

Do not run all bundled scripts as one automatic gate. `verify.sh` provisions
a Linux venv (can delete `VENV_DIR`), downloads NLTK data, rewrites fixture soul
and runs a full suite; `smoke.sh` also writes fixtures and runs broad tests.
They are explicit historical lifecycle helpers, not read-only or routine checks.
Use current install/Actions commands instead for ordinary verification.

`test_terminal_consoles.py` issues authenticated ops; require disabled/mocked
connectors and disposable DBs. Platform smoke scripts cover only a gateway
subset. PowerShell 7 HTTP smoke does not prove installer PowerShell 5.1 support.
Browser failures are FAIL; missing browser packages are SKIP. No stub/native
substitute should receive a higher fidelity label.

The removed Python coding console and extractor are not audit prerequisites;
inspect retained agentic/optimizer code rather than resurrecting their routes.
Historical reports remain in `docs/audits/` and are not current PASS evidence.

## Report

Use `$verification-specialist`'s command/output/exit and adversarial-probe format.
Record PASS/FAIL/SKIP/NOT RUN by lane, exact SHA/profile, CI URLs and limits.
Keep aggregate/redacted evidence outside the candidate. Clean only owned
processes/worktrees/temp state. Give an overall PARTIAL when required lanes
could not run; a full audit request alone grants no publication authority.
