---
description: Iterative architecture refactor loop — refactors code, live-tests after each significant step, runs autoreview, commits, and tracks progress in /tmp/refactor-{projectname}.md.
---

Run the architecture refactor loop until structure is clean and coherent. $ARGUMENTS

See `.claude/skills/architecture-refactor/SKILL.md` for the full loop
(Assess → Plan → Execute → Live-test → Autoreview → Invariant check →
Commit → Update tracker).

## Notes

- Never refactor across the six invariants (`CLAUDE.md` §3) without arguing
  the change explicitly and re-running `invariant-guard`.
- Never touch `soul.md`/`apply_evolution` without a non-empty `reason` string (I5).
- Never weaken or delete a test to make a refactor step "pass."
- A loop, not a one-shot edit — keeps going until the codebase is clean.
