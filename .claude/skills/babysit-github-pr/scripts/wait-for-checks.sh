#!/bin/bash
# wait-for-checks.sh: Block until PR checks settle or timeout.
# Exit codes: 0=all passing, 1=red, 2=timeout, 3=no checks.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <pr-number> [poll_seconds] [timeout_minutes]" >&2
    exit 1
fi

PR_NUMBER="$1"
POLL_SECONDS="${2:-90}"
TIMEOUT_MINUTES="${3:-45}"

TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))
ELAPSED=0

echo "Waiting for checks to settle (timeout: ${TIMEOUT_MINUTES}m, poll: ${POLL_SECONDS}s)..." >&2

while [[ $ELAPSED -lt $TIMEOUT_SECONDS ]]; do
    CHECKS=$(gh pr checks "$PR_NUMBER" --repo . --json name,status 2>/dev/null || echo "[]")

    # Check if any checks are terminal
    if [[ "$CHECKS" == "[]" ]]; then
        echo "No checks configured." >&2
        exit 3
    fi

    # Count pending, success, failure
    PENDING_COUNT=$(echo "$CHECKS" | jq '[.[] | select(.status == "pending")] | length')
    FAILURE_COUNT=$(echo "$CHECKS" | jq '[.[] | select(.status == "failure")] | length')
    SUCCESS_COUNT=$(echo "$CHECKS" | jq '[.[] | select(.status == "success")] | length')

    if [[ $PENDING_COUNT -eq 0 ]]; then
        # All checks terminal
        if [[ $FAILURE_COUNT -gt 0 ]]; then
            echo "Checks complete: $SUCCESS_COUNT passing, $FAILURE_COUNT failing." >&2
            exit 1  # Red
        else
            echo "All checks passing." >&2
            exit 0  # Green
        fi
    fi

    echo "Still waiting... ($SUCCESS_COUNT passing, $FAILURE_COUNT failing, $PENDING_COUNT pending) [${ELAPSED}s / ${TIMEOUT_SECONDS}s]" >&2
    sleep "$POLL_SECONDS"
    ELAPSED=$((ELAPSED + POLL_SECONDS))
done

echo "Timeout: checks did not settle within ${TIMEOUT_MINUTES} minutes." >&2
exit 2
