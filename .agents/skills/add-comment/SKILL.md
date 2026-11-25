---
name: add-comment
description: "Add WHY comments to requested CyClaw code. Use for verified non-obvious ordering, thresholds, workarounds or security gates. Preserve executable behavior."
---

# Add WHY Comments

Read callers and existing comments. Explain the reason in one or two sentences. Leave executable lines, generated data and the protected soul untouched.

Compare before/after Python ASTs where applicable. Run touched Ruff F/B/S and `git diff --check`. Check any security claim against the relevant invariant.
