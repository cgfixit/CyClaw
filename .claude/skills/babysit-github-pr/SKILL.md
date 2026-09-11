---
name: babysit-github-pr
description: >
  Watch a GitHub PR end-to-end — rebase when behind, triage CI failures (flaky
  vs code), fix code issues, address review comments, drive to green or escalate
  to human. Triggers on: babysit, watch my PR, keep this PR green, fix CI,
  rebase and push, get this merged, why is CI failing, or any PR number + CI/checks/review.
---

# Babysit GitHub PR

**Persona:** You own a PR from "branch exists locally" through "merged or blocked on a human." You run a bounded, repeatable loop that syncs state, rebases if behind, waits for checks, triages failures (flaky vs code), addresses review comments, and exits only when the PR is green or stuck.

**Why this skill exists:** PR lifecycle automation is tedious and error-prone by hand. You spend tokens polling GitHub, reading logs, guessing whether a timeout is flaky or a real failure, and applying the same rebase/test/push cycle. This skill automates all six steps of that loop — it never asks "is this flaky?" or "should I rerun?" by guessing. It classifies failures by log content, retries intelligently, and tells you exactly why it stopped.

---

## The Loop

Each iteration:

1. **Sync state** → Fetch PR metadata, check status, count unresolved comments
2. **Rebase if behind** → `git fetch && git rebase origin/<base>`; handle conflicts (stop if auto-resolution fails)
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
- Count of unresolved review comments (threads + top-level, excluding `outdated`)

**Exit early if:** PR is merged/closed → report and stop.

### 2. Rebase if Behind

If `mergeStateStatus == BEHIND` or `DIRTY` (conflict):

```bash
git fetch origin
git rebase origin/<base>
```

**On conflict:**
- Try simple auto-resolution: for each file, if both sides added non-overlapping lines, merge them
- If auto-resolution fails (overlapping edits to same region), **stop and report conflict as blocker**
- User resolves manually, re-invokes skill

**Before pushing:**
- Check that no commits are from a different author (`git log --format=%aE` against your email)
- If mixed authors → **stop and report, don't rewrite history**

**On success:** Commit with message `ci: rebase onto origin/<base>` and push with `--force-with-lease` (never plain `--force`).

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

- **Flaky** (log contains: "timed out", "runner lost", "rate limited", "429", "cancelled" OR same test passed on earlier run in this PR)
  - Action: `gh run rerun <run-id> --failed`, max 2 retries per check
- **Code** (log contains: "AssertionError", "FAILED", "TypeError", lint errors, build failure)
  - Action: Reproduce locally (`<test_command>`), fix, commit with `ci: <check-name>` prefix, push
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
- If `AUTO_MERGE=true`: run `gh pr merge --squash --auto`; else report readiness

❌ **Give up:**
- Same check failed `MAX_FIX_ATTEMPTS=3` times after a code fix
- Iteration count reached `MAX_ITERATIONS=8`
- Merge conflict auto-resolution failed (user must resolve)
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
| `AUTO_MERGE` | `false` | Auto-merge when green + approved (else just report) |
| `TIMEOUT_MINUTES` | `45` | Max time to wait for checks to settle |

---

## Report Template

At exit, print (to stdout):

```
=== BABYSIT REPORT ===
PR: https://github.com/{owner}/{repo}/pull/{number}
Status: [green | red | timeout | conflict | exhausted | blocked]

Final Check State:
  - <check-name>: passing
  - <check-name>: failing (last seen <timestamp>)
  - <check-name>: not yet run

Commits Made (this session):
  - <sha> : <message> (authored by: <email>)
  - <sha> : <message> (authored by: <email>)

Unresolved Comments (deferred to author):
  - Line <N> in <file>: "..." (awaiting confirmation)

Stopped Because:
  - [reason for exit]

Next Steps:
  - [what the user should do]
```

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

The six invariants from `CLAUDE.md` §3 stay locked:
- **RAG-first** (CyClaw-specific): does not apply to this cross-project skill
- **Topology = policy** (CyClaw-specific): does not apply
- **Triple-gated external fallback** (CyClaw-specific): does not apply
- **Audit convergence** (CyClaw-specific): does not apply
- **Soul governance** (CyClaw-specific): does not apply
- **Module isolation** (CyClaw-specific): does not apply

**This skill's guardrails:**
- Never skip a failing test; fixing a real failure is the core job
- Never assume a timeout is flaky without external confirmation (check test history)
- Never rebase or force-push without confirming it won't touch co-authored commits
- Never auto-merge if human review is required (only if `AUTO_MERGE=true` AND approved)

---

## Gotchas

1. **Comment ID gaps** — If the skill crashes or is interrupted, re-run it immediately. The persisted `last_comment_id` in `.git/babysit-state.json` ensures idempotency. If you manually delete the state file, the skill will re-process all comments.

2. **Merge conflict resolution** — The skill attempts auto-resolution but stops if it fails. Do not expect it to resolve overlapping edits in the same file. Resolve manually and re-invoke.

3. **Author detection** — The skill checks `git log --format=%aE` against your configured `user.email`. If your email is misconfigured, the skill may skip a rebase thinking it's co-authored. Set git config before invoking.

4. **Flaky test history** — Classifying a failure as flaky requires checking the PR's full run history. If a test consistently fails, it's not flaky, even if it times out. The `classify-failure.py` script queries prior runs.

5. **Test command detection** — The skill asks you once (via `AskUserQuestion`) if it can't auto-detect. The answer is cached in `.git/babysit-state.json` forever, per-repo. To re-detect, delete the state file or manually set `detected_test_command`.

6. **Blast radius** — The skill tracks the original PR's file set and refuses to modify >5 additional files. If your fix requires broader changes, the skill stops and reports it. Consider splitting into multiple PRs.

7. **Terminal output** — The skill prints the final report to stdout. If running in a CI/automation context, redirect to a file or feed to another tool.

---

## Success Criteria

- ✅ PR rebase succeeds (no conflicts, or conflicts are auto-resolved)
- ✅ CI passes (all checks terminal and success)
- ✅ All review comments addressed (mechanical ones fixed, architectural ones deferred)
- ✅ Authorship respected (no commits from different authors rewritten)
- ✅ Report printed with full audit trail

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

# Syntax check
bash scripts/run-babysit.sh --help

# Dry run (see README.md)
```
