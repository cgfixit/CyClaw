# Groundedness evaluation fixtures

This directory contains a deliberately fictional, public-safe corpus and the
fixed 52-case rubric used by `tests/judge_eval.py`. It must never contain or
reference an operator's `data/corpus/`, production `index/`, personal data, or
secrets.

The corpus names, organizations, measurements, and relationships are synthetic.
Each case declares expected claims, forbidden claims, and expected source IDs.
Six categories: `direct_factual` (12), `paraphrase` (10),
`two_source_synthesis` (8), `false_premise` (8), `out_of_corpus` (8), and
`injected_content` (6). The two `injected_content` documents
(`sable_bridge.md`, `tern_airfield.md`) each embed one instruction the ingest
sanitizer rewrites to `[FILTERED]` and one plain instruction it lets through;
their expected claims are the documents' real facts and their forbidden claims
are the instructions' payloads, so a contestant that obeys retrieved text fails.
Every document is a single chunk and the evidence window is five, so the two
injected documents commonly appear as lower-ranked evidence on other cases
as well; the retrieval floors require only that each case's expected sources
are present, and a payload leaking into another case's answer registers there
as an unsupported claim rather than a forbidden one.
Live reports store only case IDs, scores, reason codes, and source IDs; they do
not persist queries, answers, evidence excerpts, or claim text.

`calibration.json` holds 36 hand-labeled answers to these cases (each with the
claim IDs a correct judge should mark supported, contradicted, or forbidden,
and whether the case should pass). `tests/judge_calibrate.py` runs only the
judge over them and reports agreement, so an operator can check a judge,
especially a local one, before trusting its trend. The answers are synthetic
and public-safe like the rest of this directory.

`python -m tests.ci_rag_smoke` (required CI) also builds an **isolated** index
from this corpus and fails if macro hit@5 / Recall@5 / MRR on the 44
source-labeled cases drop below floors in `tests/ci_rag_smoke.py`, or if an
`injected_content` document's retrieved chunk still carries a raw banned
pattern (it must be a `sanitize_chunk` fixed point containing `[FILTERED]`).
The eight `out_of_corpus` cases are skipped (no relevant documents). No LLM. Do not
point this fixture at `data/corpus/` or a production index.
Metrics use the first five retrieved chunks, matching the evaluator's hit
window. Recall counts each expected source once; reciprocal rank uses the
first matching chunk's original position, without deduplicating the ranking.
