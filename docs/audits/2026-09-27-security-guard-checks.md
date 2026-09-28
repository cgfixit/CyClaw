# Security guard checks on 2026-09-27

This report records the maintained invariant, telemetry, and prompt-filter checks from a branch based on `54669c3e` on `origin/main`. The branch corrects how the telemetry checker reads the ONNX Runtime pin in `environment.yml`. It changes no runtime policy or configuration.

## Results

| Check | Result | Evidence |
| --- | --- | --- |
| Invariant guard | Pass | The static checker reported 46 passes and zero failures across I1-I6 and G1-G5. Its self-test detected all four injected violations. |
| Telemetry hardening | Pass | The strict checker reported zero failures and zero warnings across T1-T14. It now recognizes the `onnxruntime==1.30.0` entry in the Conda environment's pip subsection. Its mutation self-test passed, including a case that removes that entry. |
| Injection red team | Pass for the maintained corpus | The runner evaluated 48 probes: 36 blocked and 12 allowed, with no new bypasses, open findings, or false positives. Its self-test detected a disabled filter. |
| Focused behavior tests | Pass | The sanitizer, telemetry, ONNX, MCP, gateway prompt-injection, and graph test selections passed with `GROK_API_KEY=dummy`. |

The telemetry checker reports two standing informational limits: the `fastembed` and `transformers` transitive dependencies have no version bound in the manifests. These are not strict-checker warnings. Its installed-package metadata lookup reports ONNX Runtime 1.28.0 in the local test environment, while importing the module reports 1.30.0. Three ONNX Runtime distribution metadata directories are present there, so the metadata result does not identify the imported runtime version.

## Reproduce

Run these commands from the repository root with the project Python environment active:

```sh
python .claude/skills/invariant-guard/check_invariants.py
bash .claude/skills/invariant-guard/verify.sh
python .claude/skills/otel-hardening/check_otel.py --strict --as-of 2026-09-27
bash .claude/skills/otel-hardening/verify.sh
python .claude/skills/injection-redteam/redteam.py --json
bash .claude/skills/injection-redteam/verify.sh
GROK_API_KEY=dummy python -m pytest tests/test_sanitizer.py tests/test_telemetry_kill.py tests/test_telemetry_env_delivery.py tests/test_onnx_telemetry.py tests/test_mcp_server.py -q --tb=short
GROK_API_KEY=dummy python -m pytest tests/test_gate.py::TestPromptInjection tests/test_graph.py -q --tb=short
```

The self-tests deliberately mutate temporary copies or temporary configuration. The focused tests use fixtures and a dummy provider key. This run did not test live model quality, real provider calls, or whether every vendor version suppresses all network egress. The prompt-filter result applies to the maintained corpus only.
