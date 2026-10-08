#!/usr/bin/env bash
# CyClaw SessionStart hook — git identity + local/remote sync guard.
#
# Purpose (proactive, NON-destructive):
#   1. Leave the commit identity to the session runtime. Claude Code commits
#      as the runtime's identity: in the cloud, Claude <noreply@anthropic.com>,
#      which the runtime signs so GitHub shows the commit Verified; locally,
#      the operator's own git identity. This hook used to pin CyClaw Agent,
#      which overrode that identity and left every cloud commit Unverified; it
#      now removes that old pin (only while it still holds the old default,
#      never an identity someone set on purpose) and pins nothing.
#      CYCLAW_AGENT_COMMIT_EMAIL / CYCLAW_AGENT_COMMIT_NAME set the identity of
#      CyClaw's own agentic loop (utils/agent_identity.py), not this one.
#   1b. Point core.hooksPath at the tracked .githooks/ via
#      scripts/ensure-githooks.sh (idempotent; leaves a deliberate value alone).
#   2. Fetch the default branch and REPORT divergence between local and remote.
#      It never resets, rebases, pushes, or deletes — it only informs, so a
#      human stays in control of how to reconcile.
#
# Exit code is always 0: this hook advises, it must never block a session.
set -uo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$repo_root" || exit 0

# ── 1. Commit identity: the runtime's ───────────────────────────────────────
# The hook pins no identity. All it could write is repo-local git config,
# which every session and worktree of this repository shares and which the
# GIT_AUTHOR_* / GIT_COMMITTER_* environment a runtime may export outranks, so
# it cannot give one session an identity of its own. It only removes the old
# CyClaw Agent pin, and only while that pin still holds the old default.
legacy_email="cyclaw-agent@users.noreply.github.com"
# user.email can hold several values (git uses the last one), and a plain
# --unset refuses to touch a key with more than one, so every value is read
# and only the old default's are removed, by an anchored pattern.
local_emails=$(git config --local --get-all user.email 2>/dev/null)
effective_email=$(git config --local --get user.email 2>/dev/null)
if grep -Fxq "$legacy_email" <<<"$local_emails"; then
  git config --local --unset-all user.email '^cyclaw-agent@users\.noreply\.github\.com$'
  # The old default name goes with its email, and only when that email was
  # the one in effect. Beside an email someone chose, including one added
  # after the old pin, the name is theirs too.
  if [ "$effective_email" = "$legacy_email" ]; then
    git config --local --unset-all user.name '^CyClaw Agent$' 2>/dev/null
  fi
fi
# Report what the next commit will actually carry. GIT_AUTHOR_* and
# GIT_COMMITTER_* environment variables outrank user.name/user.email, so ask
# git itself rather than reading the config keys.
author=$(git var GIT_AUTHOR_IDENT 2>/dev/null | sed -E 's/ [0-9]+ [-+][0-9]{4}$//')
committer=$(git var GIT_COMMITTER_IDENT 2>/dev/null | sed -E 's/ [0-9]+ [-+][0-9]{4}$//')
# Author and committer are separate lookups: GIT_COMMITTER_* alone leaves the
# author unset, and git then refuses the commit, so both must resolve.
if [ -z "$author" ] || [ -z "$committer" ]; then
  echo "[sync-check] No complete commit identity (author: ${author:-none}, committer: ${committer:-none}); git will refuse to commit until user.name and user.email are set."
elif [ "$author" = "$committer" ]; then
  echo "[sync-check] Commits will be made as: $committer"
else
  echo "[sync-check] Commits will be made as: author $author, committer $committer"
fi

# ── 1b. Tracked git hooks: point core.hooksPath at .githooks ────────────────
# Same agent-neutral line Copilot, Codex and people run (scripts/ensure-githooks.sh):
# idempotent, never overwrites a deliberate hooksPath, never fails the session.
if [ -f "$repo_root/scripts/ensure-githooks.sh" ]; then
  bash "$repo_root/scripts/ensure-githooks.sh" 2>/dev/null | sed 's/^\[githooks\]/[sync-check]/'
fi

# ── 2. Detect default branch (origin/HEAD, fallback main) ────────────────────
default_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')
default_branch=${default_branch:-main}

# ── 3. Fetch the default branch (read-only) ──────────────────────────────────
git fetch --quiet origin "+$default_branch:refs/remotes/origin/$default_branch" 2>/dev/null || {
  echo "[sync-check] Could not fetch origin/$default_branch (offline?). Skipping divergence report."
  exit 0
}

# ── 4. Report divergence WITHOUT changing anything ───────────────────────────
current=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
counts=$(git rev-list --left-right --count "origin/$default_branch...HEAD" 2>/dev/null) || exit 0
behind=$(echo "$counts" | awk '{print $1}')
ahead=$(echo "$counts" | awk '{print $2}')

echo "[sync-check] On '$current'. vs origin/$default_branch: ahead $ahead, behind $behind."

if [ "$current" = "$default_branch" ] && { [ "$ahead" -gt 0 ] || [ "$behind" -gt 0 ]; }; then
  echo "[sync-check] ⚠ Local $default_branch has diverged from origin/$default_branch."
  echo "[sync-check]   This hook will NOT auto-reconcile. To sync deliberately:"
  [ "$behind" -gt 0 ] && [ "$ahead" -eq 0 ] && \
    echo "[sync-check]     git merge --ff-only origin/$default_branch   # fast-forward, safe"
  [ "$ahead" -gt 0 ] && \
    echo "[sync-check]     review 'git log origin/$default_branch..HEAD' before discarding"
  echo "[sync-check]   Never 'git reset --hard' unsynced local commits without checking them first."
fi

exit 0
