# Benchmarks and evals

How CyClaw measures retrieval and answer quality, what has actually been
measured, and what has not. Four planes, deliberately kept apart: a
deterministic retrieval gate on every PR, an operator dogfood run against the
real local model, an opt-in Anthropic judge, and an opt-in local judge with a
hand-labeled calibration set. None of them is a graph node, a request-path
policy point, or a security control. The tracking issues are
[#1398](https://github.com/cgfixit/CyClaw/issues/1398) (parent) and
[#1395](https://github.com/cgfixit/CyClaw/issues/1395) (live slice).

## The fixture every plane shares

`tests/fixtures/groundedness/` is a synthetic, public-safe corpus of eight
single-chunk documents and a 52-case rubric (`cases.json`) in six categories:
`direct_factual`, `paraphrase`, `two_source_synthesis`, `false_premise`,
`out_of_corpus`, and `injected_content`. Every case declares expected claims,
forbidden claims, and expected source IDs. The two `injected_content`
documents embed one instruction the ingest sanitizer rewrites to `[FILTERED]`
and one plain instruction it lets through; their forbidden claims are the
instructions' payloads. `calibration.json` adds thirty hand-labeled answers for
checking a judge. Counts and categories are owned by
`tests/fixtures/groundedness/README.md` and enforced by `tests/judge_eval.py`;
this page cites them and does not restate the per-category numbers.

Never point this fixture at `data/corpus/` or a production index.

## Plane 1 — deterministic retrieval gate (required CI, no LLM)

`python -m tests.ci_rag_smoke` runs on every PR in `ci.yml`. It first builds
the real ChromaDB + BM25 index from `data/corpus/` and checks four queries
against the configured `retrieval.min_score` and `min_semantic_score` gates,
then builds an isolated index from the fixture and computes macro hit@5,
Recall@5 and MRR over the source-labeled cases (the `out_of_corpus` cases are
skipped). It also requires each `injected_content` document's retrieved chunk
to be a `sanitize_chunk` fixed point containing `[FILTERED]`, proving the
ingest sanitizer neutralized the banned phrasing before it could reach a
prompt. The floors live in `tests/ci_rag_smoke.py` and were set from a
measured `origin/main` run, not invented; they are the blocking gate.

## Plane 2 — operator dogfood against the real local model (opt-in)

`CYCLAW_EVAL_DOGFOOD=1 python scripts/cyclaw-eval-dogfood.py` builds the
isolated fixture index, runs one case per category plus a sanitizer probe, and
calls the loopback local model when it is up. Rows are `generated`,
`retrieval_only`, `unverified`, `PASS` or `FAIL`; a down model produces
`unverified`, never a green matrix. Output is `logs/evals/dogfood_matrix.md`
(gitignored). The recipe, the named-environment checklist, and the manual
recovery steps are in `tests/fixtures/groundedness/DOGFOOD.md`. This plane
answers "does the shipped model actually run and answer on a named box", not
"how good is it".

## Plane 3 — forensic Anthropic judge (opt-in, spends money)

`CYCLAW_EVAL_LIVE=1 python tests/judge_eval.py` with `ANTHROPIC_API_KEY` set
generates an answer per case with the local contestant, has Claude grade it
against the expected and forbidden claims, and writes a metadata-only report
to `logs/evals/` (case IDs, scores, reason codes, source IDs; never queries,
answers, evidence or claim text). Thresholds are constants in
`tests/judge_eval.py`. Required CI never sets `CYCLAW_EVAL_LIVE` or a provider
key; `tests/test_judge_eval.py` pins that. The threat-model scope is the
thirteenth amendment in `docs/THREAT_MODEL.md`.

## Plane 4 — local judge and calibration (opt-in, fully local)

Setting `evals.local_judge.enabled: true` in `config.yaml`, with a `model` tag
of a different family from `models.local_llm.model`, makes the same
`judge_eval.py` command grade with a second loopback model and drop the
Anthropic key requirement. `CYCLAW_EVAL_LIVE=1 python tests/judge_calibrate.py`
runs only the judge over the thirty hand-labeled rows and reports pass,
supported, contradicted and forbidden agreement (report only; set a floor from
a measured run). The intended cadence is a nightly cron or launchd job on the
operator's box, with `python -m metrics` printing the last ten runs from
`logs/evals/eval_runs.jsonl`. It is not a GitHub Actions workflow: required CI
never runs the live script and there is no self-hosted runner.

Why no position swapping or majority voting: the rubric is pointwise (one
answer, one verdict) at temperature 0, so swapping positions has nothing to
swap and repeated rounds return the same verdict. The mitigations that apply
are a different model family from the contestant and the calibration set.

## What has been measured

| Date | Commit | Plane | Result |
|---|---|---|---|
| 2026-09-12 | `da8e771` (PR #1399) | 1 | 20 scored cases: hit@5 1.0, Recall@5 1.0, MRR 1.0 on Ubuntu and macOS CI |
| 2026-09-12 | `7f6b550` (PR #1400) | 2 | Five `generated` rows on `qwen3.8:27b-mlx`, M5 Pro 48 GB; recovery steps walked — [`docs/audits/2026-09-12_Local_Qwen_Dogfood_Matrix.md`](audits/2026-09-12_Local_Qwen_Dogfood_Matrix.md) |
| 2026-09-16 | [#1410](https://github.com/cgfixit/CyClaw/pull/1410) | 1 | 44 scored cases after growing the fixture to 52: hit@5 1.0, Recall@5 1.0, MRR 1.0; injected evidence sanitized (local run, Python 3.12, CPU) |

## What has not been measured

- No `judge_eval.py` result (plane 3 or 4) has been published in-repo, so
  there is no groundedness or completeness number for the shipped model.
- No calibration agreement rate for any judge; the calibration set exists but
  has not been run against a model.
- Nothing on hardware other than the M5 Pro 48 GB box, and nothing on the
  52-case fixture with a live model.
- No production-corpus or customer outcome: every number above is on the
  synthetic fixture or the four `data/corpus/cyclaw_overview.md` queries.

## Commands

```bash
GROK_API_KEY=dummy python -m tests.ci_rag_smoke            # plane 1, what CI runs
CYCLAW_EVAL_DOGFOOD=1 python scripts/cyclaw-eval-dogfood.py # plane 2, local model up
CYCLAW_EVAL_LIVE=1 python tests/judge_eval.py               # plane 3 (or 4 via config.yaml)
CYCLAW_EVAL_LIVE=1 python tests/judge_calibrate.py          # plane 4 calibration
python -m metrics                                           # eval-run trend section
```
