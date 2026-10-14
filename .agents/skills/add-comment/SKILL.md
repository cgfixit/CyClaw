---
name: add-comment
description: "Add bounded WHY comments to requested CyClaw code without changing executable behavior. Use for non-obvious ordering, thresholds, workarounds or security gates; exclude repo-wide commentary and refactoring."
---


# Add WHY Comments

Read the requested module, callers and existing comments. Explain a verified
reason in one or two sentences; do not narrate the next line or add TODOs.
Keep protected soul, generated data and executable lines untouched.

Inspect the diff and compare before/after Python ASTs when proving a Python
change is comment-only. Run touched Ruff F/B/S and `git diff --check`; use the
invariant checker when a comment makes a security claim. A comment-only change
needs no unrelated runtime suite. Report unavailable checks and use the normal
publication boundary from `.codex/Codex_instructions.md`.
