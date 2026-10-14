---
name: invariant-guard
description: "Check CyClaw I1\u2013I6 and related static guards after core routing, auth, audit, sanitizer, soul or import-boundary changes. Pair structural evidence with relevant behavior; never relax the checker to pass."
---


# Check Invariants

Read the affected flow, `INVARIANTS.md` and the maintained checker's actual
core/out-of-band sets. Run from the root:

```text
python .claude/skills/invariant-guard/check_invariants.py
```

Preserve retrieval entry, graph routing, external consent gates, audit
convergence, governed soul apply and direct import isolation. The six core
modules and five forbidden packages are defined in the checker; memory and
in-process guardrail bridges have their own contracts. I6 is not an OS sandbox.

Exercise the changed allowed/refused path separately; a static pass cannot
prove all endpoint, auth, telemetry or audit-sink behavior. Follow `CLAUDE.md`
section 5 for direct/local/Actions evidence instead of expanding local suites.

Run `bash .claude/skills/invariant-guard/verify.sh` when modifying or validating
the guard itself. Report unavailable Bash/native checks explicitly. Do not
mutate soul, graph/config policy or assertions during a read-only guard run.
