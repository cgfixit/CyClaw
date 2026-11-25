---
name: cyclaw-run-cyclaw
description: "Set up, index or start CyClaw on explicit request. Use the supported platform profile and manage only the requested instance."
---

# Set Up or Start CyClaw

Read `setup-guide.md`, `locks/README.md`, current config and the platform installer. Inspect the existing environment first. Use Python 3.12 and the documented platform Torch and runtime hash locks. Preserve operator environments and credentials.

Resolve every corpus, soul, index, log and database path. For verification use synthetic data and a sanitized environment in a disposable checkout. `CYCLAW_HOME` alone leaves some paths unchanged.

Build the requested index and launch via the canonical entry points:

```text
python -m retrieval.indexer
python gate.py
```

Installed equivalents are `cyclaw-index` and `cyclaw-server`. Direct Uvicorn bypasses `gate.main()` startup and bind checks. Verify cached embedder/reranker availability before claiming offline readiness. Preserve destination trust and loopback policy.

Check readiness and relevant query/UI behavior with `$cyclaw-command-run`. Record PID and port. Stop only owned verification services unless asked to leave them running.
