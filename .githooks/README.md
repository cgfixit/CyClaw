# Git hooks (branch naming, title prefix, fresh main, security gate)

Enforces **documented multi-vendor feature-branch prefixes** on commit and push,
**PR-template commit title prefixes** on every commit subject, plus
fresh-`origin/main` ancestry for feature-branch pushes.

Canonical list (must stay aligned with `utils.agent_identity.ALLOWED_BRANCH_PREFIXES`,
`CLAUDE.md` §10 "Branch namespaces", and `.github/PULL_REQUEST_TEMPLATE.md`):

| Prefix | Driver |
|--------|--------|
| `grok/<feature>` | Grok Build |
| `claude/<feature>` | Claude Code / agentic harness |
| `codex/<feature>` | Codex |
| `kimi/<feature>` | Kimi / Kimi Code |
| `agent/<feature>` | Generic / default agent identity |
| `CyClaw/<feature>-…` / `cyclaw/…` | CyClaw direct / MCP |

Also allowed: `main`, `master`, `develop`, `dependabot/*`, `renovate/*`, `release/*`, `hotfix/*`.

| Hook | When | Behavior |
|------|------|----------|
| `pre-commit` | every commit | refuses commit if current branch is off-convention |
| `commit-msg` | every commit | refuses subjects that are not `[prefix] - description` per the PR template Title section |
| `pre-push` | every push | fetches `origin/main`, refuses off-convention head refs, and refuses non-default branches that do not contain current `origin/main` |

The `commit-msg` hook's allowlist is a closed set — `invariant`, `governance`,
`fsconnect`, `agentic`, `rag`, `harness`, `security`, `docs`, `infra`, `fix`,
`feat`. It also lets through Dependabot/Renovate subjects beginning `chore(deps)`, `build(deps)`, or `ci(deps)` — the `(deps)` scope is required, so a bare `chore:` or `build:` subject is still rejected — and
skips the check entirely for merge/revert/fixup commits (`Merge`, `Revert`,
`fixup!`, `squash!`, `Amend!`). Anything else is rejected, so reach for the
closest listed prefix rather than inventing one.

## Security gate (`_security.sh` + `security.conf`)

Full explainer, install line for every agent, and reuse steps: [`docs/GITHOOKS.md`](../docs/GITHOOKS.md).

`pre-commit` and `pre-push` both source `_security.sh` (generic, shared with
cg-agent-harness) and `security.conf` (CyClaw values). It covers only what CI
sees too late or cannot see:

| Check | pre-commit | pre-push | Override |
|-------|-----------|----------|----------|
| Credential-shaped strings in added lines (provider prefixes; plus `gitleaks` when installed) | staged diff | every commit being published | none — fix, or mark a fixture `gitleaks:allow` |
| Credential / runtime-state filenames (`.env`, `*.key`, `*.db`, `CONSOLIDATED.md`, …) | staged | every commit being published | `SEC_BLOCKED_EXCEPT` in `security.conf` |
| Protected control files (`soul.md`, `utils/sanitizer.py`, `gate_auth.py`, scanner ignore files, `.githooks/*`) | staged | pushed range | `HOOK_OPERATOR_ACK=1` (operator only) |
| Privacy: operator identifiers from the untracked private file, absolute home-directory paths, invisible bidi / Unicode-tag characters | staged diff | every commit being published | none — use a placeholder; fixture lines take `gitleaks:allow` |
| Agent session residue (`.aider*`, `settings.local.json`, `*.har`, shell histories, …), new files over `SEC_MAX_NEW_FILE_KB`, media with GPS/author metadata (needs `exiftool`) | staged | filenames only | `SEC_BLOCKED_EXCEPT` / raise the cap with the operator |
| `.gitignore` rule removed (also checked on pushed commits); agent tool wiring (`.mcp.json`, `.claude/settings.json`, `.codex/config.toml`) changed or deleted | staged | rule removal: blocks; wiring: reminder | `HOOK_OPERATOR_ACK=1` (operator only) |
| Secure-by-design questions when a diff adds a route, outbound call, exec/deserialization, persisted model, file write, config input, telemetry or HTML sink; reminders for dependency manifests and agent instruction files | printed, not blocking | — | answer in the PR body |
| `ruff --select F,B,S` on staged Python (if `ruff` is installed) | yes | — | fix the finding |
| Direct push to, or deletion of, `main` | — | yes | `ALLOW_MAIN_PUSH=1` (operator only; delete has none) |
| Non-fast-forward push | — | yes | `ALLOW_FORCE_WITH_LEASE=true` (operator only) |
| `invariant-guard` (run on an export of each pushed commit) when any file it reads is in the push: the core six, `config.yaml`, `utils/personality*.py`, the out-of-band packages | — | yes | fix the finding |

Operator-private patterns (`SEC_PII_REGEX`, `SEC_AUTHOR_EMAIL_DENY`) live in
`~/.config/githooks/private.conf` or the untracked `.githooks/security.local.conf`,
never in `security.conf`: a tracked list of your identifiers is the leak.

It is a speed bump, not a boundary: `--no-verify`, a clone that never ran the
install step, and the agentic pipeline (which pins `core.hooksPath` to an empty
directory for its workspace clones) all bypass it. The `gitleaks.yml` workflow
and the `main` ruleset remain the controls.

## PR body template (not a git hook)

Git cannot intercept PR bodies created via the GitHub UI, `gh pr create`, or
the GitHub connector API. For that layer:

1. **Always** fill [`.github/PULL_REQUEST_TEMPLATE.md`](../.github/PULL_REQUEST_TEMPLATE.md) fully when opening a PR (required for Grok Build + GitHub connector on cgfixit/CyClaw).
2. **Local check:** `scripts/check-pr-template.sh path/to/body.md` before create.
3. **CI:** blocking check via `.github/workflows/pr-template-check.yml` (same headers as `scripts/check-pr-template.sh`).

Example:

```bash
# draft body from template, edit, then gate
cp .github/PULL_REQUEST_TEMPLATE.md /tmp/pr-body.md
# ... fill sections ...
scripts/check-pr-template.sh /tmp/pr-body.md
gh pr create --title '[docs] - …' --body-file /tmp/pr-body.md
```

## Install (once per clone)

```bash
bash scripts/install-githooks.sh
# or: git config core.hooksPath .githooks && chmod +x .githooks/*
```

Verify:

```bash
git config core.hooksPath   # → .githooks
```

The pre-push gate deliberately does not rebase or force-push for you. Rebase,
inspect conflicts, rerun the relevant checks, and use force-with-lease only
with explicit approval. It also cannot infer multi-PR semantics: map shared
files and trial the chronological merge order as required by
`.codex/Codex_instructions.md`.

## Bypass (emergency only)

```bash
git commit --no-verify
git push --no-verify
```

Do not use bypass for routine feature work.
