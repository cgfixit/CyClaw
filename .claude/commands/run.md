---
description: Run the CyClaw Quick Mode smoke (smoke.sh) against your current checkout in place. Starts its own server, runs sections A-G with the full pytest section skipped, and reports pass/fail with endpoint details.
---

Run the CyClaw smoke test against the local server. $ARGUMENTS

This is **Quick Mode** of the `CyClaw-Sandbox` skill: a fast in-place check
of your current checkout. For the fuller local audit (checkers, ruff, every
selftest, the swarm, the full route contract, in scratch copies), use
`/CyClaw-Sandbox` instead. Neither opens a PR.

## Steps

1. Check `data/personality/soul.md` exists (it self-heals at boot if not).
   `smoke.sh` builds the index itself when `index/bm25.json` is missing; in
   the cloud sandbox export `HF_HUB_DISABLE_XET=1` first or that download
   hangs.
2. Execute the smoke script with the CyClaw 3.12 venv's interpreter:
   ```bash
   SMOKE_SKIP_PYTEST=1 PYTHON=<venv>/bin/python bash .claude/skills/CyClaw-Sandbox/smoke.sh
   ```
   `SMOKE_SKIP_PYTEST=1` skips section F (the full suite), which GitHub
   Actions runs on every PR (CLAUDE.md §5). Leave it unset only when the
   user asks for the suite.
3. Report results for sections A-G (core API, `agentic/fsconnect`, NeMo
   guardrails, opt-in PostgreSQL backends, pytest, summary; there is no C
   since `agentic/sqlconnect` was removed on 2026-10-18). The script prints
   its own totals and writes them to `.claude/sandbox-test.txt`; see
   SKILL.md's **Quick Mode** section for what it does and does not cover.
4. Exit summary:
   - ✅ All checks passed: server is healthy
   - ❌ N checks failed: list each failure with the actual vs expected response

## Notes

- `status: degraded` in `/health` is **normal** without a live Ollama
  daemon running. `index_ready` and `graph_ready` are the meaningful fields.
- `needs_confirm: true` on `/query` is **correct** when retrieval misses the
  vault-hit gate (`retrieval.min_semantic_score` on the best cosine hit).
- `TELEMETRY KILL` messages on stdout are intentional.
- `GROK_API_KEY=dummy` is sufficient for all offline smoke checks.
- `soul.md` is backed up and restored by the smoke script, but its server
  appends to your `logs/` (it runs in place, on :8787).
