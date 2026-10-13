---
description: >
  Clone origin/main to a clean local sandbox, install all dependencies, then
  run a comprehensive audit — LangGraph routing, the Ollama local-LLM path
  at three realism tiers, triple-gated Grok/Claude fallback, API key
  redaction, Phase 2 guardrails, due-diligence invariants, the full terminal
  console REST surface, and a Python-3.12 runtime gate. Produces a dated
  report.
---

Invoke the `CyClaw-Sandbox` skill and run the full sandbox audit: clone,
install, mock Ollama, audit every subsystem, report. $ARGUMENTS

See `.claude/skills/CyClaw-Sandbox/SKILL.md` for the full audit (its
Operator map + "Steps -- the full audit" section): realism ladder, config
validation, gate/graph standalone checks, the 5-query swarm test,
triple-gate + key redaction, due-diligence invariants, guardrails, the
full terminal-console REST + slash-command surface, the 3.12 runtime gate,
the Guardrails invariant table, and the sign-off report.

For a fast check against your current checkout with no clone or report —
use the skill's **Quick Mode** section instead (it absorbed the former separate
`/run-cyclaw` command; `/run` still ships as the thin Quick-Mode entry point):

```bash
bash .claude/skills/CyClaw-Sandbox/smoke.sh
```

## Notes

- A **destructive-safe, clone-first** audit — never modifies the real
  `data/personality/soul.md`, fully reproducible.
- Run the highest Ollama realism tier the environment supports (Tier 0
  stubs / Tier 1 mock-over-HTTP / Tier 2 real daemon) and record which tier
  was used — never claim Tier 2 realism from a Tier 0/1 run.
- This skill opens no PR (CLAUDE.md §9); it produces a dated sign-off report.
- `status: degraded` without live Ollama is expected and normal.
