---
name: cyclaw-sandbox-test
description: "Use the explicitly requested legacy CyClaw socket-mock smoke runner in a disposable prepared checkout. Exclude routine verification and native macOS install claims; prefer current platform CI and cyclaw-sandbox for full audits."
---


# Legacy Socket-Mock Smoke

Keep this entry point explicit-only while its runner has fixed-port and process
ownership assumptions. It is not a required fresh-clone gate. Prefer current
native/Actions smoke lanes or `$cyclaw-command-run` for an existing environment.

Read `scripts/run_sandbox_test.py` before use. `--ref` pins a cloned candidate;
`--branch` can move. `--in-place` ignores `--ref` and uses the selected checkout,
rewrites config and builds state, so use only an owned disposable copy.
Bootstrap uses the platform-specific Torch, runtime and test hash locks. For an
environment already prepared via `setup-guide.md`/`locks/`, use `--skip-install`
with that environment's Python; the runner reuses
`sys.executable`, not a discovered `.venv`. Mocks do not prove platform parity.

For a prepared disposable checkout with synthetic data:

```text
python .agents/skills/cyclaw-sandbox-test/scripts/run_sandbox_test.py --in-place --skip-install --skip-tests
```

Run only after confirming ports 11434 and 8787 are unused in an isolated network
environment. The runner can reuse a responder and cannot prove PID ownership;
matching model IDs do not make an operator service safe to reuse. Remove real
credentials and DB DSNs from its child environment. It temporarily enables
provider health probes and points dummy-key clients at a loopback mock.
In hybrid mode `/health` must report `ollama` and `embeddings_local` healthy and
`grok_api` and `claude_api` unhealthy, because the online destination allowlist
(https on port 443 only) refuses the loopback mock before a probe sends a key.
Those probes cannot prove production online-destination or graph consent policy.

The runner writes index/log/report state and exercises soul reload/ops and
unauthenticated refusals. It scaffolds a missing default soul before startup,
even with installs/indexing skipped. Never use the operator's personality/backend.
Direct uvicorn startup does not prove `gate.main()` binding/TLS policy. With
`--skip-index`, ensure a compatible synthetic index exists. With `--skip-tests`, follow `CLAUDE.md`
section 5 and obtain remaining suite evidence from the exact-head Actions.

Inspect the printed report and stdout/stderr, failures, config restoration and
cleanup. Distinguish preparation, socket-mock, endpoint and skipped tests; no
legacy count proves today's coverage. Retain helper contract tests and current
callers until a separately verified replacement permits retirement.
