---
name: otel-hardening
description: "Verify CyClaw telemetry suppression, SDK import order and child environments. Use for telemetry, heavy-import, dependency or egress-policy changes; suppression is not a firewall."
---


# Verify Telemetry Suppression

Read `utils/telemetry_kill.py`, `utils/onnx_telemetry.py`, affected startup/import
paths and the maintained checker. Run:

```text
python .claude/skills/otel-hardening/check_otel.py
```

Trace new SDK/environment reads and child environments; suppression must precede
initializing imports, with ONNX post-import API seams preserved. First-run model
downloads and vendor telemetry have separate policies. An environment-variable
inventory does not prove complete egress blocking.

Exercise the changed path with synthetic data, no credentials and controlled
egress when available. Do not enable telemetry to test its suppression. For
checker changes run `bash .claude/skills/otel-hardening/verify.sh`; for core
import changes run the invariant guard. Report vendor/native/runtime limits and
follow `CLAUDE.md` section 5 rather than a blanket local full-suite gate.
