# `tests/` — the CyClaw test suite

Pytest suite for this directory (`test_*.py` files, auto-collected
via `testpaths = ["tests"]` in `pyproject.toml`). Test trees outside `tests/` —
notably `tools/lora_finetune/tests/`, whose CI is `.github/workflows/lora-finetune.yml` —
are NOT collected by `pytest tests/`; see `CLAUDE.md` §8. Ordinary tests avoid
live LLM/cloud calls, using shared mocks or scoped integration fixtures.
Some exercise real loopback sockets, subprocesses, local databases, and native
platform behavior; optional service tests skip when their prerequisites are absent.
A fresh clone has **no** Python deps installed; install first (see `CLAUDE.md`
§4 "Environment & install") before running anything here.

## Running

For routine changes, exercise the affected behavior and run relevant lint or
static checks first. Hosted CI owns broad regression and coverage runs. Use one
focused test file when it covers a concrete risk that direct execution cannot
verify (`CLAUDE.md` §5).

```bash
GROK_API_KEY=dummy python -m pytest tests/test_graph.py -q  # focused example
GROK_API_KEY=dummy python -m tests.ci_rag_smoke             # real-index RAG smoke
GROK_API_KEY=dummy python -m pytest tests/ -q --tb=short    # CI/owner full-suite run
```

Routine tests need no real provider key (`GROK_API_KEY=dummy`). The RAG smoke
rebuilds the configured corpus/index (the shipped corpus is `data/corpus`) and
exercises real retrieval/routing without generation. Use a disposable checkout
if an existing index must be preserved; seed the embedding and enabled reranker model caches
first if it must run with `HF_HUB_OFFLINE=1`. Its `--with-docs` variant builds
an isolated temporary index and reports scores without asserting the probe
outcomes. Run pytest through a Python 3.12 venv
(`requires-python >=3.12,<3.13`); a 3.11 host interpreter fails on 3.12-only
stdlib calls (recipe in `CLAUDE.md` §4 "Environment & install").

The optional groundedness evaluator is a separate live-spend command and is not
part of required CI:

```bash
CYCLAW_EVAL_LIVE=1 python tests/judge_eval.py
```

It needs `ANTHROPIC_API_KEY` and a running loopback local LLM, uses only the
tracked synthetic corpus under `tests/fixtures/groundedness/`, and keeps its
reports and isolated index ignored under `logs/evals/`. Exit 0: rubric passed;
1: a complete run missed a threshold; 2: refused or incomplete (including a
missing gate). `evals.local_judge.enabled: true` (with a `model` tag different
from `models.local_llm.model`) swaps the Anthropic judge for a second loopback
model — no `ANTHROPIC_API_KEY`, nothing leaves the host, `CYCLAW_EVAL_LIVE=1`
still gates. Before trusting any judge, run the hand-labeled calibration set
(36 rows in `tests/fixtures/groundedness/calibration.json`, judge only):

```bash
CYCLAW_EVAL_LIVE=1 python tests/judge_calibrate.py
```

It prints pass / supported / contradicted / forbidden agreement rates and
writes `logs/evals/calibration_report.json`; it is report-only, so set a floor
from a measured run rather than inventing one. The nightly trend is an
operator-box job, not GitHub Actions (required CI never runs the live script
and there is no self-hosted runner), for example:

```cron
0 3 * * * cd /path/to/CyClaw && CYCLAW_EVAL_LIVE=1 .venv/bin/python tests/judge_eval.py >> logs/evals/nightly.log 2>&1
```

`python -m metrics` then prints the last ten runs from `logs/evals/eval_runs.jsonl`
(`logging.eval_runs_file`). Nothing on the request path or in CI reads that
trend, so it is non-blocking by construction.

## Coverage

