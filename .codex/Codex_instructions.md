# Codex workflow overlay

[AGENTS.md](../AGENTS.md) owns shared policy and [CLAUDE.md](../CLAUDE.md) section 5 owns verification. The root guidance links this overlay for Codex Git and PR work.

1. Inspect checkout, remotes, dirty state and local commits. Fetch `origin/main`, check open-PR overlap and record base/head. Preserve unrelated work with an isolated checkout where needed.
2. Use `codex/<topic>` or keep the existing PR branch. Run `bash scripts/ensure-githooks.sh` once per clone and use the runtime's own commit identity.
3. Consolidate a shared concern or stack a genuine dependency. Trial-merge overlaps in the intended order and inspect the resulting changes.
4. Verify the final diff and staged files. Before pushing, refresh the base and destination refs, resolve drift and rerun affected checks. Read the remote ref after any ambiguous push result.
5. For authorized publication, follow the [PR template](../.github/PULL_REQUEST_TEMPLATE.md), including the trial-merge note, final ELI5 and timestamp. Run `bash scripts/check-pr-template.sh --title "$title" --branch "$branch" "$body_file"`. Flag changes to agent instructions and workflow prompts for human review.
6. Read back the draft and verify its exact remote head. Report checks, skips, review state and mergeability separately. When asked to monitor, follow that head to terminal checks or report the observation blocker.

Keep drafts open for human merge. Preserve concurrent remote work and follow the root authorization rules for merges and history rewrites.

For skill edits, use the [inventory and validation commands](README.md#validation). Check triggers, references and policy with representative matching and adjacent tasks. For hosted prompt edits, check the [three workflow contracts](README.md#hosted-pr-prompts).
