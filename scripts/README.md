# `scripts/` — repo development hygiene

Contributor-side tooling for this clone's git workflow, the hashed-lock
refresh and check tools, CI checks, one operator throughput probe, and
measurement tools. Nothing here is imported by gate.py / graph.py / llm at
runtime.

## Scripts

| Script | What it does |
|---|---|
| `install-githooks.sh` | Sets `core.hooksPath` to `.githooks/`, replacing any existing value, and restores hook executable bits. The hooks check branch/title conventions, fresh `origin/main` ancestry, and the shared content/privacy/protected-control security gate. Use `ensure-githooks.sh` for routine setup; see [the hook guide](../.githooks/README.md). |
| `ensure-githooks.sh` | Idempotent, never-fatal form of `install-githooks.sh` for agent setup: sets `core.hooksPath` to `.githooks` only when it is unset, leaves a deliberate value alone, honors `GITHOOKS_SKIP_INSTALL=1`. Run by the Claude Code SessionStart hook and Copilot setup steps; the line to paste into a Codex environment setup script. |
| `check-pr-template.sh` | Checks that a PR is a complete fill of `.github/PULL_REQUEST_TEMPLATE.md` before you open it: every body section, a ticked box under Types of changes and Checklist, a trial-merge note, `## ELI5` last, the `Last updated` stamp last, an invariant mention on core-path changes, and (with `--title` / `--branch`) the `[prefix] - Sentence` title and an allowed branch name. Git hooks cannot intercept `gh pr create` bodies, so run it by hand: `gh pr view N --json body -q .body \| scripts/check-pr-template.sh --title "..." --branch "..." -`. `.github/workflows/pr-template-check.yml` applies the same rules with the same `[key]` per failure as the blocking CI check, and `tests/test_pr_template_check_parity.py` keeps the two in step. Exit 0 = ok, 1 = rules failed, 2 = usage error. |
| `measure_local_llm_throughput.py` | Operator probe: calls Ollama `POST /api/generate` and prints prefill/decode tok/s from the runner's nanosecond counters. Defaults to loopback; `--host` accepts an HTTP(S) URL without enforcing loopback or the gateway's trusted-host policy. Uses fixed synthetic prompts and does not set `num_ctx`. stdlib only; see `docs/! How-To-Guides/OLLAMA_SETUP.md`. |
| `cyclaw-eval-dogfood.py` | Opt-in local Qwen dogfood matrix (`CYCLAW_EVAL_DOGFOOD=1`). Isolated groundedness index + sanitizer probe; optional loopback generate(). Never required CI. See `tests/fixtures/groundedness/DOGFOOD.md`. |
| `rerank_bakeoff.py` | Issue #1456 reranker choice: builds the `data/corpus` and `data/corpus` + `docs/` indexes, scores every probe window that clears the cosine gate with five candidate cross-encoders (chunk and passage granularity), and applies a pre-registered rule: pick a model and threshold on the older probes, then judge it on `tests/rerank_probes.py`'s fresh ones. Needs the full install and Hugging Face access on a cold cache. Report only; not a CI gate. First run (PR #1464): no configuration passed; see `docs/audits/2026-09-26-reranker-bakeoff.md`. |
| `check_lock_contract.py` | Offline freshness check for the hashed locks (#1526): fails when a lock's inputs, pins, hashes or output set no longer match `pyproject.toml`, `constraints.txt` and `scripts/ci-lock-inputs/`; `--wheel dist/*.whl` also checks the built wheel's metadata. It does not claim a fresh resolve would pick the same versions. Run by `ci.yml`. |
| `check_codex_skills.py` | Checks `.agents/skills/` manifests, UI/invocation metadata, relative references, Python syntax, and agreement with `.codex/README.md`. Needs PyYAML; accepts `--repo-root` for a disposable fixture. `codex-skills.yml` runs it and checks shell syntax separately. It does not invoke skills or prove their runtime behavior. |
| `refresh-runtime-lock.sh` | Regenerates the runtime and torch locks (`locks/requirements-lock-*.txt`, `locks/requirements-torch-lock-*.txt`) with `uv pip compile`, seeded from the tracked locks so unchanged transitive pins stay put. Runs only on an arm64 macOS host. |
| `refresh-ci-locks.sh` | Same approach for the CI tool and extra install sets compiled from `scripts/ci-lock-inputs/*.txt` (ruff, bandit, numbat, the Postgres extras, …), so those jobs install with `--require-hashes`. Leaves the runtime and torch locks to `refresh-runtime-lock.sh`. arm64 macOS only. |
| `compare_vector_backends.py` | Issue #1255 Phase C spike tool: builds two isolated semantic indices from the same corpus + embeddings (real `retrieval.vector_store` Chroma writer vs. a prototype-only sqlite-vec writer), runs index-doctor's fixed probe set through both, and reports top-1/overlap agreement plus build/query wall-clock. Not wired into any CI job; `sqlite-vec` is test-only (`requirements-test.txt`), not a runtime dependency. See `docs/audits/2026-09-21-sqlite-vec-phase-c-spike.md`. |

Run helpers from the repository root using the prepared Python 3.12 environment.
Lock refreshes write dependency artifacts; probes and bakeoffs may load models,
build indexes, or call the configured local runner. Choose the helper needed
for the task instead of running this directory as a blanket check.

## Related

- Branch-prefix allowlist source of truth: `utils/agent_identity.py`
- Branch and PR conventions: `CLAUDE.md` §5, `.github/PULL_REQUEST_TEMPLATE.md`
