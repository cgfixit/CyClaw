---
name: babysit-github-pr
description: >
  Watch a GitHub PR end-to-end — rebase when behind, triage CI failures (flaky
  vs code), fix code issues, address review comments, drive to green or escalate
  to human. Not auto-invocable: it starts an extended watch loop against live
  GitHub state and pushes commits, so it only runs on explicit request —
  "babysit", "watch my PR", "keep this PR green", "fix CI", "rebase and push",
  "get this merged", "why is CI failing", or a PR number + CI/checks/review.
disable-model-invocation: true
---

# Babysit GitHub PR

**Persona:** You own a PR from "branch exists locally" through "merged or blocked on a human." You run a bounded, repeatable loop that syncs state, rebases if behind, waits for checks, triages failures (flaky vs code), addresses review comments, and exits only when the PR is green or stuck.

**Why this skill exists:** PR lifecycle automation is tedious and error-prone by hand. You spend tokens polling GitHub, reading logs, guessing whether a timeout is flaky or a real failure, and applying the same rebase/test/push cycle. This skill is the procedure for that loop: the scripts under `scripts/` snapshot state, wait for checks, and classify failures by log content; the fixing, replying, and resolving steps are yours to carry out and report.

**Where it runs:** the `scripts/` helpers need an operator shell with `gh`.
In a Claude Code cloud session the equivalent is the runtime's own
`subscribe_pr_activity` event flow plus the GitHub MCP tools (CLAUDE.md §4
"Git & PR"); use this file for the triage rules and exit conditions, not the
`gh` commands.

---

## The Loop

Each iteration:

1. **Sync state** → Fetch PR metadata, check status, count unresolved comments
2. **Rebase if behind** → with explicit force-with-lease authorization, `git fetch && git rebase origin/<base>`; stop on any conflict
3. **Wait for checks** → Poll until all checks are terminal or timeout (non-blocking script)
4. **Triage failures** → For each red check, classify as flaky (retry) / code (fix) / unknown (report)
5. **Address comments** → Process unresolved review comments; fix mechanical requests, defer architectural ones
6. **Exit conditions** → Check if done (green + approved) or stuck (retries/iterations exhausted, conflict, blast radius)

---

## Loop Steps — Detailed

### 1. Sync State

`gh pr view --json <fields>` + `gh pr checks --json` → one JSON snapshot.

**What we track:**
- PR number, head/base branch, mergeability, merge state, review decision, draft status, head SHA
- All checks and their statuses (success/failure/pending/skipped)
- Count of unresolved review comments (threads with no `resolved_at`)

**Exit early if:** PR is merged/closed → report and stop.

### 2. Rebase if Behind

If `mergeStateStatus == BEHIND` or `DIRTY` (conflict):

```bash
git fetch origin
git rebase origin/<base>
```

**On conflict:**
- Abort the rebase and **stop with the conflicting file list**. Choosing a side
  automatically can discard concurrent work.
- User resolves manually, re-invokes skill

**Before pushing:**
- Check that no commits are from a different author (`git log --format=%aE` against your email)
- If mixed authors → **stop and report, don't rewrite history**

**On success:** Push with `--force-with-lease` (never plain `--force`) only when
the user explicitly authorized it in this session. `ALLOW_FORCE_WITH_LEASE` is
the `.githooks` operator override; the operator sets it, never the agent
(CLAUDE.md §4 "Git & PR"). Without that authorization, stop and ask.

### 3. Wait for Checks

Run `scripts/wait-for-checks.sh` (non-blocking, sleeps outside the model loop).

Exits with:
- `0` = all checks passed
- `1` = at least one check failed
- `2` = timeout (after `TIMEOUT_MINUTES=45`)
- `3` = no checks configured

**Do not poll from inside the model loop** — the wait script handles all polling. This keeps token usage low.

### 4. Triage Failures

For each red check:

```bash
gh run view <run-id> --log-failed | python3 scripts/classify-failure.py
```

**Classification logic:**

- **Flaky** (log contains: "timed out", "runner lost", "rate limited", "429", "cancelled"). The script reads only the log you pipe in; confirming "same test passed on an earlier run of this PR" is your check, and a log that also carries an assertion is a code failure, whatever the timeout wording says
  - Action: `gh run rerun <run-id> --failed`, max 2 retries per check
- **Code** (log contains: "AssertionError", "FAILED", "TypeError", lint errors, build failure)
  - Action: Reproduce locally (`<test_command>`), fix, commit as `[fix] - <check-name>: <what changed>` (the tracked `commit-msg` hook refuses `ci:` subjects), push
- **Unknown** (no pattern match)
  - Action: Report in final report, move to next check

**Retry cap:** `MAX_FIX_ATTEMPTS=3` per check per PR. After 3 failures, give up and report.

### 5. Address Comments

Fetch unresolved comments newer than `last_comment_id` (from `.git/babysit-state.json`).

For each comment:

**Mechanical requests** (typo, rename, missing null check, add test, style):
- Fix the issue locally, test, commit, push
- Reply in the thread: `[babysit] Fixed in <commit-sha>: <brief description>`
- Mark thread resolved

**Architectural/subjective requests** (design question, API change, behavior change):
- Reply: `[babysit] This requires author confirmation. <your proposal>`
- Defer to final report (do not mark resolved)

**Always include committer SHA** in replies so reviewers can track the fix.

### 6. Exit Conditions

Stop the loop (and print final report) when ANY is true:

