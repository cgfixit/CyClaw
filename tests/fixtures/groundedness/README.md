# Groundedness evaluation fixtures

This directory contains a deliberately fictional, public-safe corpus and the
fixed 24-case rubric used by `tests/judge_eval.py`. It must never contain or
reference an operator's `data/corpus/`, production `index/`, personal data, or
secrets.

The corpus names, organizations, measurements, and relationships are synthetic.
Each case declares expected claims, forbidden claims, and expected source IDs.
Live reports store only case IDs, scores, reason codes, and source IDs; they do
not persist queries, answers, evidence excerpts, or claim text.

`python -m tests.ci_rag_smoke` (required CI) also builds an **isolated** index
from this corpus and fails if macro hit@5 / Recall@5 / MRR on the 20
source-labeled cases drop below floors in `tests/ci_rag_smoke.py`. The four
`out_of_corpus` cases are skipped (no relevant documents). No LLM. Do not
point this fixture at `data/corpus/` or a production index.