Bare `pytest` runs **no** coverage — the 80% gate (`fail_under` in
`pyproject.toml` `[tool.coverage.report]`) applies only when CI's explicit
`--cov=` flags are passed. Both `.github/workflows/ci.yml` and
`.github/workflows/python-package-conda.yml` use one flag per entry in
`[tool.coverage.run] source`. Package flags such as `--cov=utils`,
`--cov=retrieval`, and `--cov=sync` cover new nested modules automatically.
A new top-level coverage source needs an entry in all three places;
`test_ci_coverage_flag_contract.py` checks their agreement. New test files are
auto-discovered and need no coverage-source entry.

## Layout and special files

| Path | What it is |
|---|---|
| `conftest.py` | Shared config, retriever, and LLM fixtures. `test_config` is a **deepcopy** on purpose — a shallow copy leaks mutations across tests (`test_conftest_fixtures` guards this). |
| `ci_rag_smoke.py` | Deliberately NOT `test_*`-named so pytest ignores it; runs as a separate CI step against a real index. Renaming it double-runs it and drags ChromaDB into the unit lane. |
| `judge_eval.py` | Default-off 52-case groundedness evaluator. Builds an isolated real Chroma/BM25 index; the opt-in judge is Claude or a second loopback model. See `docs/EVALS.md`. |
| `rerank_probes.py` | Answer keys for every answerable RAG probe, plus a fresh held-out probe set, for choosing the reranker veto (issue #1456). Labels a window by whether an answer key is in it, never by a model score. Read by `scripts/rerank_bakeoff.py` and `test_rerank_bakeoff.py`; no heavy imports. |
| `judge_calibrate.py` | Runs the selected judge over 36 labeled fixture answers without generating contestant answers; reports agreement, not a CI gate. |
| `TEST_SUITE_AUDIT.md`, `VERIFICATION_REPORT_3.12.md` | Point-in-time audit reports, kept beside the suite they audited. |
| `apipsTest.ps1`, `cmd2index.bat` | Windows-side manual helpers; not collected by pytest. |
| `nemo_runtime/` | Real NeMo engine, combined NeMo/Numbat CLI/CEL gateway HTTP acceptance, and logging privacy checks with a loopback-only harness (`network_jail.py`, `mock_openai.py`); collected with the main suite and skipped unless `CYCLAW_NEMO_RUNTIME=1`. |
| `spend_live_probe.py` | Opt-in live spend probe, not `test_*`-named, so not collected. |
| `import_graph.py` | The AST import walker shared by the six `test_*_isolation.py` I6 guards; not collected. |
| `numbat_shaped_events.py` | Drives one representative event per producer family (mainline audit projection, pre-action hook verdicts, CEL monitor, ops/fsconnect) into a throwaway stream; `python -m tests.numbat_shaped_events --frozen --out ...` regenerates `fixtures/numbat/cyclaw-shaped-*.ndjson`. Not collected; `test_numbat_cyclaw_shaped.py` and `numbat-rules.yml`'s `numbat-stream-contract` job hold its output to the pinned Numbat CLI and schema (issue #1458). |

## Conventions that bite

- Never `import gate` at a test module's top level — it triggers full app init
  (FastAPI + ChromaDB + retriever). Use a subprocess (`test_telemetry_kill`)
  or module-level patching (`test_gate`).
- The conftest mock retriever's `min_score` (0.75) is intentionally different
  from production (0.028, RRF scale) — both are load-bearing; do not unify.
- `MockGrokClient` defaults `available=True`; pass `available=False` to
  simulate a missing API key.
- POSIX-only modules (`pty`, `termios`) must be imported behind an
  `os.name != "nt"` guard — a top-level import aborts collection on Windows
  before any `skipif` marker can run.
- Keep routine tests deterministic and independent of live providers. Socket
  and subprocess integration tests use bounded local fixtures; native-platform
  and optional-service prerequisites must have explicit skips.

## Related

- Commands and environment setup: `CLAUDE.md` §8
- Invariant regression harness: `tests/test_due_diligence_invariants.py` and
  repo-root `INVARIANTS.md`
