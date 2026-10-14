---
name: cyclaw-command-run
description: "Run focused, authorized smoke probes against an existing CyClaw environment or server. Use for health, query, terminal or route verification; use cyclaw-run-cyclaw for installation, indexing or startup."
---


# Smoke an Existing Environment

Identify the requested behavior and server/checkout/config. Use an isolated
instance for query or mutation probes because even queries write audit state.
Do not install, rebuild an index, start a service or instantiate soul managers.

Probe only relevant routes, with bounded timeouts and synthetic input. Read
current auth and body shapes from `gate.py` and its route modules. Check actual
status/headers/body and side effects; HTML 200 alone does not prove its assets.
Use `$verification-specialist` for independent acceptance or edge-case coverage.

Keep `user_confirmed_online` false for ordinary smoke. Do not enable external
health probes or relax trusted destinations/key bypass to make a request pass.
Use fixture credentials without printing them. Preserve CSRF/RBAC/origin and
peer/proxy distinctions. A missing index has an expected 503 path.

Run `python -m tests.ci_rag_smoke` only in a prepared disposable environment
when retrieval is relevant; it can load models and index state. Follow
`CLAUDE.md` section 5 for further checks. Report mock versus real evidence,
denied/error cases, exit/status codes and unavailable lanes.
