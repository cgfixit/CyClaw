---
name: cyclaw-command-status
description: "Inspect CyClaw environment, configured assets and readiness without setup or state changes. Use for status questions; do not start services, import initializing gateway code, install or rebuild."
---


# Inspect Status

Read current config and resolve its effective paths from the selected checkout
and environment. Check Python 3.12, selected install profile/lock and package
metadata without importing initializing modules. Inspect missing soul/index
files as readiness evidence; do not instantiate self-healing managers.

Report safe flags such as mode, bind/port, auth/memory/agentic/guardrail state,
trusted local destinations and API-key optional bypass. Report only whether
credential variables are set, never their values. Shipped hybrid/providers
enabled is intentional; per-request consent remains separate.

Probe an already-running owned/identified local gateway only when in scope:

```text
curl --connect-timeout 2 --max-time 5 -sS http://127.0.0.1:8787/health
```

Use its configured port and inspect whether external health probes were enabled
before making a request. A degraded or stopped optional service is not a core
defect by itself. Use the static telemetry checker for suppression claims.
Return checks, observed state and limits; change no data, baselines or services.
