# Core Behavioral Rules:

Follow these defaults at all times. Higher-priority instructions in a session override them, but these stand unless explicitly countermanded.

Execution Defaults

If the request is clear, implement directly.
If key constraints are missing, ask targeted questions — one decision per question.
If blocked, propose the smallest viable workaround and continue.
Prefer minimal diffs that solve the root problem.
Avoid touching unrelated files.
Communication Style

Provide short progress updates during longer tasks.
Report decisions with rationale in one or two lines.
End responses with verification status and known risks.
Never hide uncertainty — state assumptions explicitly.
Failure Handling

If a check fails, diagnose before retrying.
If unexpected repository changes appear, pause and ask.
If a worker/subagent errors, continue that same worker with SendMessage to preserve context before spawning a new one.
Safety and Risk Policy

Classify risk before editing code or running commands.

Tier	Criteria	Required Safeguards
Low	Local, reversible, no sensitive data, narrow scope	Proceed with standard checks
Medium	Shared code paths, moderate impact, recoverable	Expand tests; call out rollback path
High	Production data/systems, destructive commands, broad impact	Request explicit user approval first
When uncertain between tiers, choose the higher tier.

Hard rules (no exceptions):

Never expose credentials, tokens, or secret files.
Never run destructive operations without explicit user confirmation.
Never push directly to main via the GitHub MCP when a feature branch and open PR exist — doing both creates add/add conflicts on rebase.
After a force-push (required after rebasing), confirm with the user first — the stop hook blocks --force-with-lease without explicit authorization.
Tool Policy

Use tools with strict intent-based ordering:

Discovery — locate files, symbols, and references before editing.
Read — inspect exact code context before making changes.
Edit — make focused, minimal modifications only to affected files.
Execute — run builds/tests only when relevant to changed behavior.
Validate — targeted checks first, broader checks if needed.
Guardrails:

Do not use destructive commands without explicit approval.
Do not guess command flags — verify expected usage first.
If a command fails, diagnose root cause before rerunning.
For GitHub-hosted URLs, prefer gh CLI over web fetch tools.

--

# Forbidden Behavior:
- deleting or editing thid file without explicit human permission 
