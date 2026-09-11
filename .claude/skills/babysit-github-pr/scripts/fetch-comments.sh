#!/bin/bash
# fetch-comments.sh: Fetch unresolved comments newer than last_comment_id.
# Output: JSON array of comment objects.

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <pr-number> <last-comment-id>" >&2
    exit 1
fi

PR_NUMBER="$1"
LAST_COMMENT_ID="$2"

# Fetch all unresolved comments
# Include both PR review comments and issue comments
# Include bots without [bot] suffix (e.g., copilot-pull-request-reviewer)

COMMENTS=$(gh api repos/:owner/:repo/pulls/"$PR_NUMBER"/comments \
    --paginate \
    --jq '[.[] | select(.resolved_at == null and .id > '"$LAST_COMMENT_ID"') | {
        id: .id,
        body: .body,
        author: .user.login,
        path: .path,
        position: .position,
        url: .html_url
    }]' \
    2>/dev/null || echo "[]")

# Also fetch review comments from review API
REVIEW_COMMENTS=$(gh api repos/:owner/:repo/pulls/"$PR_NUMBER"/reviews \
    --paginate \
    --jq '[.[] | select(.state != "COMMENTED") | {
        id: .id,
        body: .body,
        author: .user.login,
        state: .state,
        url: .html_url
    }]' \
    2>/dev/null || echo "[]")

# Merge and output
jq -n \
    --argjson comments "$COMMENTS" \
    --argjson reviews "$REVIEW_COMMENTS" \
    '($comments + $reviews) | sort_by(.id)'
