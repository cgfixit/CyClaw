#!/bin/bash
# pr-state.sh: Fetch current PR state (metadata, checks, unresolved comments).
# Output: JSON object with PR metadata and check statuses.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <pr-number>" >&2
    exit 1
fi

PR_NUMBER="$1"

# Fetch PR metadata
PR_JSON=$(gh pr view "$PR_NUMBER" --json \
    number,headRefName,baseRefName,mergeable,mergeStateStatus,reviewDecision,isDraft,state,headRefOid \
    --repo . 2>/dev/null || echo "{}")

# Fetch check statuses
CHECKS_JSON=$(gh pr checks "$PR_NUMBER" --repo . --json name,status 2>/dev/null || echo "[]")

# Count unresolved comments (threads and top-level, excluding outdated)
UNRESOLVED_COUNT=$(gh api repos/:owner/:repo/pulls/"$PR_NUMBER"/comments \
    --paginate --jq '[.[] | select(.resolved_at == null)] | length' \
    2>/dev/null || echo "0")

# Merge into single JSON output
jq -n \
    --argjson pr "$PR_JSON" \
    --argjson checks "$CHECKS_JSON" \
    --arg unresolved "$UNRESOLVED_COUNT" \
    '{
        number: $pr.number,
        headRefName: $pr.headRefName,
        baseRefName: $pr.baseRefName,
        mergeable: $pr.mergeable,
        mergeStateStatus: $pr.mergeStateStatus,
        reviewDecision: $pr.reviewDecision,
        isDraft: $pr.isDraft,
        state: $pr.state,
        headRefOid: $pr.headRefOid,
        checks: $checks,
        unresolved_comment_count: ($unresolved | tonumber)
    }'
