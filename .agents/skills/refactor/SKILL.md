---
name: refactor
description: "Make a scoped, behavior-preserving CyClaw structural cleanup. Use for requested duplication removal, module-boundary simplification or a measured hot-path improvement; exclude speculative architecture rewrites."
---


# Refactor CyClaw

Read the affected callers and contracts; record the concrete problem and a
comparable baseline before editing. Use `.codex/Codex_instructions.md` for
authorized publication.

Prefer deletion or reuse over a new abstraction. Make one coherent cleanup,
preserving public APIs, typed errors, timeouts/retries, destination checks,
consent, audit and I6 bridge boundaries. Preserve both local generation paths
when extracting shared code. Reclassify any intentional behavior change.

Execute the baseline again, inspect adjacent callers and the final diff, and
run touched lint plus the invariant guard for core changes. Follow `CLAUDE.md`
section 5 for local/Actions test ownership; do not require a full local suite.
Use identical conditions for performance claims and report measured results.
Stop when the requested defect is gone; no iteration or PR quota is required.
