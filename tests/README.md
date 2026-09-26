# `tests/` — the CyClaw test suite

Pytest suite for this directory (213 `test_*.py` files, auto-collected
via `testpaths = ["tests"]` in `pyproject.toml`). Test trees outside `tests/` —
notably `tools/lora_finetune/tests/`, whose CI is `.github/workflows/lora-finetune.yml` —
are NOT collected by `pytest tests/`; see `CLAUDE.md` §8. Ordinary tests avoid
live LLM/cloud calls, using shared mocks or scoped integration fixtures.
Some exercise real loopback sockets, subprocesses, local databases, and native
platform behavior; optional service tests skip when their prerequisites are absent.
A fresh clone has **no** Python deps installed; install first (see `CLAUDE.md`
§4 "Environment & install") before running anything here.

## Running

```bash
GROK_API_KEY=dummy pytest tests/ -q --tb=short          # full suite
GROK_API_KEY=dummy pytest tests/test_graph.py -q        # one file
GROK_API_KEY=dummy python -m tests.ci_rag_smoke         # real-index RAG smoke
```

Use `GROK_API_KEY=dummy` for routine tests; they do not require a real provider
key. The separate RAG smoke loads the embedding model and a real index; seed
the model cache first if it must run with `HF_HUB_OFFLINE=1`.

Python 3.12 is required (`requires-python >=3.12,<3.13`). Build a 3.12 venv
and invoke pytest through it; an unsupported host interpreter can fail on
3.12-only stdlib calls (full recipe in `CLAUDE.md` §4 "Environment & install").

The optional groundedness evaluator is a separate live-spend command and is not
part of required CI:

```bash
CYCLAW_EVAL_LIVE=1 python tests/judge_eval.py
```

It also requires `ANTHROPIC_API_KEY` and a running loopback local LLM. Missing
either gate returns exit 2. It uses only the tracked synthetic corpus under
`tests/fixtures/groundedness/`; reports and its isolated index stay ignored
under `logs/evals/`. Exit 0 means the approved rubric passed, exit 1 means a
complete run missed a threshold, and exit 2 means the run was refused or could
not complete.

Setting `evals.local_judge.enabled: true` in `config.yaml` (with a `model` tag
that differs from `models.local_llm.model`) swaps the Anthropic judge for a
second loopback model: the same command then needs no `ANTHROPIC_API_KEY` and
nothing leaves the host. `CYCLAW_EVAL_LIVE=1` still gates the run. Before
trusting any judge, run the hand-labeled calibration set (36 rows in
`tests/fixtures/groundedness/calibration.json`, judge only, no contestant):

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
`--cov=` flags are passed. New modules in `utils`, `retrieval`, and `sync`
need explicit `--cov=<package>.<module>` entries in both `.github/workflows/ci.yml`
and `.github/workflows/python-package-conda.yml`; those lanes enumerate each
module. Whole-package flags cover their nested modules automatically. New
top-level coverage sources also belong in `[tool.coverage.run] source`;
new test files are auto-discovered and need neither coverage declaration.

## Layout and special files

| Path | What it is |
|---|---|
| `conftest.py` | Shared config, retriever, and LLM fixtures. `test_config` is a **deepcopy** on purpose — a shallow copy leaks mutations across tests (`test_conftest_fixtures` guards this). |
| `fixtures/github_coding_repo/` | Canned repo used by the agentic real-repo-loop tests. |
| `ci_rag_smoke.py` | Deliberately NOT `test_*`-named so pytest ignores it; runs as a separate CI step against a real index. Renaming it double-runs it and drags ChromaDB into the unit lane. |
| `judge_eval.py` | Default-off 52-case groundedness evaluator. Builds an isolated real Chroma/BM25 index; the opt-in judge is Claude or a second loopback model. See `docs/EVALS.md`. |
| `rerank_probes.py` | Answer keys for every answerable RAG probe, plus a fresh held-out probe set, for choosing the reranker veto (issue #1456). Labels a window by whether an answer key is in it, never by a model score. Read by `scripts/rerank_bakeoff.py` and `test_rerank_bakeoff.py`; no heavy imports. |
| `judge_calibrate.py` | Runs the selected judge over 36 labeled fixture answers without generating contestant answers; reports agreement, not a CI gate. |
| `TEST_SUITE_AUDIT.md`, `VERIFICATION_REPORT_3.12.md` | Point-in-time audit reports, kept beside the suite they audited. |
| `apipsTest.ps1`, `cmd2index.bat` | Windows-side manual helpers; not collected by pytest. |
| `nemo_runtime/` | NeMo-guardrails runtime tests plus their own harness (`network_jail.py`, `mock_openai.py`); collected with the main suite and skipped unless the runtime lane is enabled. |
| `executor_sandbox_double.py`, `spend_live_probe.py` | Helper doubles/probes, not `test_*`-named, so not collected. |

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
