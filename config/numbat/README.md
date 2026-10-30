# `config/numbat/` - pre-action rule examples

[`gate/`](gate/) contains starter rules for the optional external-call hook.
Both are **monitor-only**; neither sets `enforce: true`.

| Rule | Matches |
|---|---|
| `cyclaw.gate.watch_escalations` | Every `network.indicator` event tagged `pre_action_hook`. |
| `cyclaw.gate.pinned_models` | Pre-action model tags outside `gate/pinned_models.yaml`. Update that list and its tests together. |

Each has matching/non-matching `*_tests.yaml` fixtures. From the repo root:

```bash
numbat version  # expected: numbat 0.2.0 (schema 0.3.0)
numbat rules check --no-builtin-rules --rules-dir config/numbat/gate
```

`utils/numbat_gate.py` snapshots the rules and evaluates proposed calls with
`numbat rules test`. An enabled `enforce: true` rule can deny a match.
Malformed rules, empty/disabled sets, wrong CLI versions, timeouts, or missing
evaluation evidence also deny, including under monitor-only policy.
`cyclaw.gate.canary` is reserved for the engine.

Independent [`config.yaml`](../../config.yaml) switches:

- `policy.fallback.pre_action_hook.enabled` ships **false**. Engine `numbat`
  reads `rules_dirs: ["config/numbat/gate"]` only after mode, provider,
  confirmation, and availability gates allow a call.
- `numbat.enabled` ships **true**: derived local NDJSON, without continuous
  evaluation of these rules.
- `numbat.cel.enabled` ships **false**: a separate Python monitor of structured
  query results. Expressions live in `config.yaml`; it cannot block requests.

Copy starters to an operator-controlled directory before customization.
Installation, readiness, fields, and enablement:
[`Numbat hook guide`](../../docs/security-philosophy/numbat_pre_action_gate.md).
