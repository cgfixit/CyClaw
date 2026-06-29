# `.codex/`

This folder holds Codex-specific operating material for CyClaw. Repo-wide instructions belong in `AGENTS.md`; reusable task playbooks, checklists, and prompt templates can live here.

## Purpose

Use `.codex/` to help future Codex agents start safely and consistently without copying large project docs. Keep material short, practical, and linked to canonical sources such as `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, and the CI workflows.

Existing `.codex/skills/` content is project-specific skill material. Do not rewrite it as part of routine onboarding unless the maintainer explicitly asks.

## Available Routines

- `routines/first-pass-repo-review.md` - orient in the repo before changing code.
- `routines/bugfix.md` - diagnose and fix a bug with targeted verification.
- `routines/feature.md` - implement a new feature without breaking CyClaw invariants.
- `routines/refactor.md` - improve structure while preserving behavior.
- `routines/test-and-verify.md` - choose and run verification commands.
- `routines/pr-review.md` - review a PR or diff with risk-first findings.
- `routines/security-review.md` - assess security-sensitive changes.

## Prompt Templates

- `prompts/issue-triage.md`
- `prompts/implementation-plan.md`
- `prompts/review-diff.md`
- `prompts/release-notes.md`

Copy these into a Codex prompt and fill in the placeholders. Each template references `AGENTS.md` so the agent starts from repo-specific guidance.

## Checklists

- `checklists/pre-commit.md`
- `checklists/pre-pr.md`
- `checklists/regression-risk.md`

Use checklists as lightweight reminders, not as a substitute for reading the relevant code and CI workflows.

## Adding New Routines

1. Put task-specific playbooks in `.codex/routines/`.
2. Keep repo-wide rules in `AGENTS.md` instead of duplicating them.
3. Link to canonical docs rather than copying long sections.
4. Include when to use it, inputs, workflow, verification, and final response expectations.
5. Keep routine names lower-case kebab-case.

## Scratch Work

Generated scratch work, logs, local notes, and temporary outputs should not be committed unless the maintainer explicitly requests them. Use ignored runtime locations or local scratch space for experiments, then summarize results in the final response.
