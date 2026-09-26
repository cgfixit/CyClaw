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
#      never an identity someone set on purpose). Setting
#      CYCLAW_AGENT_COMMIT_EMAIL / CYCLAW_AGENT_COMMIT_NAME explicitly still
#      pins them. CyClaw's own agentic loop takes its identity from
#      utils/agent_identity.py, unchanged.
#   2. Fetch the default branch and REPORT divergence between local and remote.
#      It never resets, rebases, pushes, or deletes — it only informs, so a
#      human stays in control of how to reconcile.
#
# Exit code is always 0: this hook advises, it must never block a session.
set -uo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$repo_root" || exit 0

# ── 1. Commit identity: the runtime's, unless explicitly overridden ─────────
legacy_email="cyclaw-agent@users.noreply.github.com"
legacy_name="CyClaw Agent"
if [ -n "${CYCLAW_AGENT_COMMIT_EMAIL:-}" ] || [ -n "${CYCLAW_AGENT_COMMIT_NAME:-}" ]; then
  [ -n "${CYCLAW_AGENT_COMMIT_EMAIL:-}" ] && git config --local user.email "$CYCLAW_AGENT_COMMIT_EMAIL"
  [ -n "${CYCLAW_AGENT_COMMIT_NAME:-}" ] && git config --local user.name "$CYCLAW_AGENT_COMMIT_NAME"
elif [ "$(git config --local --get user.email 2>/dev/null)" = "$legacy_email" ]; then
  git config --local --unset user.email
  [ "$(git config --local --get user.name 2>/dev/null)" = "$legacy_name" ] && git config --local --unset user.name
fi
echo "[sync-check] Commits will be authored as: $(git config user.name 2>/dev/null) <$(git config user.email 2>/dev/null)>"

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
