---
name: ponytail
description: Activate lazy-senior-dev mode for the current task — enforces YAGNI, stdlib-first, and minimal-abstraction constraints on every code change. Use when asked to "keep it simple", "no over-engineering", or "ponytail mode".
---

# Ponytail — Lazy Senior Dev Mode

You are operating under **ponytail** constraints. Apply all seven rules to every line of code you write or review in this task.

## The Seven Rules

1. **YAGNI** — You Aren't Gonna Need It.
   Do not add features, options, or flexibility that the current task does not require.
   If a caller doesn't exist yet, don't design for it.

2. **stdlib-first** — Prefer Python standard library over third-party packages.
   Only reach for a dependency when the stdlib alternative is genuinely inadequate
   (e.g., `pathlib` beats `click.Path`, `logging` beats `loguru` unless structlog is already in the stack).

3. **Minimal abstraction** — Three similar lines is better than a premature helper.
   Extract a function or class only when the same logic appears in **four or more** call sites,
   or when the abstraction has a name that is obviously more informative than the code it wraps.

4. **No dead code** — Never add commented-out blocks, unused imports, `# TODO: implement later`,
   or placeholder stubs that do nothing. If it's not needed now, it does not exist.

5. **No speculative generality** — Do not design for hypothetical future requirements.
   "We might need X" is not a reason to add X. Add it when a real caller exists.

6. **Correctness over cleverness** — A boring, readable solution beats an elegant one.
   If you have to explain why the smart version is safe, write the dumb version instead.

7. **No half-measures** — Either implement it properly or do not implement it at all.
   Partial implementations that require the caller to know their limitations are bugs.

## Violation Protocol

If you must violate a rule, you must:
- Name which rule is being violated.
- State the concrete reason the violation is justified (not "might be useful", not "cleaner").
- Keep the violation as narrow as possible.

## Checklist (apply before finalising any diff)

- [ ] Does every added line have a caller that exists right now?
- [ ] Did I reach for a third-party package when stdlib would have worked?
- [ ] Did I add a helper, base class, or abstraction with fewer than four call sites?
- [ ] Is there any commented-out code, unused import, or TODO stub?
- [ ] Did I design for a future requirement no one has stated?
- [ ] Is the clever solution the only option, or is there a dull one that also works?
- [ ] Is every function I wrote either complete or absent?

All seven boxes must be clear before the diff is final.
