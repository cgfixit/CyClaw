---
name: cyclaw-run-cyclaw
description: "Set up, index or start CyClaw when explicitly requested. Use current platform hashed install instructions and an owned loopback lifecycle; focused existing-runtime probes belong to cyclaw-command-run."
---


# Set Up or Start CyClaw

Read `setup-guide.md`, `locks/README.md`, current config and the active platform
installer. Inspect an existing environment before installing. Use Python 3.12
and the selected platform Torch/runtime/test locks with `--require-hashes`;
plain macOS Torch and Linux/Windows CPU wheels differ. Do not substitute stale
legacy manifest commands for the documented install or overwrite a venv.

Resolve every corpus, soul, index, log and DB path. Preserve operator soul and
credential stores. For verification use a disposable copy, synthetic data and
sanitized child environment; `CYCLAW_HOME` alone does not relocate all paths.
For an authorized real run preserve the operator's configured credentials.

Build only the requested/configured index when needed:

```text
python -m retrieval.indexer
python gate.py
```

Indexing may need first-run model downloads; inspect cached embedder/reranker
availability before claiming offline readiness. `cyclaw-index` and
`cyclaw-server` are installed entry points. Direct `uvicorn gate:app` skips
`gate.main()` startup/bind checks and is not equivalent to the canonical launcher.
Never loosen destination trust or expose a listener to make setup pass.

Check relevant health/query/UI behavior via `$cyclaw-command-run`, then follow
`CLAUDE.md` section 5 for verification. Do not require optional/cloud services
or a full local suite for an ordinary start. Record owned PID/port/readiness;
stop owned verification servers when done unless asked to leave them running.
