---
description: Iterative test coverage and quality loop — adds tests under tests/ until coverage reaches 100%, diagnoses and fixes failing tests, and continues until all test results exceed 85% pass rate (targeting 100%). Use when asked to improve test coverage, fix failing tests, or get the test suite green.
---

Run the tests refactor loop until coverage and pass rate meet target. $ARGUMENTS

See `.claude/skills/tests-refactor/SKILL.md` for the full loop.

## Notes

- Use `tests/conftest.py` fixtures; start no live service.
- Assert behavior/contract, not incidental implementation detail.
- Never weaken or delete a failing assertion to make the suite "pass" — fix the source or the test.
- A loop, not a one-shot edit — keeps going until targets are met.
