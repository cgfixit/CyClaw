---
name: cyclaw-command-run
description: "Smoke-test health, query, terminal or routes on an existing CyClaw instance. Use cyclaw-run-cyclaw for setup, indexing or startup."
---

# Smoke an Existing Environment

Identify the instance, checkout, effective config and requested path. Use isolation for queries and mutations because queries write audit state. Leave installation, indexing and service lifecycle to their owning workflows.

Use bounded timeouts, synthetic input and redacted fixture credentials. Read auth and request shapes from gateway routes. Inspect status, headers, body and side effects, including assets for UI checks. Missing index should return 503 for query.

Keep `user_confirmed_online` false for ordinary smoke. Preserve destination checks, external health settings, key bypass rules, CSRF, RBAC and origin/peer boundaries.

For retrieval, use `python tests/ci_rag_smoke.py` only in a prepared disposable environment. Report exit/status codes, observed refusals and mock limits. Use `$verification-specialist` for independent acceptance.
