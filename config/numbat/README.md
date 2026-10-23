# `config/numbat/` — pre-action rule examples

The [`gate/`](gate/) directory contains the maintained starter rules for
CyClaw's optional external-call hook. Both rules are **monitor-only**: neither
sets `enforce: true`.

| Rule | Matches |
|---|---|
| `cyclaw.gate.watch_escalations` | Every `network.indicator` event tagged `pre_action_hook`. |
| `cyclaw.gate.pinned_models` | A pre-action event whose model tag is outside the reviewed list in `gate/pinned_models.yaml`. Keep that list and its companion tests aligned when changing provider model pins. |

Each rule has a `*_tests.yaml` companion with matching and non-matching
events. From the repository root, with the pinned CLI installed:

```bash
numbat version  # expected: numbat 0.2.0 (schema 0.3.0)
numbat rules check --no-builtin-rules --rules-dir config/numbat/gate
```

`utils/numbat_gate.py` snapshots these files and evaluates each proposed call
with `numbat rules test`. An enabled rule with `enforce: true` can deny a
matching call; malformed rules, an empty/disabled rule set, a wrong CLI
version, a timeout, or missing evaluation evidence also deny. The reserved
rule id `cyclaw.gate.canary` belongs to the engine. Monitor-only policy still
fails closed on engine errors.

The switches are independent in [`config.yaml`](../../config.yaml):

- `policy.fallback.pre_action_hook.enabled` ships **false**. Its selected
  engine is `numbat`, with `rules_dirs: ["config/numbat/gate"]`; it only runs
  after hybrid mode, provider enablement, request confirmation, and provider
  availability allow an external call.
- `numbat.enabled` ships **true** and writes a derived local NDJSON event
  stream. It does not continuously evaluate this directory's rules.
- `numbat.cel.enabled` ships **false**. It is a separate, optional Python
  monitor over structured query-result fields; its expressions live in
  `config.yaml`, and it cannot block a request.

Copy the starter rules to an operator-controlled directory before customizing
an enforcement policy. Installation, readiness checks, event fields, and
enablement instructions:
[`docs/security-philosophy/numbat_pre_action_gate.md`](../../docs/security-philosophy/numbat_pre_action_gate.md).
