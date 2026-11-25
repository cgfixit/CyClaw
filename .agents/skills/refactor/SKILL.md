---
name: refactor
description: "Simplify CyClaw structure while preserving behavior. Use for demonstrated duplication, module friction or measured hot-path cost."
---

# Refactor CyClaw

Read callers and contracts. Establish a comparable baseline. Prefer deletion or reuse. Preserve APIs, typed errors, retries/timeouts, destination and consent gates, audit and I6 bridges. Check both local answer paths when sharing code. Reclassify deliberate behavior changes.

Repeat the baseline probe under equivalent conditions, exercise adjacent callers and inspect the final diff. Run touched lint and the invariant guard for core changes. Use `CLAUDE.md` section 5 for verification and `.codex/Codex_instructions.md` for authorized publication.
