---
description: Iterative speed optimization loop — continuously optimizes code for performance, measures page-load across every page under repeatable test conditions after each change, and continues until every page and module loads or runs in under 50 ms.
---

Run the speed refactor loop until every page/module meets the latency target. $ARGUMENTS

See `.claude/skills/speed-refactor/SKILL.md` for the full loop.

## Notes

- Measure under repeatable conditions after every change — no unverified speed claims.
- Never trade away correctness or a security invariant for latency.
- A loop, not a one-shot edit — keeps going until every page/module is under target.
