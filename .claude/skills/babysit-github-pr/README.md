# `/babysit-github-pr` — PR lifecycle guidance

Explicit CI triage, review, base-update, and readiness workflow:
[SKILL.md](SKILL.md). CyClaw PRs stay draft for humans; invocation does not
authorize merges or history rewrites. Shell helpers are **legacy scaffolding**
with the limits below; use working GitHub tools to inspect exact-head checks
and reviews.

## Installation

The skill already lives in `.claude/skills/babysit-github-pr/`, with its command
wrapper in `.claude/commands/`. Invoke these in a Claude Code session, not a shell:

```text
/babysit-github-pr 42
/babysit-github-pr codex/my-fix
/babysit-github-pr https://github.com/cgfixit/CyClaw/pull/42
```

For another repository, copy the skill folder into its `.claude/skills/` or
into the operator's `~/.claude/skills/`, and reconcile its procedures with that
repository's branch, PR, verification, and authorization rules.

## Helper prerequisites and limits

Helpers need Bash, Git, authenticated `gh`, `jq`, and Python 3.12. Without
them, follow the procedure using runtime GitHub tools; do not reset auth
merely because a helper is unavailable.

The tracked implementation currently has these limits:

- `run-babysit.sh`, `pr-state.sh`, and `wait-for-checks.sh` pass `--repo .`;
  GitHub CLI expects `OWNER/REPO` or repository inference from the checkout.
  The check readers also request the unsupported JSON field `status` instead
  of `state`. Their swallowed command errors can look like absent checks.
- The exit condition checks only for failures. It does not independently prove
  that all expected jobs registered and reached successful terminal states.
  Do not treat its ready message as CI or merge-readiness evidence.
- Comment helpers use review/comment records rather than authoritative review
  thread resolution. The orchestrator only prints comments; it neither fixes,
  replies, nor resolves them. Cursor updates happen in a piped subshell and
  are lost, so comments can repeat.
- Code failures are reported and counted, not repaired. `BLAST_RADIUS_FILES`
  is declared but not enforced. Command detection uses Makefile, package.json,
  pyproject.toml, tox.ini, then workflow text; missing commands fall back to
  `pytest tests/ -q` and `ruff check --select F,B,S .` without prompting.
  In CyClaw, reproduce with the affected command or one relevant test file
  instead of accepting that full-suite fallback.
- The helper's new-PR path uses `gh pr create --fill`, which does not satisfy
  CyClaw's required PR body template. Create authorized drafts with
  [the repository template](../../../.github/PULL_REQUEST_TEMPLATE.md) and
  validate the body with `scripts/check-pr-template.sh` from the repo root.

Exercise repaired helpers before trusting unattended operation; no live watch
is established here.

## Helper configuration

Shell-helper environment defaults (not prefixes for slash commands):

| Variable | Default | Implemented use |
| --- | --- | --- |
| `DRAFT_BY_DEFAULT` | `true` | Adds `--draft` to the helper's incomplete PR-creation path. |
| `POLL_SECONDS` | `90` | Delay between check reads. |
| `FLAKY_RETRIES` | `2` | Retry cap for failures classified as flaky from log text; confirm run history yourself. |
| `MAX_FIX_ATTEMPTS` | `3` | Counter for reported code failures; the helper does not fix code. |
| `MAX_ITERATIONS` | `8` | Loop iteration limit, including the persisted count. |
| `BLAST_RADIUS_FILES` | `5` | Declared only; the agent must enforce the scope limit. |
| `AUTO_MERGE` | `false` | Enables a merge request in the helper; keep false in CyClaw, where a human merges. |
| `ALLOW_FORCE_WITH_LEASE` | `false` | Operator-owned gate before rebase/push; agents must not set the override themselves. |
| `TIMEOUT_MINUTES` | `45` | Timeout for each wait-for-checks call, not a whole-session deadline. |

Local `.git/babysit-state.json` stores cursor, retry counts, iteration, and
commands. Only the first three reload; commands are re-detected. Linked
worktrees are unsupported because `.git` is assumed to be a directory. Never
commit state; reset only to start a fresh watch.

## Verification

From the repository root:

```bash
bash .claude/skills/babysit-github-pr/verify.sh
```

This checks shell/Python syntax, the two Python helper self-checks, usage output,
and documentation presence. The advisory `verify-skills` matrix in `ci.yml`
runs it too. It does not exercise a live PR, check API compatibility, repair
comments, or prove that the watcher reaches a correct terminal state.

## Troubleshooting and handoff

Check the active GitHub host, account, and execution context when `gh` fails.
A network or restricted-shell failure does not prove that credentials are
invalid; do not automatically log out or reset them.

Stop on a rebase conflict and preserve the conflicting paths for review.
Rewriting a published branch requires explicit authorization, inspection of
concurrent changes, and an exact-head lease; do not copy an unqualified
force-push command from a generic example.

Report the exact head SHA, individual check states, review decision, unresolved
threads, draft state, and mergeability separately. Pending, missing, skipped,
or advisory checks are not substitutes for required successful checks.