✅ **Success:**
- All checks passing
- No unresolved actionable comments
- `reviewDecision == APPROVED` (or `CHANGES_REQUESTED` but you've addressed all comments)
- Report readiness. In this repo a human merges (CLAUDE.md §5); `AUTO_MERGE` stays `false`

❌ **Give up:**
- Same check failed `MAX_FIX_ATTEMPTS=3` times after a code fix
- Iteration count reached `MAX_ITERATIONS=8`
- Merge conflict detected (user must resolve)
- Rebase would touch commits from another author
- Fix would edit >5 files outside the original PR diff (blast radius exceeded)

---

## Knobs (Configurable)

All knobs are set via environment variables or `.git/babysit-state.json`. Defaults:

| Knob | Default | Purpose |
|------|---------|---------|
| `DRAFT_BY_DEFAULT` | `true` | Create new PRs as draft (not ready for review) |
| `POLL_SECONDS` | `90` | Sleep between check status polls |
| `FLAKY_RETRIES` | `2` | Max reruns per flaky check |
| `MAX_FIX_ATTEMPTS` | `3` | Max fix attempts per code failure |
| `MAX_ITERATIONS` | `8` | Bounded loop; stop after this many full iterations |
| `BLAST_RADIUS_FILES` | `5` | Max additional files to modify outside original diff |
| `AUTO_MERGE` | `false` | Auto-merge when green + approved. Leave `false` in CyClaw: a human merges |
| `ALLOW_FORCE_WITH_LEASE` | `false` | Operator-set `.githooks` override permitting a behind-branch rebase and force-with-lease push; an agent never sets it |
| `TIMEOUT_MINUTES` | `45` | Max time to wait for checks to settle |

---

## Report

At exit, report the PR, its status (green / red / timeout / conflict /
exhausted / blocked), the final state of every check, the commits you made
with their authors, the comments deferred to the author, why you stopped, and
what the user should do next. `run-babysit.sh`'s `print_report` prints a
shorter subset; fill in the rest by hand.

---

## Never

- ❌ Never `git push --force` (only `--force-with-lease`)
- ❌ Never `git reset --hard` on a branch with unpushed work
- ❌ Never `git checkout .` without first stashing to a named stash
- ❌ Never edit a test to make it pass (tests are oracles)
- ❌ Never rewrite history that includes another author's commits
- ❌ Never merge without `reviewDecision == APPROVED` and branch protection satisfied
- ❌ Never suppress a lint rule or add `# noqa` to fix CI
- ❌ Never process a comment twice (idempotency via persisted last ID)
- ❌ Never post secrets or full log dumps in PR comments

---

## Guardrails

This is a cross-project PR skill; CyClaw's six invariants (`CLAUDE.md` §3)
are not touched by it, and a CI fix that would touch one goes through
`invariant-guard` like any other change.

**This skill's guardrails:**
- Never skip a failing test; fixing a real failure is the core job
- Never assume a timeout is flaky without external confirmation (check test history)
- Never rebase or force-push without explicit user authorization and confirmation it won't touch co-authored commits
- Never merge; PRs stay draft until a human decides
- A new PR body must follow `.github/PULL_REQUEST_TEMPLATE.md` (the blocking `pr-template-check.yml` wants all eight headings, `## ELI5` last, and the `Last updated:` stamp); `gh pr create --fill` does not produce that

---

## Gotchas

1. **Comment ID gaps** — If the skill crashes or is interrupted, re-run it immediately. The persisted `last_comment_id` in `.git/babysit-state.json` ensures idempotency. If you manually delete the state file, the skill will re-process all comments.

2. **Merge conflict resolution** — The skill aborts and stops on every conflict.
   Resolve manually and re-invoke; it never chooses `ours` or `theirs` for you.

3. **Author detection** — The skill checks `git log --format=%aE` against your configured `user.email`. If your email is misconfigured, the skill may skip a rebase thinking it's co-authored. Set git config before invoking.

4. **Flaky test history** — Classifying a failure as flaky requires checking the PR's full run history. If a test consistently fails, it's not flaky, even if it times out. `classify-failure.py` reads only the log on stdin and makes no API calls; the history check is yours.

5. **Test command detection** — `detect-test-command.py` reads the repo's manifests and falls back to `pytest tests/ -q` without prompting. In CyClaw that default is the full suite, which CLAUDE.md §5 reserves for CI; reproduce a red check with the one test file it names instead.

5a. **Helper-script gaps (2026-10-13)** — the `scripts/` helpers call `gh pr checks --json name,status` (current `gh` rejects `status`; the field is `state`) and pass `--repo .` (not a valid `OWNER/REPO`), so `wait-for-checks.sh` reports "no checks configured" and `run-babysit.sh` cannot find the PR. Comment handling, the comment-ID cursor, and the blast-radius knob are described here but not implemented in `run-babysit.sh`. Treat the scripts as scaffolding until those are fixed; the loop above is the contract.

6. **Blast radius** — The skill tracks the original PR's file set and refuses to modify >5 additional files. If your fix requires broader changes, the skill stops and reports it. Consider splitting into multiple PRs.

7. **Terminal output** — The skill prints the final report to stdout. If running in a CI/automation context, redirect to a file or feed to another tool.

---

## Run

```bash
# Invoke by PR number (most common)
/babysit-github-pr 123

# Invoke by branch name (infers PR from branch)
/babysit-github-pr feature/my-fix

# Invoke by PR URL (extracts number)
/babysit-github-pr https://github.com/cgfixit/cyclaw/pull/123

# Set knobs via environment
DRAFT_BY_DEFAULT=false TIMEOUT_MINUTES=60 /babysit-github-pr 123

# View state (for debugging)
cat .git/babysit-state.json | jq .
```

---

## Verification

Unit tests and integration dry-run:

```bash
# Unit tests
python3 -m pytest scripts/tests/ -v

# Syntax check (no args prints usage; `--help` is parsed as a branch name)
bash -n scripts/run-babysit.sh && bash scripts/run-babysit.sh

# Dry run (see README.md)
```
