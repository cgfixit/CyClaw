---
name: cyclaw-optimize
description: "Audit or implement explicitly requested CyClaw improvements from current evidence and open-PR overlap. Use for a bounded optimization pass; no autonomous feature expansion, dependency bump or publication."
---


# Improve CyClaw

1. Establish audit versus implementation scope. Inspect the checkout, record
   base/head and fetch current main; follow `.codex/Codex_instructions.md`.
2. Read actual code/callers and measure the stated problem. File size, a newer
   dependency, old accepted-risk notes or a feature name is not a finding.
3. Inspect open PRs touching the same files before duplicating work. Validate
   each finding's trigger, impact, smallest fix and falsifying check.
4. Select only improvements that serve the requested outcome. Preserve the
   maintenance posture and I1–I6; do not resurrect removed console/broker code.
5. Implement within authorization. Consolidate related shared-file changes or
   stack real dependencies; trial-merge related candidates where needed.
6. Execute the changed behavior and relevant guards/lint. Follow `CLAUDE.md`
   section 5: broad suites/coverage/platform gates belong to Actions; use one
   focused local test file for a concrete uncovered risk.
7. Return validated findings for an audit. For authorized publication, use the
   full PR template and report the actual remote head and CI state.

Use `$refactor` for behavior-preserving structure, `$dep-guard` for static
dependency contracts and `$verify-dep` for selected install-profile acceptance.
Use `utils/agent_identity.py` as a contract reference, not as a reason to
impersonate CyClaw's own runtime identity. Do not merge or rewrite history
without the applicable authorization.
