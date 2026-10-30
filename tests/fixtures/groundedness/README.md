# Groundedness evaluation fixtures

This directory contains a deliberately fictional, public-safe corpus and the
fixed 52-case rubric used by `tests/judge_eval.py`. It must never contain or
reference an operator's `data/corpus/`, production `index/`, personal data, or
secrets.

All names, measurements, and relationships are synthetic. Cases specify
expected/forbidden claims and source IDs across six categories:
`direct_factual` (12), `paraphrase` (10), `two_source_synthesis` (8),
`false_premise` (8), `out_of_corpus` (8), and `injected_content` (6).
The injected documents (`sable_bridge.md`, `tern_airfield.md`) each contain
one instruction sanitized to `[FILTERED]` and one surviving instruction.
Facts are expected claims; instruction payloads are forbidden claims.
Every document is one chunk; the five-chunk window often includes injected
documents on other cases. Retrieval floors require expected sources, while
cross-case payload leaks count as unsupported rather than forbidden claims.

Live reports retain IDs, scores, reason codes, and provenance (SHA, model
tags, rubric/index fingerprints, timestamps), never query/answer/evidence or
claim text. `calibration.json` supplies 36 synthetic hand-labeled answers;
`tests/judge_calibrate.py` reports judge agreement before operators trust trends.

`python -m tests.ci_rag_smoke` (required CI) also builds an **isolated** index
from this corpus and fails if macro hit@5 / Recall@5 / MRR on the 44
source-labeled cases drop below floors in `tests/ci_rag_smoke.py`, or if an
`injected_content` document's retrieved chunk still carries a raw banned
pattern (it must be a `sanitize_chunk` fixed point containing `[FILTERED]`).
The eight `out_of_corpus` cases are skipped (no relevant documents). No LLM is
called by that smoke check. Its fixture phase is isolated, but the command
first rebuilds the corpus/index configured by the checkout's `config.yaml`
for the ordinary RAG probes. Run it in a disposable checkout, not against an
operator's production corpus or index.
Metrics use the first five retrieved chunks, matching the evaluator's hit
window. Recall counts each expected source once; reciprocal rank uses the
first matching chunk's original position, without deduplicating the ranking.

## Live judge and calibration runs

From the repository root, with the embedding model already cached and a
loopback local model available:

```bash
CYCLAW_EVAL_LIVE=1 python tests/judge_calibrate.py
CYCLAW_EVAL_LIVE=1 python tests/judge_eval.py
```

Both commands require the literal opt-in above. By default the judge is
Claude and requires `ANTHROPIC_API_KEY`; fixture prompts, evidence, and answers
are sent to that provider and can incur charges. The `evals.local_judge`
configuration instead selects a loopback judge with a model tag different
from the contestant and needs no Anthropic key. Neither path uses the
operator's corpus: each builds a temporary index from this fixture.

Outputs go to `logs/evals/`: `calibration_report.json` reports agreement;
`eval_report.json` holds the latest run and `eval_runs.jsonl` appends its
summary. External judge usage goes to a separate `spend.jsonl` there.
Calibration reports agreement without imposing a passing threshold. The
evaluation command requires at least 90% passing cases, correct abstention
on every out-of-corpus case, and zero contradicted or forbidden claims.
Per-case grounding and completeness thresholds remain in `tests/judge_eval.py`.

For the smaller local-only generation matrix, see [`DOGFOOD.md`](./DOGFOOD.md).
Its `CYCLAW_EVAL_DOGFOOD` opt-in and output are separate from the judge suite.
