# Groundedness evaluation fixtures

This directory contains a deliberately fictional, public-safe corpus and the
fixed 24-case rubric used by `tests/judge_eval.py`. It must never contain or
reference an operator's `data/corpus/`, production `index/`, personal data, or
secrets.

The corpus names, organizations, measurements, and relationships are synthetic.
Each case declares expected claims, forbidden claims, and expected source IDs.
Live reports store only case IDs, scores, reason codes, and source IDs; they do
not persist queries, answers, evidence excerpts, or claim text.

`calibration.json` holds 30 hand-labeled answers to these cases (each with the
claim IDs a correct judge should mark supported, contradicted, or forbidden,
and whether the case should pass). `tests/judge_calibrate.py` runs only the
judge over them and reports agreement, so an operator can check a judge,
especially a local one, before trusting its trend. The answers are synthetic
and public-safe like the rest of this directory.

`python -m tests.ci_rag_smoke` (required CI) also builds an **isolated** index
from this corpus and fails if macro hit@5 / Recall@5 / MRR on the 20
source-labeled cases drop below floors in `tests/ci_rag_smoke.py`. The four
`out_of_corpus` cases are skipped (no relevant documents). No LLM. Do not
point this fixture at `data/corpus/` or a production index.
Metrics use the first five retrieved chunks, matching the evaluator's hit
window. Recall counts each expected source once; reciprocal rank uses the
first matching chunk's original position, without deduplicating the ranking.
