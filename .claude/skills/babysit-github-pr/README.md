# `/babysit-github-pr` — PR Lifecycle Automation

Automate the tedious parts of PR management: rebasing, CI triage, review comments, and merge readiness. Once invoked, the skill runs a bounded loop that drives the PR to green or escalates to a human.

## Installation

### Project-Local (`.claude/skills/`)

Already installed in CyClaw. For other repos:

```bash
# Copy the skill into your repo's .claude/skills/ directory
mkdir -p .claude/skills
cp -r ~/.claude/skills/babysit-github-pr .claude/skills/
```

Then invoke with `/babysit-github-pr <pr-number>` from within Claude Code.

### User-Wide (`~/.claude/skills/`)

```bash
# Copy to your home directory's skills folder (once per machine)
mkdir -p ~/.claude/skills
cp -r /path/to/babysit-github-pr ~/.claude/skills/
```

Then invoke `/babysit-github-pr` from any repo.

## Prerequisites

Before using this skill, ensure:

1. **`gh` CLI** (GitHub CLI) — authenticated with `repo` scope
   ```bash
   gh auth login
   gh auth status  # Verify you see "✓ Token: ghu_..." and "✓ Scopes: repo, gist"
   ```

2. **`jq`** — JSON query tool (for parsing GitHub API responses)
   ```bash
   # macOS
   brew install jq
   
   # Linux (Ubuntu/Debian)
   sudo apt-get install jq
   
   # Windows (choco or scoop)
   choco install jq  # or: scoop install jq
   ```

3. **`python3`** (3.8+) — for failure classification and command detection

4. **`git`** — version control (already assumed)

5. **Project's test/lint commands discoverable** from one of:
   - `Makefile` (targets: `test`, `lint`)
   - `package.json` (scripts: `test`, `lint`)
   - `pyproject.toml` (pytest/tox config)
   - `tox.ini` (envs)
   - `.github/workflows/*.yml` (run: steps)

   If none found, the skill will ask you once (first invocation).

## Knobs & Configuration

All knobs are environment variables. Set them before invoking the skill:

```bash
TIMEOUT_MINUTES=60 AUTO_MERGE=true /babysit-github-pr 123
```

| Knob | Default | Type | Purpose |
|------|---------|------|---------|
| `DRAFT_BY_DEFAULT` | `true` | bool | Create new PRs as draft (not auto-reviewed) |
| `POLL_SECONDS` | `90` | int | Seconds between check status polls |
| `FLAKY_RETRIES` | `2` | int | Max reruns per flaky check |
| `MAX_FIX_ATTEMPTS` | `3` | int | Max fix attempts per check failure |
| `MAX_ITERATIONS` | `8` | int | Bounded loop; stop after N full iterations |
| `BLAST_RADIUS_FILES` | `5` | int | Max additional files to modify (beyond original PR diff) |
| `AUTO_MERGE` | `false` | bool | Merge automatically when green + approved |
| `TIMEOUT_MINUTES` | `45` | int | Max time waiting for checks to settle |

### State File (`.git/babysit-state.json`)

The skill persists state per-repo in `.git/babysit-state.json` (not committed). It tracks:

```json
{
  "last_comment_id": 1234567890,
  "retry_counts": { "pytest": 1, "ruff": 0 },
  "iteration": 2,
  "detected_test_command": "pytest tests/ -q --cov",
  "detected_lint_command": "ruff check --select F,B,S ."
}
```

**Idempotency:** Comments are processed by ID, so re-invoking the skill won't double-process them.

**Resetting:** Delete `.git/babysit-state.json` to start fresh (re-detect test command, re-process all comments).

---

## What It Will NEVER Do

1. **Force-push carelessly** — always uses `--force-with-lease`, never plain `--force`
2. **Rewrite history with co-authors** — stops if commits are from another author
3. **Edit tests to make them pass** — tests are oracles; failures are real
4. **Suppress lint or add `# noqa`** — ignores the linter instead of fixing
5. **Process a comment twice** — persists comment ID for idempotency

---

## Quick Start

```bash
# Babysit a PR by number
/babysit-github-pr 42

# Babysit by branch name (infers PR from branch)
/babysit-github-pr feature/my-feature

# Babysit by PR URL (extracts number)
/babysit-github-pr https://github.com/cgfixit/cyclaw/pull/42

# Set custom knobs
TIMEOUT_MINUTES=120 AUTO_MERGE=true /babysit-github-pr 42
```

## Dry Run (Testing)

To test the skill without affecting a real PR:

1. Create a throwaway GitHub repo (e.g., `test-babysit`)
2. Clone it locally
3. Create a branch with a deliberate lint failure:
   ```bash
   git checkout -b feature/test-lint-fail
   echo "import unused" >> test.py
   git add test.py && git commit -m "wip: add lint error"
   git push -u origin feature/test-lint-fail
   ```
4. Invoke the skill:
   ```bash
   /babysit-github-pr feature/test-lint-fail
   ```
5. Watch it:
   - Create a draft PR
   - Wait for CI to detect the lint error
   - Fix the error, commit, and push
   - CI re-runs and passes
   - Report shows PR is ready to merge
6. Close the PR and clean up:
   ```bash
   git push origin --delete feature/test-lint-fail
   ```

## Troubleshooting

### `gh` not found
Install GitHub CLI: https://cli.github.com/

### `gh auth status` shows expired token
Re-authenticate:
```bash
gh auth logout
gh auth login
```

### Skill can't detect test command
The skill will ask you once. Provide the exact command used to run tests in your project (e.g., `pytest tests/ -v` or `npm test`).

### Merge conflict not auto-resolved
The skill only auto-resolves simple conflicts (non-overlapping additions). For overlapping edits:
```bash
# Resolve manually
git merge --abort
git rebase origin/main  # or your base branch
# Fix conflicts in your editor
git add .
git rebase --continue
git push --force-with-lease
```
Then re-invoke `/babysit-github-pr`.

### PR stuck on "awaiting human review"
If the skill stops with "awaiting human review," check:
1. Are all checks passing? (`gh pr checks`)
2. Is the PR approved? (`gh pr view --json reviewDecision`)
3. Are there unresolved comments? (`gh pr view --json comments`)

Address the blocker, then re-invoke.

---

## For Repository Owners

This skill works on any GitHub repository with:
- Automated checks (GitHub Actions, GitLab CI, etc.)
- A detectable test/lint command (Makefile, package.json, pyproject.toml, or workflows)
- Branch protection rules (optional but recommended)

No configuration in the repo itself is needed — the skill auto-detects everything.

---

## See Also

- `SKILL.md` — Full loop description, Never list, exit conditions
- `.github/PULL_REQUEST_TEMPLATE.md` — PR body template (if present)
- `verify.sh` — stdlib self-check; run in CI by the per-skill verify matrix in `.github/workflows/ci.yml`
- `scripts/` — `classify-failure.py`, `detect-test-command.py`, and the shell helpers the loop shells out to (`scripts/tests/` covers the two Python ones)

