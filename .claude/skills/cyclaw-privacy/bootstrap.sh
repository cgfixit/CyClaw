#!/usr/bin/env bash
# bootstrap.sh — cyclaw-privacy skill harness.
# Refreshes origin/main and prints the SHA a review should cite, then runs
# verify.sh so the posture SKILL.md describes is confirmed before advising.
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root" || exit 3

hr() { printf '%s\n' "------------------------------------------------------------"; }

echo "Bootstrapping cyclaw-privacy skill..."
hr
git fetch origin main --quiet || echo "WARN: fetch failed (offline?); citing the local ref"
echo "origin/main: $(git rev-parse --short origin/main 2>/dev/null || echo 'unknown')"
echo "HEAD:        $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
hr
bash "$repo_root/.claude/skills/cyclaw-privacy/verify.sh"
rc=$?
hr
echo "Legal compliance assistant mode: DPA reviews, DSR handling, breach triage, regulatory monitoring."
echo "Cite config.yaml at the SHA above; the numbers are tunables, not constants."
exit "$rc"
