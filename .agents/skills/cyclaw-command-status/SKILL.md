---
name: cyclaw-command-status
description: "Inspect CyClaw configuration, assets and readiness read-only. Use for status requests on a checkout or already-running gateway."
---

# Inspect Status

Read effective config and storage paths. Check Python, the selected lock profile, package metadata, soul and index without importing initializing modules or constructing soul managers.

Report mode, bind/port, auth, memory, connectors, guardrails, trusted local destinations and optional key bypass. Report only credential presence. Distinguish shipped switches from per-request consent.

For an in-scope, identified running gateway, consult `api.health_probe_external_providers` before a bounded probe at its configured port:

```text
curl --connect-timeout 2 --max-time 5 -sS http://127.0.0.1:8787/health
```

Identify readiness gaps and optional-service degradation. Use the OTel checker for suppression claims. Leave packages, data, baselines and services untouched.
