# Numbat pre-action gate for external LLM calls

**Audience:** operators who want a policy check in front of every confirmed
Grok or Claude call, and reviewers of that check. **Code and `config.yaml`
win** over this page: the engine is `utils/numbat_gate.py`, the hook runner is
`utils/external_pre_hook.py`, and the settings live under
`policy.fallback.pre_action_hook` in `config.yaml`. Background on Numbat in
CyClaw: [numbat_secondary_evaluator.md](numbat_secondary_evaluator.md).
Tracking issue: [#1458](https://github.com/cgfixit/CyClaw/issues/1458).

## What the CyClaw pre-action gate is

The pre-action gate is a synchronous checkpoint in `graph.py`
(`pre_action_hook_grok` / `pre_action_hook_claude`) that runs after the I3
triple gate has already allowed an external call: `app.mode` is `hybrid`, the
provider is enabled, and the user confirmed this query. The gate can only take
that call away. A denied call is answered with `answer_model: "hook-denied"`
and still converges on `audit_logger` (I4). The gate ships disabled; while
`pre_action_hook.enabled` is false the checkpoint is a no-op.

Two engines decide, selected by `pre_action_hook.engine`:

| Engine | What decides | Deny signal |
|---|---|---|
| `command` (default) | the operator's argv, given JSON on stdin (`action`, `provider`, `model`, `query_hash`) | exit code 2; any other non-zero exit, crash, or timeout also denies |
| `numbat` | the pinned Numbat CLI evaluating the proposed call against operator rules | a match of a rule marked `enforce: true`; any engine failure also denies |

Once the gate is enabled, nothing but an explicit allow from the engine lets a
call through. Enabled with an empty `command` also denies: before issue #1458
that case silently allowed every call.

## Why `numbat hook` cannot be the pre-action gate command

Older copies of `config.yaml` suggested
`command: ["numbat", "hook", "pre-tool", "--agent", "cyclaw"]`. That argv
never worked. `numbat hook` speaks the hook protocol of the agent hosts Numbat
supports (Claude Code, Codex, Qwen Code, and others); CyClaw is not one of
them. Verified against the pinned `numbat 0.2.0 (schema 0.3.0)` binary with
CyClaw's payload on stdin, and pinned by
`tests/test_numbat_gate.py::TestAgainstThePinnedCli::test_numbat_hook_cannot_gate_cyclaw_calls`:

| `numbat hook` invocation | Result | What CyClaw's exit-code contract makes of it |
|---|---|---|
| `pre-tool --agent cyclaw` (the old suggestion) | `hook: unknown agent "cyclaw"`, exit 0 | allow |
| `PreToolUse --agent claude --enforce` with a match-everything enforce rule | JSON `permissionDecision: "deny"` on stdout, exit 0 | allow |
| `PreToolUse --agent qwen --enforce` with a rule on `event.model_provider == "xai"` | `{}`, exit 0: the adapter drops the provider, so the rule never fires | allow |
| `PreToolUse --agent qwen --enforce` with a match-everything enforce rule | exit 2 | deny, but only "deny everything" is expressible |
| a mistyped event name | usage text, exit 0 | allow |

A real agent adapter parses CyClaw's payload as that agent's own generic tool
call, so the provider, URL, and query hash never reach a rule. The most
`numbat hook` can do for CyClaw is deny every call, which disabling the
provider already does, while any error allows. The `numbat` engine exists to
close that gap.

## How the Numbat engine decides a proposed call

The `numbat` engine (`utils/numbat_gate.py`) asks Numbat a question it
answers deterministically: `numbat rules test`, the same evaluator the CI
fixture jobs run.

1. CyClaw builds the proposed call as one schema-0.3.0 event with
   `utils.numbat_emitter.build_event`, the builder the Numbat stream uses:
   `event_type: "network.indicator"`, `decision: "asked"`,
   `tool_name: "external_llm_call"`, `model` (the configured tag),
   `model_provider` (`"xai"` or `"anthropic"`), `url` (the provider's
   `base_url` with any userinfo, query and fragment removed, so a credential
   configured into it never reaches a rule or a file),
   `tags: ["cyclaw", "pre_action_hook", "<provider>"]`, and the
   `endpoint` host fields. The query is present only as its SHA-256, inside
   `content_preview`, and not at all when
   `logging.audit_fields.include_query_hash` is false.
2. `numbat version` must print the pinned line, `numbat 0.2.0 (schema
   0.3.0)`, on every call. `/health` checks it too, but `/health` only
   advises; a different binary (`/bin/true`, another release) denies the call
   itself.
3. A private temp directory receives the event, a byte-for-byte snapshot of
   each rule directory, and the engine's canary rule. Then
   `numbat rules test --fixture <file> --no-builtin-rules --rules-dir <snapshot> ... --rules-dir <canary>`
   evaluates the event against the operator's rules only. The shipped catalog
   is detection-only, so it is not loaded. The engine classifies the same
   bytes Numbat reads, so an edit that lands mid-request cannot pair one
   version's `enforce` flag with another version's match.
4. The canary rule, `cyclaw.gate.canary`, matches every call. A run that does
   not report it denies. Exit 0 with no output is also what `/bin/true` or a
   CLI that skipped the event prints, so only the canary's match shows that
   the rules actually ran against this call.
5. A match of a rule with `enforce: true` denies. A match of a rule without it
   is a monitor match: the call is allowed and the match is reported. That is
   Numbat's own rule semantics: severity never blocks, `enforce: true` does.
6. The temp directory is deleted.

Every failure denies:
- a missing binary, or one that is not the pinned release;
- a missing or empty `rules_dirs`, or a rules file that cannot be read;
- a rule that does not compile, a duplicate rule id, all rules disabled, or a
  rule that uses the reserved id `cyclaw.gate.canary`;
- a timeout, a non-zero exit, output the engine cannot parse, a run that does
  not report the canary, or a matched rule id the engine did not find in the
  rule files.

Each evaluation spawns the binary twice (the version check, then `rules
test`) within one `timeout_sec` budget. Measured end to end at a median of
17 ms (p90 19 ms; Linux x86_64, the two example rules), against a default
`timeout_sec` of 5.

## Enabling the Numbat engine for the pre-action gate

1. Install the pinned CLI where CyClaw runs. CI installs it from the release
   archive `numbat_0.2.0_linux_amd64.tar.gz` checked against sha256
   `6513d8cec69ea4a55667b0a764b93b7cef8fe814c2ef9e2535aaf438f11f1548`
   (`.github/workflows/numbat-rules.yml`). CyClaw never vendors or imports
   Numbat; it is an external Go binary. `numbat version` must print
   `numbat 0.2.0 (schema 0.3.0)`.
2. Copy `tests/fixtures/numbat/gate-rules/` to a directory the operator
   controls and edit the rules. Check them, including their companion tests:
   `numbat rules check --no-builtin-rules --rules-dir <dir>`.
3. Set the block in `config.yaml` and restart (config is read once at boot):

   ```yaml
   pre_action_hook:
     enabled: true
     engine: numbat
     numbat:
       binary: "numbat"          # or an absolute path
       rules_dirs: ["/etc/numbat/cyclaw-gate"]
     timeout_sec: 5
     verdict_mode: enforce
     emit_verdict: true
   ```

4. Check `GET /health`: an enabled gate appears as service `pre_action_hook`,
   and `/health` reports `degraded` while the gate would deny every call
   (binary missing, wrong version, rules that fail `rules check`) or could
   never deny one (no `enforce: true` rule). Boot refuses a malformed block,
   for example `enabled: "true"` as a string, an unknown engine,
   `verdict_mode: monitor`, or an enabled engine with nothing to run.

## Writing rules for the CyClaw pre-action gate

Gate rules are ordinary Numbat operator rules (one YAML object per file; see
Numbat's `docs/rules.md` in the release archive). The event they see is the
`network.indicator` described in "How the Numbat engine decides a proposed
call". Two examples ship in `tests/fixtures/numbat/gate-rules/`, each with a
companion `*_tests.yaml` that `numbat rules check` runs:

- `cyclaw.gate.pinned_models` (`enforce: true`) denies a call whose model tag
  is not on a vetted list. It still holds if `config.yaml` is edited to a new
  model: the call is denied until the tag is added to the rule too.
- `cyclaw.gate.watch_escalations` (no `enforce`) matches every gated call and
  only reports it.

A new policy should start without `enforce: true`. Its matches then appear as
`monitor_match:<rule id>` tags on the allowed verdict events (with
`emit_verdict: true`) while every call still goes through. Once the matches look
right, add `enforce: true`. That is the observe-only trial; there is no
`verdict_mode: monitor`, which would let a real deny through and needs its own
dual-run observation issue first. To stop gating, set `enabled: false`: a gate
whose rules are all disabled denies every call, because `numbat rules test`
exits non-zero with nothing to run.

Each call reads its rules once, into the snapshot described above. To change
several rules at once, build the new set in a fresh directory and switch a
symlink that `rules_dirs` points at. The engine resolves each rules directory
once per call, so a call sees the old set or the new one, never half of each.
Editing files in place is safe for one file at a time. The rule id
`cyclaw.gate.canary` is reserved for the engine.

## Pre-action gate reason codes and where they show up

Every decided verdict carries one `reason_code`
(`utils.external_pre_hook.REASON_CODES`):

| Reason code | Verdict | Meaning |
|---|---|---|
| `hook_allowed` | allow | the command exited 0, or no `enforce: true` rule matched |
| `hook_denied` | deny | policy: the command exited 2, or an `enforce: true` rule matched |
| `hook_timeout` | deny | the command, the version check, or `numbat rules test` ran past `timeout_sec` |
| `hook_error` | deny | the command or the numbat binary could not be started, or a rules file could not be read |
| `hook_failure` | deny | a bad exit code, a Numbat error, unparseable output, or no canary match |
| `hook_misconfigured` | deny | an empty command, no `rules_dirs`, a missing rules directory, an unknown engine, a binary that is not the pinned release, or a rule using the reserved canary id |

The code appears in four places:

- the audit record, as `pre_action_hook_reason` (only when an enabled gate decided);
- `cyclaw-metrics`, as "Pre-action hook verdicts" counted by reason, with the
  last one (also in `GET /audit/summary`);
- the Numbat stream, as a tag on the verdict event, when `emit_verdict` is true;
- process logs, with the free-text reason.

The free-text reason (a command's stderr, or the Numbat rule ids) is kept out
of the Numbat stream and out of `/health`. A column of `hook_timeout` or
`hook_error` means the gate is failing closed, not that policy is denying.

## Pre-action gate verdicts in the Numbat stream

With `emit_verdict: true` (the shipped value; a config that omits the key
keeps the old default, false) and `numbat.enabled: true`, each decided call
adds one event to `logs/numbat-events.ndjsonl`:

| Verdict | Event | Decision | Confidence |
|---|---|---|---|
| allow | `network.indicator` with the provider `url` (credentials stripped) | `allowed` | high |
| policy deny (`hook_denied`) | `permission.denied` with `approval_reason: "hook_denied"` | `denied` | high |
| gate failure (any other deny) | `network.indicator` with the provider `url` | `denied` | low |

Each event is tagged `pre_action_hook`, its reason code, and `engine:<name>`.
It carries `evidence.artifact_type: "pre_action_hook"` and, unless
`include_query_hash` is false, `{"query_hash": ...}` in `content_preview` as
the join key to the `rag_query` record. A failure to write the event never
changes the verdict (`tests/test_graph.py::TestPreActionHookEnginesAndVerdicts`).

## What the Numbat pre-action gate does not do

- It does not score the rolling Numbat stream or enforce Numbat rules outside
  this checkpoint; that is Phase 5 of issue #1458 and needs its own dual-run
  observation issue.
- It evaluates one event per call, so Numbat sequence rules (for example "a
  secret read, then egress") cannot match yet: the proposed call is not joined
  to earlier events.
- It never sees the query text or the answer, only their shape.
- It never widens I3: a call reaches this gate only after the triple gate
  allowed it, and the gate's only outcomes are "proceed as allowed" and "deny".
