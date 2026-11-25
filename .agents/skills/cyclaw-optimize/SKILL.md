---
name: cyclaw-optimize
description: "Audit or implement a requested, bounded CyClaw improvement. Validate the problem and check open-PR overlap before changing code."
---

# Improve CyClaw

Establish audit or implementation scope and refresh main. Use `.codex/Codex_instructions.md` for overlap and publication. Trace actual callers and measure the problem before claiming an improvement. Old audits, file length and newer versions are leads.

For each candidate, identify the trigger, impact, smallest fix and a check that could disprove the claim. Select changes that serve the request and preserve I1–I6 and the current maintenance scope. Consolidate overlapping changes or stack real dependencies.

Run the affected behavior and relevant checks under `CLAUDE.md` section 5. Report validated findings for an audit. Publish only when authorized, using the repository template and exact-head evidence.

Use `$refactor` for structural cleanup, `$dep-guard` for pin contracts and `$verify-dep` for install acceptance.
