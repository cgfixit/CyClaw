---
description: >
  Verify a CyClaw checkout locally: one command (local_audit.py) runs the
  stdlib checkers, ruff, every CLI and subsystem selftest, the in-process
  LangGraph swarm, and a live gate.py probed against the CLAUDE.md route
  contract, all in scratch copies that leave your working tree untouched.
  Opt-in steps cover auth, memory, a real Ollama, MCP and the agentic
  sandbox. pytest and coverage stay with GitHub Actions. Produces a report.
---

Invoke the `CyClaw-Sandbox` skill and run the local audit (Ladder L), then
whichever opt-in steps the user asks for. $ARGUMENTS

See `.claude/skills/CyClaw-Sandbox/SKILL.md`: the Operator map says which
ladder proves what and which ones GitHub Actions owns; "Steps -- the full
local audit" is the procedure.

```bash
<venv>/bin/python .claude/skills/CyClaw-Sandbox/local_audit.py              # all stages
<venv>/bin/python .claude/skills/CyClaw-Sandbox/local_audit.py --mock-ollama # Tier 1 local LLM
```

`<venv>` is the CyClaw Python 3.12 venv (`/root/.venv-cyclaw-312` in the
cloud sandbox, built by `bash .claude/skills/cyclaw-gotchas/driver.sh venv`).

## Notes

- Local-first: run the code, then lint and the checkers. Do not run
  `pytest tests/` or a `--cov` run; read the PR's CI result instead
  (CLAUDE.md §5). Reproduce a CI job only when it is red.
- Never writes the checkout: the swarm and live gate run in scratch copies,
  so `soul.md`, `logs/` and `index/` are untouched.
- Record which local-LLM realism tier was live (0 none, 1 `mock_ollama.py`,
  2 real daemon); never claim Tier 2 from a Tier 0/1 run.
- In the cloud sandbox export `HF_HUB_DISABLE_XET=1` before building the
  index or the first `/query`, or the model download hangs (SKILL.md Gotchas).
- This skill opens no PR (CLAUDE.md §9); it produces a report.
- `status: degraded` without a live Ollama is expected and normal.
