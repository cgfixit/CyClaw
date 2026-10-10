# `scripts/` — repo development hygiene

Contributor-side tooling for this clone's git workflow, one operator
throughput probe, and measurement tools. Nothing here is imported by gate.py / graph.py / llm at
runtime.

## Scripts

| Script | What it does |
|---|---|
| `install-githooks.sh` | Points `core.hooksPath` at the repo-managed `.githooks/` (pre-commit: branch-naming allowlist; pre-push: branch naming + fresh `origin/main` ancestry; commit-msg: `[prefix] - subject` title convention). Run once per clone. |
| `ensure-githooks.sh` | Idempotent, never-fatal form of `install-githooks.sh` for agent setup: sets `core.hooksPath` to `.githooks` only when it is unset, leaves a deliberate value alone, honors `GITHOOKS_SKIP_INSTALL=1`. Run by the Claude Code SessionStart hook and Copilot setup steps; the line to paste into a Codex environment setup script. |
| `check-pr-template.sh` | Checks that a PR is a complete fill of `.github/PULL_REQUEST_TEMPLATE.md` before you open it: every body section, a ticked box under Types of changes and Checklist, a trial-merge note, `## ELI5` last, the `Last updated` stamp last, an invariant mention on core-path changes, and (with `--title` / `--branch`) the `[prefix] - Sentence` title and an allowed branch name. Git hooks cannot intercept `gh pr create` bodies, so run it by hand: `gh pr view N --json body -q .body \| scripts/check-pr-template.sh --title "..." --branch "..." -`. `.github/workflows/pr-template-check.yml` applies the same rules with the same `[key]` per failure as the blocking CI check, and `tests/test_pr_template_check_parity.py` keeps the two in step. Exit 0 = ok, 1 = rules failed, 2 = usage error. |
| `measure_local_llm_throughput.py` | Operator probe: hits loopback Ollama `POST /api/generate` and prints prefill/decode tok/s from the runner's own nanosecond counters. stdlib only. Not imported by gate/graph/llm. See `docs/! How-To-Guides/OLLAMA_SETUP.md`. |
| `cyclaw-eval-dogfood.py` | Opt-in local Qwen dogfood matrix (`CYCLAW_EVAL_DOGFOOD=1`). Isolated groundedness index + sanitizer probe; optional loopback generate(). Never required CI. See `tests/fixtures/groundedness/DOGFOOD.md`. |
| `rerank_bakeoff.py` | Issue #1456 reranker choice: builds the `data/corpus` and `data/corpus` + `docs/` indexes, scores every probe window that clears the cosine gate with five candidate cross-encoders (chunk and passage granularity), and applies a pre-registered rule: pick a model and threshold on the older probes, then judge it on `tests/rerank_probes.py`'s fresh ones. Needs the full install and Hugging Face access on a cold cache. Report only; not a CI gate. First run (PR #1464): no configuration passed; see `docs/audits/2026-09-26-reranker-bakeoff.md`. |
| `compare_vector_backends.py` | Issue #1255 Phase C spike tool: builds two isolated semantic indices from the same corpus + embeddings (real `retrieval.vector_store` Chroma writer vs. a prototype-only sqlite-vec writer), runs index-doctor's fixed probe set through both, and reports top-1/overlap agreement plus build/query wall-clock. Not wired into any CI job; `sqlite-vec` is test-only (`requirements-test.txt`), not a runtime dependency. See `docs/audits/2026-09-21-sqlite-vec-phase-c-spike.md`. |

## Related

- Branch-prefix allowlist source of truth: `utils/agent_identity.py`
- Branch and PR conventions: `CLAUDE.md` §5, `.github/PULL_REQUEST_TEMPLATE.md`
