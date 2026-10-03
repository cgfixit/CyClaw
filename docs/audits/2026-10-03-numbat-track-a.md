# Numbat Track A acceptance — 2026-10-03

Scope: [issue #1486](https://github.com/cgfixit/CyClaw/issues/1486), Track A,
on main `b3f4ff817097370f97cd42c0c79520ecee8c034d` plus this change.
Track B's NeMo implementation and README updates already merged in #1534
and #1535. The latest issue comment correctly identified the existing CEL
call in `gate.py` after graph completion and audit. No second call was added.

## Changes and defaults

The real Numbat CLI allowed a monitor-only rule set, but CyClaw's readiness
check rejected it because it had no enforcing rule. Readiness now accepts
that supported trial mode. Missing binaries, invalid rules, timeouts, missing
canary matches, and unrecognized verdicts still fail closed.

`config/numbat/gate/` supplies two monitor-only rules with six companion
cases. They observe external calls and model tags outside the prepared list.
Both wheel and source archives include all four YAML files. Config selects
`engine: numbat` and this directory. Two populated CEL expressions observe
weak-retrieval cloud answers and hook/guardrail refusals. Enabled CEL gets a
public `/health` service that reports dependency and compilation readiness
with fixed errors. It neither executes trial inputs nor certifies delivery.

The stream remains on, while the hook and CEL remain off. The CLI and
`numbat-cel` extra are absent from standard/full installs; a default-on CLI
hook would deny confirmed cloud calls on those installs. Operators must
install dependencies, enable each evaluator, and review monitor matches
before promoting rules. The stream, hook, and CEL switches are independent.
Local NDJSON is the selected alert destination. Continuous stream consumption
and production-corpus policy calibration remain outside this acceptance.

## Direct runtime and Computer Use

The isolated macOS arm64 environment used Python 3.12.14, NeMo 0.24.0,
cel-python 0.5.0, and the official Numbat 0.2.0/schema 0.3.0 binary. The
Darwin archive SHA-256 was
`192512a128d3cb845f104ecddc885639ffb99d5fd9ac0249a217612b65a1ff32`.
The gateway used a synthetic Cedar corpus, cached embeddings, dummy cloud
credentials, counted synthetic cloud clients, and a loopback OpenAI-compatible
proxy. One query relayed to the existing local `qwen3.8:27b-mlx` model;
controlled model responses made the refusal scenarios deterministic.
Candidate production source hashes matched the files in the runtime copy.

Chrome's actual gateway console was operated through Computer Use before
README edits. Observed results:

| Scenario | Result |
|---|---|
| Healthy hook and CEL | Both services ready in the console's health details |
| Grounded local query | Correct thirty-day retention answer; one counted generation |
| External request without consent | Confirmation UI; no cloud generation |
| Confirmed Grok, monitor-only rules | Answer delivered; monitor match recorded |
| Disposable rule promoted to enforce | Confirmed Grok refused; no additional provider call; hook ready after its companion case was updated |
| Invalid CLI rule | Public health degraded; confirmed Claude refused with `hook_failure`; no provider call |
| NeMo input and output refusals | Input refusal made no generation call; output refusal replaced one controlled response; CEL observed the refusals |
| Real local-model answer | Correct retention response in 8.336 seconds; guardrails ready and not degraded |
| Invalid CEL plus forced unsupported NeMo engine | CEL health showed a fixed compilation error; query succeeded through deterministic guardrail fallback and audited degradation |
| Hook, CEL, stream, and guardrails disabled | Query answered; optional health services absent; no Numbat file produced |

The combined runtime tests additionally cover all eight hook/CEL/stream switch
combinations, unavailable dependencies, true subprocess timeout, both cloud
providers, and NeMo disabled, enabled, and degraded states. Cloud transport and
paid provider behavior were not tested. Synthetic clients establish call
accounting and policy behavior; they do not establish model quality.

## Finite monitor trial

Forty sequential, interleaved CLI/CEL evaluations covered eight structured
field scenarios five times: weak Grok and Claude, Grok at the score boundary,
weak local and best-effort answers, hook refusal, and guardrail refusal in
both local and blocked roles.
All 40 CLI proposals were allowed with the expected watch match. CEL produced
25 expected observations, zero unexpected observations, and zero errors.
These deliberately selected inputs do not measure production false positives.

| Measurement | Cold first call | Warm median (39 calls) | Warm range |
|---|---:|---:|---:|
| CLI version check, rule snapshot, and decision | 36.00 ms | 25.60 ms | 24.10–28.79 ms |
| CEL compilation and evaluation | 77.13 ms | 0.787 ms | 0.666–1.137 ms |

The disabled evaluator path took a median 0.00146 ms. The machine exposed
18 CPUs and load averages 4.22/5.18/7.86 at capture. Measurements used
`perf_counter`, one process, no concurrent load generator, and include cold
imports only in the first sample. No speedup or general latency guarantee is
claimed. CEL's configured budget warns after evaluation; it cannot interrupt
a costly expression.

Ten actual HTTP Claude queries with retrieval, CLI, NeMo, and CEL enabled had
a median 81.81 ms (79.32–88.57 ms), zero errors, and exactly ten controlled
cloud generations. Across the normal browser/HTTP run's 22 authoritative audit
records, hook reasons were 11 allowed, 2 denied, 1 failure, and 8 not run.
Consent pauses are separate HTTP requests with their own audit records.
Synthetic prompt/response canaries were absent from application and console
logs, authoritative audit, guardrail metrics, and Numbat events. Raw logs and
screenshots remain local because the stream includes endpoint identifiers.

## Automated evidence and boundaries

- Pinned CLI rules check: two rules compiled, six companion cases passed.
- Gate regressions with the real CLI required: 142 passed.
- CEL and health regressions with CEL required: 166 passed.
- Full focused real-NeMo runtime workflow command:
  `python -m pytest tests/nemo_runtime -q --tb=short`: 104 passed, including
  33 combined Numbat cases. Required dependency flags prevented silent skips.
- Invariant guard: 46 passed. Touched-path Ruff F/B/S and Actionlint with
  ShellCheck passed. Wheel and sdist rule inclusion was inspected directly.

The runtime lane's privacy checks observe actual application-file and console
handlers. Pytest 9 attaches capture handlers inside non-propagating SDK logger
namespaces; capturing there observes events before CyClaw's containment
boundary and is not evidence of an application-log leak.

The workflow now installs the checksummed Linux CLI and CEL extra alongside
NeMo before running the combined lane. Linux installation and broad regression
coverage belong to hosted CI; local macOS evidence does not substitute for
them. Consult the PR's exact-head checks for those results.

No graph nodes, edges, consent rules, soul write paths, sanitizer patterns,
or core/out-of-band import boundaries changed. Retrieval remains first,
denials converge on audit, and monitor observations never grant permission.
