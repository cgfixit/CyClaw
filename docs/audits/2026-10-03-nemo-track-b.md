# NeMo Track B acceptance, 2026-10-03

Issue [#1486 Track B](https://github.com/cgfixit/CyClaw/issues/1486#issuecomment-5969523503)
phases 0–4 are implemented and locally verified on `codex/nemo-track-b`.
The fresh clone's base is `ea346fdbf7ca96c1bc7cad348082f0abd81c8105`.
This record describes the candidate before publication, not a merged release
or a hosted CI result. The [current reference](../NeMo/README.md) describes
its configuration and runtime contracts.

The user selected `guardrails.enabled: true` in the shipped configuration.
NeMo remains an optional dependency. Explicit `false` and an absent block
retain the disabled behavior. No private corpus or paid cloud calls were
used for this acceptance.

## Phase evidence

| Phase | Result and evidence |
|---|---|
| 0. Install and isolate | Installed `nemoguardrails==0.24.0` in a disposable Python 3.12.14 environment. Installed the plain macOS Torch 2.13.0 wheel first, then the guardrails, test, and dev extras with platform-adjusted constraints. `pip check` was clean; 19 baseline real-engine checks passed |
| 1. Enable and protect failures | Enabled the shipped switch. Reproduced and fixed missing deterministic protection on failed live checks and duplicate generation after wrapper errors. The first integrated gate passed 307 focused checks. Later review added per-engine threshold isolation and SDK log containment |
| 2. Trial and measure | Ten actual local-model queries returned correct facts, with ten model calls and ten audit events. None blocked or degraded. Separate rail and HTTP measurements below isolate check overhead. The threshold remains `0.18` |
| 3. Extend CI coverage | Added 47 gateway HTTP acceptance cases with the real NeMo engine. The matrix covers enabled, disabled, and forced-degraded modes across local, best-effort, Grok, and Claude routes. It checks consent, sanitizer denial, model-call counts, audit convergence, and grounding scope |
| 4. Record declined rails | NVIDIA model-assisted `self_check_input`, `self_check_output`, and `self_check_facts` are declined and inactive. Retained input/facts prompt templates are inert. Active `/query` rails execute Python actions and add no model calls |

The final combined focused run passed **397 checks** with 32 dependency
warnings. A subsequent package import-order correction preserved the
telemetry-kill-first invariant. Its four real-engine privacy checks and all
46 static invariant checks passed afterward. The terminal's controlled
answer smoke also passed after that correction.

## Changes required by verification

The broker now falls back on deterministic checks for a missing engine,
failed check, or unsupported verdict. Input and soul-leak protection cover
every generation route. `None` context excludes grounding only; local
retrieval answers remain grounded against the evidence actually supplied.
Fallback refusal records both `guardrail_blocked` and `guardrail_degraded`.
Unexpected wrapper errors return a generic error without replaying generation.

Independent review found a global grounding threshold shared by cached
engines. Each engine now captures its own threshold, and the threshold is
part of its cache key. A real-engine A/B/A test at thresholds `0.2`, `0.8`,
and `0.2` gives pass, block, pass with zero model calls.

Computer Use found a separate privacy defect. NeMo's INFO events copied raw
query, context, and answer payloads into the application log even when the
answer was refused. The package now contains the `nemoguardrails` logging
namespace before optional imports. It prevents propagation into application
handlers and Python's fallback handler. CyClaw's bounded diagnostics remain
visible. The four privacy regressions failed before the fix and pass after it;
fresh browser logs contain none of the controlled privacy canaries.

## Actual local-model trial

The trial used the full HTTP gateway, a real Chroma/BM25 index, a cached
retrieval embedder, and the local Ollama model `qwen3.8:27b-mlx`. The corpus
was one synthetic Cedar archive document. Personality, reranking, and cloud
providers were disabled in this disposable profile. Generation used a
512-token output cap and the shipped 720-second model timeout.

The ten questions covered retention, full and incremental schedules, restore
drills, checksums, capacity, warning thresholds, recovery objectives, key
storage, and report contents. All answers matched the synthetic source.
Each response joined to one audit event by query hash. Proxy counts recorded
exactly one local model call per request. Results were **0/10 blocked, 0/10
degraded, and 0/10 response errors**. The checksum answer repeated text and included a stray
`</think>` marker, a model-formatting limitation outside guardrail policy.

Observed request latency had a median of **97.244 seconds**, ranging from
**28.679 to 467.503 seconds**. These are end-to-end model responses, not a
measure of guard overhead. An earlier trial with a different model alias
and a shortened 90-second timeout was aborted after model timeouts and is
excluded from the accepted cohort.

This ten-question trial preceded the threshold-isolation and log-containment
follow-ups. The final focused checks and browser runs verified those changes.
Ten benign questions from one synthetic document do not establish a
production false-positive rate or justify threshold tuning.

## Measured check overhead

A direct real-NeMo measurement ran one cold and ten warm input/output check
pairs against a counted loopback service. Persistence was disabled for this
measurement. Cold time was **241.525 ms**. Warm median was **25.251 ms**,
with a range of **24.412–38.730 ms**. It recorded zero model POSTs, blocks,
or degraded decisions.

A separate HTTP A/B/A measurement used the actual gateway, real cached
retrieval, a fixed loopback answer service, and persisted metrics. Each fresh
process received three warmups followed by ten timed requests. No model
inference was included in this comparison.

| Profile | Timed requests | Median | Range |
|---|---:|---:|---:|
| Enabled before | 10 | 30.264 ms | 28.598–32.439 ms |
| Disabled | 10 | 4.245 ms | 3.358–5.434 ms |
| Enabled after | 10 | 30.418 ms | 28.358–33.357 ms |

All 39 requests, including warmups, produced the expected answer, one answer
call, and one audit event. There were **zero extra model calls**. The observed
enabled/disabled median difference was approximately **26 ms** in this
controlled local run. The small sequential A/B/A cohort is a latency estimate
for this fixture, not a production throughput or concurrency benchmark.

## Computer Use acceptance

Chrome exercised the actual terminal at a disposable loopback gateway through
Computer Use. Controlled answers isolated guardrail decisions from model
variability. Corresponding requests, model counts, audit events, and fresh
logs were inspected.

| Browser scenario | Observed result |
|---|---|
| Grounded controlled answer | Displayed the answer with one model call and no block or degradation |
| Soul-mutation input | Displayed refusal before any model call |
| Ungrounded local output | Replaced the generated answer with a grounding refusal |
| Soul-leak output | Replaced an otherwise grounded answer with a soul-leak refusal |
| Offline best-effort after declining online use | Allowed an out-of-corpus answer without applying local grounding |
| Forced IORails engine refusal | Allowed safe fallback with degradation; soul-leak output on local and best-effort paths recorded both blocked and degraded |
| Explicitly disabled profile | Bypassed optional rails; the gateway injection filter still returned HTTP 400 for its prohibited input |
| Privacy regression after the fix | Refused the controlled canary without copying it into application, console, audit, or guardrail logs |
| Actual local model after the fixes | Displayed the correct thirty-day retention answer with one real model request and no block or degradation |
| Final import-order smoke | Displayed the controlled thirty-day answer after preserving telemetry-kill-first ordering |

The actual-model browser response took **348.936 seconds**. Its audit query
hash was `e9202d48c2383993343a6fa47ba5c079c2e01a2f16f2379eb23ecb03a8c063f1`.
The final import-order smoke took **6.189 seconds** and used a controlled
answer. It is separate evidence from the actual-model response.

## Reproduce the automated acceptance

From the repository root, use the Python 3.12 environment and optional extra
from the [setup guide](../../setup-guide.md#install-the-optional-nemo-runtime).
The combined focused command was:

```bash
GROK_API_KEY=dummy HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
CYCLAW_NEMO_RUNTIME=1 python -m pytest -o addopts='' -p no:cacheprovider \
  tests/test_guardrails_broker.py tests/test_guardrails_integration.py \
  tests/test_guardrails_rails.py tests/test_guardrails_isolation.py \
  tests/test_graph.py tests/test_guardrails_config.py tests/test_guardrail_bridge.py \
  tests/nemo_runtime -q --tb=short
```

After the import-order correction, rerun the privacy cases and static checks:

```bash
GROK_API_KEY=dummy HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
CYCLAW_NEMO_RUNTIME=1 python -m pytest -o addopts='' -p no:cacheprovider \
  tests/nemo_runtime/test_logging_privacy.py -q --tb=short
python .claude/skills/invariant-guard/check_invariants.py
```

The real-engine lane uses a loopback socket boundary. Offline model-loader
flags alone do not prevent every network path. Grok and Claude acceptance
uses counted test clients; no live cloud-provider acceptance is claimed.
Raw runtime logs, indexes, and private environment files are not committed.

## Invariants and remaining work

The 12-node graph, retrieval-first entry, external consent gates, audit
convergence, soul-write governance, and core import isolation remain intact.
The 46 static checks complement the runtime tests; they do not replace them.

Track A remains separate. The issue's last comment incorrectly describes
CEL monitoring as unwired. The selected main already invokes
`monitor_request` after graph execution when CEL is enabled, from commit
`ee3794a1`. Remaining Track A work concerns operator enablement, rule choices,
a runtime monitoring trial, and combined Numbat/NeMo acceptance. This change
does not enable the Numbat hook or CEL monitor.

Production corpus calibration, long-running degradation measurements,
live cloud-provider trials, and broader platform coverage remain outside
this local acceptance. Hosted CI status belongs to the draft PR's exact
published head and is reported separately.
