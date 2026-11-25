---
name: cyclaw-sandbox-test
description: "Run the legacy CyClaw socket-mock smoke only on explicit request, in a prepared disposable checkout. Use cyclaw-sandbox for full audits."
---

# Legacy Socket-Mock Smoke

Read `scripts/run_sandbox_test.py`. `--ref` pins a clone. `--in-place` ignores it and rewrites config and state in the current checkout. Bootstrap uses the platform hash locks. With `--skip-install`, invoke the runner with the prepared environment's Python.

```text
python .agents/skills/cyclaw-sandbox-test/scripts/run_sandbox_test.py --in-place --skip-install --skip-tests
```

Use an isolated network with ports 11434 and 8787 unused. A matching model-list response gives no process ownership proof. Strip real credentials and DB DSNs. The runner can scaffold a missing soul, write index/log state and exercise reload and ops. Supply a synthetic index if skipping the build.

The fixture enables provider health probes with dummy keys. In hybrid mode expect healthy `ollama` and `embeddings_local`, with `grok_api` and `claude_api` refused by the HTTPS destination policy. Treat the result as socket-mock and endpoint evidence. Direct Uvicorn bypasses `gate.main()`; the runner cannot establish native install or production consent behavior.

Inspect the report, config restoration and cleanup. Record failed and skipped steps. Use current native/Actions lanes for platform evidence.
