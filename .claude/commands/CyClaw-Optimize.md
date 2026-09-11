---
description: Methodically scan the CyClaw main branch for code, CI, security, financial-risk, and maintainability optimization opportunities, then open a small set of focused, reviewable pull requests only when each chunk earns its keep (not a fixed PR quota).
---

Scan CyClaw's main branch for optimization opportunities and open focused
draft PRs where each one earns its keep. $ARGUMENTS

See `.claude/skills/CyClaw-Optimize/SKILL.md` for the full scan → dedup →
PR workflow.

## Notes

- Dedup against open PRs (`list_pull_requests`) before scanning or implementing.
- Each PR: one reviewable concern, draft, subscribed to its own activity events and driven to green.
- Never touch a security invariant (`CLAUDE.md` §3) without arguing the change explicitly and re-running `invariant-guard`.
