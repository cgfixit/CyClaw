---
name: invariant-guard
description: "Check CyClaw I1–I6 after changes to routing, auth, audit, sanitizer, soul or import boundaries. Pair static and behavioral evidence."
---

# Check Invariants

Read `INVARIANTS.md` and the affected execution path. Run from the root:

```text
python .claude/skills/invariant-guard/check_invariants.py
```

Use the checker's actual core/out-of-band sets. I6 governs direct imports. Evaluate memory, in-process guardrail bridges and OS confinement under their own contracts.

Exercise the relevant allowed and refused paths under `CLAUDE.md` section 5. A static pass alone cannot establish endpoint, auth, telemetry or audit-sink behavior. Preserve protected state, policy and assertions during read-only review. For guard changes run `bash .claude/skills/invariant-guard/verify.sh` and report platform gaps.
