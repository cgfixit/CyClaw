---
name: otel-hardening
description: "Verify CyClaw telemetry suppression, SDK import order and child environments after telemetry, heavy-import, dependency or egress changes."
---

# Verify Telemetry Suppression

Inspect `utils/telemetry_kill.py`, `utils/onnx_telemetry.py` and startup paths. Run `python .claude/skills/otel-hardening/check_otel.py`.

Trace SDK reads and child environments. Preserve suppression before initializing imports and the ONNX post-import API. Assess model downloads and vendor telemetry independently. Environment flags alone cannot establish network confinement.

Exercise the changed path with synthetic inputs, no credentials and controlled egress where available. Keep suppression enabled. Run the maintained `verify.sh` for checker edits and the invariant guard for core imports. Report vendor and runtime gaps.
