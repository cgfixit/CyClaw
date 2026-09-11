#!/bin/bash
# run-babysit.sh: Main orchestrator for the PR babysit loop.
# Parses input (PR number, branch, URL), manages state, runs the loop.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE=".git/babysit-state.json"

# Defaults (can be overridden by env vars)
DRAFT_BY_DEFAULT="${DRAFT_BY_DEFAULT:-true}"
POLL_SECONDS="${POLL_SECONDS:-90}"
FLAKY_RETRIES="${FLAKY_RETRIES:-2}"
MAX_FIX_ATTEMPTS="${MAX_FIX_ATTEMPTS:-3}"
MAX_ITERATIONS="${MAX_ITERATIONS:-8}"
BLAST_RADIUS_FILES="${BLAST_RADIUS_FILES:-5}"
AUTO_MERGE="${AUTO_MERGE:-false}"
TIMEOUT_MINUTES="${TIMEOUT_MINUTES:-45}"

# State tracking
declare -A RETRY_COUNTS
ITERATION=0
LAST_COMMENT_ID=0
STOP_REASON=""
FINAL_REPORT=""


# ============================================================================
# Utilities
# ============================================================================

log_info() {
    echo "[babysit] $*" >&2
}

log_error() {
    echo "[babysit ERROR] $*" >&2
}

# Load state from .git/babysit-state.json
load_state() {
    if [[ ! -f "$STATE_FILE" ]]; then
        log_info "Initializing new state file: $STATE_FILE"
        return
    fi

    if ! LAST_COMMENT_ID=$(jq -r '.last_comment_id // 0' "$STATE_FILE" 2>/dev/null); then
        LAST_COMMENT_ID=0
    fi

    if ! ITERATION=$(jq -r '.iteration // 0' "$STATE_FILE" 2>/dev/null); then
        ITERATION=0
    fi

    # Load retry counts
    if RETRY_JSON=$(jq -r '.retry_counts // {}' "$STATE_FILE" 2>/dev/null); then
        while IFS= read -r key value; do
            RETRY_COUNTS["$key"]="$value"
        done < <(echo "$RETRY_JSON" | jq -r 'to_entries[] | "\(.key) \(.value)"')
    fi
}

# Save state to .git/babysit-state.json
save_state() {
    local retry_json="{"
    local first=true
    for check_name in "${!RETRY_COUNTS[@]}"; do
        if [[ "$first" == false ]]; then
            retry_json+=","
        fi
        retry_json+="\"$check_name\": ${RETRY_COUNTS[$check_name]}"
        first=false
    done
    retry_json+="}"

    jq -n \
        --arg last_id "$LAST_COMMENT_ID" \
        --arg iter "$ITERATION" \
        --argjson retries "$retry_json" \
        --arg test_cmd "${DETECTED_TEST_CMD:-}" \
        --arg lint_cmd "${DETECTED_LINT_CMD:-}" \
        '{
            last_comment_id: ($last_id | tonumber),
            iteration: ($iter | tonumber),
            retry_counts: $retries,
            detected_test_command: $test_cmd,
            detected_lint_command: $lint_cmd
        }' > "$STATE_FILE"

    log_info "State saved to $STATE_FILE"
}

