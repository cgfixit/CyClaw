# `scripts/` — repo development hygiene

Contributor-side tooling for this clone's git workflow, one operator
throughput probe, and measurement tools. Nothing here is imported by gate.py / graph.py / llm at
runtime.

## Scripts

| Script | What it does |
|---|---|
| `install-githooks.sh` | Points `core.hooksPath` at the repo-managed `.githooks/` (pre-commit: branch-naming allowlist; pre-push: branch naming + fresh `origin/main` ancestry; commit-msg: `[prefix] - subject` title convention). Run once per clone. |
| `check-pr-template.sh` | Validates a PR body against `.github/PULL_REQUEST_TEMPLATE.md`'s required sections before you open the PR. Git hooks cannot intercept `gh pr create` bodies, so run this by hand (`gh pr view --json body -q .body \| scripts/check-pr-template.sh -`); CI runs the same headers as a blocking check via `.github/workflows/pr-template-check.yml`. Exit 0 = ok, 1 = missing sections, 2 = usage error (no input argument / `CYCLAW_PR_BODY_FILE` unset, or the named file does not exist). |
| `measure_local_llm_throughput.py` | Operator probe: hits loopback Ollama `POST /api/generate` and prints prefill/decode tok/s from the runner's own nanosecond counters. stdlib only. Not imported by gate/graph/llm. See `docs/! How-To-Guides/OLLAMA_SETUP.md`. |
| `cyclaw-eval-dogfood.py` | Opt-in local Qwen dogfood matrix (`CYCLAW_EVAL_DOGFOOD=1`). Isolated groundedness index + sanitizer probe; optional loopback generate(). Never required CI. See `tests/fixtures/groundedness/DOGFOOD.md`. |
| `rerank_bakeoff.py` | Issue #1456 reranker choice: builds the `data/corpus` and `data/corpus` + `docs/` indexes, scores every probe window that clears the cosine gate with five candidate cross-encoders (chunk and passage granularity), and applies a pre-registered rule: pick a model and threshold on the older probes, then judge it on `tests/rerank_probes.py`'s fresh ones. Needs the full install and Hugging Face access on a cold cache. Report only; not a CI gate. |
| `compare_vector_backends.py` | Issue #1255 Phase C spike tool: builds two isolated semantic indices from the same corpus + embeddings (real `retrieval.vector_store` Chroma writer vs. a prototype-only sqlite-vec writer), runs index-doctor's fixed probe set through both, and reports top-1/overlap agreement plus build/query wall-clock. Not wired into any CI job; `sqlite-vec` is test-only (`requirements-test.txt`), not a runtime dependency. See `docs/audits/2026-09-21-sqlite-vec-phase-c-spike.md`. |

## Related

- Branch-prefix allowlist source of truth: `utils/agent_identity.py`
- Branch and PR conventions: `CLAUDE.md` §5, `.github/PULL_REQUEST_TEMPLATE.md`
