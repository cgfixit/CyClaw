---
description: >-
  Check that CyClaw secrets stay out of dotenv files, gitignored or not:
  no runtime dotenv loading, no secret names in tracked env files,
  .gitignore coverage, a sandboxed run of macos/setup-cyclaw-keys.sh that
  must write no secret into a dotenv file or rc hook, and line checks on
  scripts and docs, with a baseline ratchet for by-design findings on main.
---

Invoke the `dotenv-guard` skill for the given task. $ARGUMENTS

See `.claude/skills/dotenv-guard/SKILL.md` for full detail.

## Notes

- Stdlib Python, git, and bash only; runs in a fresh clone before any install.
- A stale baseline entry fails: delete it in the PR that fixes the violation.