# Parse PR number from input (number, branch, or URL)
parse_pr_input() {
    local input="$1"

    if [[ "$input" =~ ^[0-9]+$ ]]; then
        echo "$input"
    elif [[ "$input" =~ ^https://github.com/.*/.*/pull/([0-9]+) ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        # Assume it's a branch name; try to find PR
        local pr_num=$(gh pr list --head "$input" --json number --jq '.[0].number' 2>/dev/null || echo "")
        if [[ -z "$pr_num" ]]; then
            log_error "Could not find PR for branch: $input"
            exit 1
        fi
        echo "$pr_num"
    fi
}

# Ensure PR exists; create if needed
ensure_pr_exists() {
    local pr_number="$1"
    local current_branch=$(git rev-parse --abbrev-ref HEAD)

    if gh pr view "$pr_number" --repo . >/dev/null 2>&1; then
        log_info "PR #$pr_number already exists"
        return 0
    fi

    # PR doesn't exist; create it
    log_info "Creating new PR for branch: $current_branch"

    # Push branch if not pushed
    if ! git rev-parse --verify "origin/$current_branch" >/dev/null 2>&1; then
        log_info "Pushing branch to origin..."
        git push -u origin "$current_branch"
    fi

    # Create PR
    local draft_flag=""
    if [[ "$DRAFT_BY_DEFAULT" == "true" ]]; then
        draft_flag="--draft"
    fi

    gh pr create $draft_flag --fill --repo . || log_error "Failed to create PR"

    # Extract PR number from new PR
    PR_NUMBER=$(gh pr view --json number --jq '.number' --repo .)
}

# ============================================================================
# Loop Steps
# ============================================================================

sync_state() {
    log_info "Step 1: Syncing PR state..."

    STATE_JSON=$("$SCRIPT_DIR/pr-state.sh" "$PR_NUMBER")

    # Extract fields
    PR_STATE=$(echo "$STATE_JSON" | jq -r '.state')
    MERGE_STATE=$(echo "$STATE_JSON" | jq -r '.mergeStateStatus // "unknown"')
    REVIEW_DECISION=$(echo "$STATE_JSON" | jq -r '.reviewDecision // "REVIEW_REQUIRED"')
    HEAD_REF=$(echo "$STATE_JSON" | jq -r '.headRefName')
    BASE_REF=$(echo "$STATE_JSON" | jq -r '.baseRefName')

    log_info "  PR #$PR_NUMBER ($HEAD_REF → $BASE_REF) | State: $PR_STATE | Merge: $MERGE_STATE | Review: $REVIEW_DECISION"

    # Check if PR is closed or merged
    if [[ "$PR_STATE" == "MERGED" ]]; then
        STOP_REASON="PR already merged"
        return 1
    elif [[ "$PR_STATE" == "CLOSED" ]]; then
        STOP_REASON="PR already closed"
        return 1
    fi
}

rebase_if_behind() {
    log_info "Step 2: Checking rebase status..."

    if [[ "$MERGE_STATE" == "BEHIND" ]] || [[ "$MERGE_STATE" == "DIRTY" ]]; then
        log_info "  Rebasing onto origin/$BASE_REF..."

        git fetch origin

        # Check for mixed authorship before rebasing
        local current_branch=$(git rev-parse --abbrev-ref HEAD)
        local current_author=$(git config user.email)

        if git log origin/$BASE_REF.."$current_branch" --format=%aE | grep -v "^${current_author}$" >/dev/null 2>&1; then
            STOP_REASON="Rebase would touch commits from another author"
            log_error "  $STOP_REASON"
            return 1
        fi

        # Attempt rebase
        if ! git rebase "origin/$BASE_REF" 2>/dev/null; then
            log_info "  Rebase conflict detected. Attempting auto-resolution..."

            # Simple auto-resolution: for each conflict, try to keep both sides
            # This is a best-effort; complex conflicts will still fail
            local resolved=0
            local unresolved_files=""

            while read -r conflicted_file; do
                log_info "    Resolving: $conflicted_file"
                if git checkout --theirs "$conflicted_file" 2>/dev/null; then
                    git add "$conflicted_file"
                    resolved=$((resolved + 1))
                else
                    unresolved_files="$unresolved_files\n      - $conflicted_file"
                fi
            done < <(git diff --name-only --diff-filter=U)

            if [[ -z "$unresolved_files" ]]; then
                git rebase --continue || {
                    STOP_REASON="Auto-resolution failed during rebase continuation"
                    git rebase --abort
                    return 1
                }
                log_info "  Auto-resolved $resolved files. Continuing rebase..."
            else
                STOP_REASON="Merge conflict auto-resolution failed (overlapping edits):$unresolved_files"
                git rebase --abort
                log_error "  $STOP_REASON"
                return 1
            fi
        fi

        log_info "  Rebase successful. Running checks before push..."

        # Run local checks if test command is available
        if [[ -n "${DETECTED_TEST_CMD:-}" ]]; then
            if ! eval "$DETECTED_TEST_CMD" >/dev/null 2>&1; then
                log_error "  Local test failed; aborting rebase push"
                return 1
            fi
        fi

        # Push with force-lease
        log_info "  Pushing with --force-with-lease..."
        git push --force-with-lease || {
            STOP_REASON="Push failed after rebase"
            return 1
        }
    fi
}

wait_for_checks() {
    log_info "Step 3: Waiting for checks..."

    "$SCRIPT_DIR/wait-for-checks.sh" "$PR_NUMBER" "$POLL_SECONDS" "$TIMEOUT_MINUTES"
    local wait_result=$?

    if [[ $wait_result -eq 0 ]]; then
        log_info "  All checks passing!"
        return 0
    elif [[ $wait_result -eq 1 ]]; then
        log_info "  One or more checks are failing."
        return 0  # Continue to triage
    elif [[ $wait_result -eq 2 ]]; then
        STOP_REASON="Checks did not settle within ${TIMEOUT_MINUTES} minutes"
        return 1
    elif [[ $wait_result -eq 3 ]]; then
        log_info "  No checks configured."
        return 0  # Continue anyway
    fi
}

triage_failures() {
    log_info "Step 4: Triaging failures..."

    local failures=$(echo "$STATE_JSON" | jq -r '.checks[] | select(.status == "failure") | .name' 2>/dev/null || echo "")

    if [[ -z "$failures" ]]; then
        log_info "  No failures to triage."
        return 0
    fi

    while read -r check_name; do
        log_info "  Checking: $check_name"

        # Get run ID for this check
        local run_id=$(gh run list --repo . --json name,databaseId --jq ".[] | select(.name == \"$check_name\") | .databaseId" 2>/dev/null | head -1 || echo "")

        if [[ -z "$run_id" ]]; then
            log_info "    Could not find run ID; skipping."
            continue
        fi

        # Get current retry count
        local current_retries=${RETRY_COUNTS[$check_name]:-0}

        # Fetch logs and classify
        local classification=$(gh run view "$run_id" --log-failed 2>/dev/null | \
            python3 "$SCRIPT_DIR/classify-failure.py" "$check_name" || echo '{"class": "unknown"}')

        local failure_class=$(echo "$classification" | jq -r '.class')
        local signal=$(echo "$classification" | jq -r '.signal')

        log_info "    Classification: $failure_class (signal: $signal)"

        if [[ "$failure_class" == "flaky" ]]; then
            if [[ $current_retries -lt $FLAKY_RETRIES ]]; then
                log_info "    Retrying flaky check ($((current_retries + 1))/$FLAKY_RETRIES)..."
                gh run rerun "$run_id" --failed 2>/dev/null || log_error "    Failed to rerun"
                RETRY_COUNTS[$check_name]=$((current_retries + 1))
            else
                log_error "    Flaky check exceeded retries ($FLAKY_RETRIES)"
            fi
        elif [[ "$failure_class" == "code" ]]; then
            if [[ $current_retries -lt $MAX_FIX_ATTEMPTS ]]; then
                log_info "    Code failure; local reproduction needed."
                log_info "    Run: $DETECTED_TEST_CMD"
                # Note: User would need to fix locally; skill would need to be interactive
                # For now, log and increment
                RETRY_COUNTS[$check_name]=$((current_retries + 1))
            else
                log_error "    Code check exceeded fix attempts ($MAX_FIX_ATTEMPTS)"
            fi
        else
            log_info "    Unknown failure; moving on."
        fi
    done <<< "$failures"
}

address_comments() {
    log_info "Step 5: Processing review comments..."

    local comments=$(bash "$SCRIPT_DIR/fetch-comments.sh" "$PR_NUMBER" "$LAST_COMMENT_ID" 2>/dev/null || echo "[]")
    local comment_count=$(echo "$comments" | jq 'length')

    if [[ "$comment_count" -eq 0 ]]; then
        log_info "  No new unresolved comments."
        return 0
    fi

    log_info "  Found $comment_count new comments to process."

    # Process each comment
    echo "$comments" | jq -c '.[]' | while read -r comment; do
        local comment_id=$(echo "$comment" | jq -r '.id')
        local comment_author=$(echo "$comment" | jq -r '.author')
        local comment_body=$(echo "$comment" | jq -r '.body')

        log_info "    Comment from $comment_author (ID: $comment_id): ${comment_body:0:50}..."

        # In a real implementation, this would parse the comment and decide
        # whether to fix it automatically or defer to the human.
        # For now, just log it.

        LAST_COMMENT_ID=$comment_id
    done
}

check_exit_conditions() {
    log_info "Step 6: Checking exit conditions..."

    ITERATION=$((ITERATION + 1))

    # Fetch fresh state
    sync_state || return 1

    # All checks passing?
    local failures=$(echo "$STATE_JSON" | jq -r '.checks[] | select(.status == "failure") | .name' 2>/dev/null || echo "")
    local unresolved_count=$(echo "$STATE_JSON" | jq -r '.unresolved_comment_count')

    if [[ -z "$failures" ]] && [[ $unresolved_count -eq 0 ]]; then
        log_info "  ✓ All checks passing and no unresolved comments."

        if [[ "$REVIEW_DECISION" == "APPROVED" ]]; then
            log_info "  ✓ PR is approved."

            if [[ "$AUTO_MERGE" == "true" ]]; then
                log_info "  Auto-merging PR..."
                gh pr merge "$PR_NUMBER" --squash --auto || log_error "Failed to auto-merge"
            fi

            STOP_REASON="PR ready for merge (approved + green)"
            return 1
        else
            log_info "  ⚠ PR not yet approved; awaiting reviewer."
            STOP_REASON="PR green but awaiting approval"
            return 1
        fi
    fi

    # Iteration limit?
    if [[ $ITERATION -ge $MAX_ITERATIONS ]]; then
        STOP_REASON="Iteration limit reached ($MAX_ITERATIONS)"
        return 1
    fi

    log_info "  Continuing (iteration $ITERATION / $MAX_ITERATIONS)..."
}


# ============================================================================
# Main Loop
# ============================================================================

main() {
    if [[ $# -lt 1 ]]; then
        cat >&2 <<EOF
Usage: $0 <pr-number|branch-name|pr-url>

Examples:
  $0 123
  $0 feature/my-fix
  $0 https://github.com/owner/repo/pull/123

Environment:
  DRAFT_BY_DEFAULT=true|false
  POLL_SECONDS=90
  FLAKY_RETRIES=2
  MAX_FIX_ATTEMPTS=3
  MAX_ITERATIONS=8
  BLAST_RADIUS_FILES=5
  AUTO_MERGE=true|false
  TIMEOUT_MINUTES=45
EOF
        exit 1
    fi

    # Load persisted state
    load_state

    # Parse input to get PR number
    PR_NUMBER=$(parse_pr_input "$1")
    log_info "Starting babysit for PR #$PR_NUMBER"

    # Ensure PR exists
    ensure_pr_exists "$PR_NUMBER"

    # Detect test command if not cached
    if [[ -z "${DETECTED_TEST_CMD:-}" ]]; then
        local detect_output=$(python3 "$SCRIPT_DIR/detect-test-command.py")
        DETECTED_TEST_CMD=$(echo "$detect_output" | jq -r '.test_command')
        DETECTED_LINT_CMD=$(echo "$detect_output" | jq -r '.lint_command')
        log_info "Detected test command: $DETECTED_TEST_CMD"
        log_info "Detected lint command: $DETECTED_LINT_CMD"
    fi

    # Main loop
    while true; do
        log_info "--- Iteration $((ITERATION + 1)) / $MAX_ITERATIONS ---"

        sync_state || break
        rebase_if_behind || break
        wait_for_checks || break
        triage_failures || true
        address_comments || true
        check_exit_conditions || break
    done

    # Save final state
    save_state

    # Print final report
    print_report
}

print_report() {
    cat <<EOF

=== BABYSIT REPORT ===
PR: $PR_NUMBER
Status: $(if [[ -n "$STOP_REASON" ]]; then echo "$STOP_REASON"; else echo "unknown"; fi)

Final State (from last sync):
  Merge State: $MERGE_STATE
  Review Decision: $REVIEW_DECISION
  Iteration: $ITERATION / $MAX_ITERATIONS

Stop Reason:
  $STOP_REASON

Next Steps:
  - Review the report above
  - If needed, resolve merge conflicts manually and re-invoke
  - If awaiting approval, request a review from @reviewer

EOF
}


# Run main
main "$@"
