---
description: Iterative logging coverage loop — reviews system logging, adds missing log statements until every important path produces useful tested logs, diagnoses low coverage or errors, makes a plan, then applies fixes until all tests exceed 85% pass rate (targeting 100%).
---

Run the logging refactor loop until logging coverage and test pass rate meet target. $ARGUMENTS

See `.claude/skills/logging-refactor/SKILL.md` for the full loop.

## Notes

- No `print()` in library code — `logging.getLogger("cyclaw.<module>")` with lazy `%s` formatting.
- Never log raw query text, API keys, or secrets — the audit log stores SHA-256 hashes only.
- Never weaken or delete a test to hit the pass-rate target.
- A loop, not a one-shot edit — keeps going until targets are met.
