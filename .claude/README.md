# `.claude/` — project skills and workflows

Quick reference for Claude Code assistance patterns in CyClaw.

## Skills

[`CLAUDE.md` §9](../CLAUDE.md) owns the complete inventory: **23 project
skills and 28 slash commands**, including five standalone commands. Common
entry points below are Claude Code session commands, not shell commands.

```text
/invariant-guard         # Static-assert the six security invariants (stdlib)
/config-guard            # Static-validate config.yaml's relational/value/threat-model contract
/dep-guard               # Static-validate dependency-pin invariants (pyproject + constraints)
/dotenv-guard            # Keep secret-classified names out of dotenv files and loaders
/run                     # Smoke-test the FastAPI server (smoke suite, sections A-G)
/architecture-refactor   # Start architecture refactor loop
/tests-refactor          # Start test coverage loop
/logging-refactor        # Start logging audit loop
/speed-refactor          # Start speed optimization loop
/doc-sync                # Detect and reconcile code<->doc drift
/CyClaw-Sandbox          # Full clone/current-checkout verification ladders
/babysit-github-pr       # Explicitly authorized PR watch/CI loop
/CyClaw-Optimize         # there are many more, verify folder each time
```

The four static guards are `/invariant-guard` for topology and imports,
`/config-guard` for config values and relations, `/dep-guard` for dependency
pins, and `/dotenv-guard` for secret-at-rest policy. Each ships a checker and a
`verify.sh`; CI runs them automatically. See the authoritative table in
[`CLAUDE.md`](../CLAUDE.md) §9.

## Refactor Loop Pattern

The `*-refactor` skills share this broad cycle; each skill defines its own
measurement and stopping criteria:

1. **Measure** — baseline the current state (tests, latency, log coverage)
2. **Assess** — identify the highest-leverage gap
3. **Execute** — make one focused change
4. **Verify** — exercise the changed behavior and run relevant static checks;
   use a focused test when needed, following `CLAUDE.md` §5
5. **Commit** — commit with a clear message
6. **Track** — record progress in `/tmp/refactor-CyClaw.md`
7. **Loop** — repeat until all stopping criteria are met

These loops are explicit-invocation workflows. The full-suite measurements in
`tests-refactor` and `logging-refactor` belong to those requested workflows,
not routine verification for unrelated changes.

## Folder Structure

```
.claude/
├── README.md              ← this file
├── settings.json          ← project permissions and hooks
├── skills/                ← project-specific skills (see CLAUDE.md for the full list)
│   ├── invariant-guard/   ← SKILL.md + check_invariants.py + verify.sh
│   ├── architecture-refactor/
│   ├── doc-sync/
│   └── …                  ← many more (agent, sandbox, optimize, …)
├── commands/              ← thin /name wrappers pointing at skills/, plus five
│                            standalone commands with no skill twin
├── hooks/                 ← session-start-sync-check.sh, fable-protocol-loader.sh and
│                            session-start-venv.sh, all SessionStart hooks in settings.json
└── rules/                 ← project-specific rules (PROJECT_RULES.md; plain
                              Markdown, no frontmatter, applies repo-wide)
```

Issue #1351 (2026-09-16) deleted `patterns/`, `utility-prompts/`, `tools/`,
`memory/` (superseded by `docs/memories/`), and `ponytail-marketplace.json`
(with the `ponytail` plugin entry in `settings.json`); do not re-create them.

## Skill Caching Policy

Claude Code resolves skills from three scopes: **project** (`<repo>/.claude/skills/`,
version-controlled, shared with every collaborator on this repo), **user**
(`~/.claude/skills/`, personal, follows the operator across every repo), and
**plugin/built-in** (document/artifact tooling, review helpers, and config
utilities shipped by Claude Code itself or by installed marketplaces).

Only **project** skills are vendored: one folder per `SKILL.md` name under
`.claude/skills/`, indexed in `CLAUDE.md` §9. Copying user/built-in skills
adds unused material, drifts from upstream, and can expose personal context.
Vendor one only when a documented CyClaw workflow needs it, then update the
inventory.

### Slash-command wrappers (`.claude/commands/`)

Every project skill in `.claude/skills/` also gets a thin
`.claude/commands/<name>.md` wrapper (frontmatter `description:` + an
"Invoke the `<name>` skill" body) so the skill is reliably reachable as
`/<name>` in any Claude Code client, including ones that surface commands
and skills separately. Wrappers are deliberately thin — the `SKILL.md` stays
the single source of truth and the wrapper only points at it, so the two
cannot drift apart in substance. Five commands are standalone by design and
have no skill folder (`/audit`, `/check-soul`, `/conversation-summary`,
`/run`, `/status`) — they are short inline procedures, not skills, so a
deletion pass that treats them as orphaned wrappers removes real commands
(this happened once under issue #1351; both were restored from `main`).

Verify the wrapper set still covers every skill with
`comm -23 <(ls .claude/skills | sort) <(ls .claude/commands | sed 's/\.md$//' | sort)`,
which must print nothing (a stray untracked `__pycache__` under a deleted
skill dir is a build artifact — `git clean -ndx .claude/skills` finds those;
delete, don't wrap them).

Rules that came out of issue #1351 and its follow-ups (2026-09-11 → 09-16;
the per-skill rationale is in `CLAUDE.md` §9):

- A wrapper that grows into a near-copy of its `SKILL.md` is drift; trim it
  back to a pointer.
- A skill that duplicates a built-in (the `general-purpose` subagent type) or
  is a slash-only chore/loop gets deleted or `disable-model-invocation: true`.
  Skills that act on live state unasked (`CyClaw-Optimize` opens PRs,
  `babysit-github-pr` starts a watch loop) are user-invoked only, as is
  `fable-protocol`, whose Sonnet-tier injection moved to
  `fable-protocol-loader.sh`.
- Auto-invocable descriptions stay under the ~600-char routing budget
  (`otel-hardening` and `verify-deps` were cut to size and keep their "use X
  instead" clauses). `dep-guard` and `verify-deps` remain two skills on
  purpose: merging them is an information-architecture decision, not a
  routing fix.
- Deleting a skill that a `settings.json` hook invokes means removing the
  hook, never resurrecting the skill (`memory-orchestrator`'s
  `PreCompact`/`SessionEnd` hooks went this way).

## settings.json — hooks and the rules behind them

`settings.json` registers exactly three hooks, all `SessionStart`, in this
order; every path resolves and is repo-relative so it survives any checkout
location. The file holds no personal data (no usernames, machine paths, or
emails) — keep it that way, it is shared with every collaborator.

Its permission configuration uses `defaultMode: default`, denies `Workflow`,
and asks before `Agent` calls. The repository's agent fan-out guidance lives in
`CLAUDE.md`'s Reference section; listing a skill here does not authorize its
side effects.

1. **`session-start-sync-check.sh`** (2026-09-04) — git identity and
   local↔remote divergence report; never resets, rebases, or pushes.
2. **`fable-protocol-loader.sh`** (2026-09-06, re-gated 2026-09-16) — injects
   `fable-protocol/SKILL.md` as `additionalContext` once per SessionStart
   (startup/resume/clear/compact), never per prompt, and only when the stdin
   model id contains `sonnet`; Opus, Haiku, Fable, and absent or unrecognized
   ids are skipped and reach the protocol only via `/fable-protocol`.
   SessionStart is the only hook event whose stdin carries `model`, and no
   event fires on a mid-session `/model` switch, so `CLAUDE.md` §10 tells the
   operator to run it by hand then. Exits 0 unconditionally, stdout JSON-only,
   diagnostics on stderr.
3. **`session-start-venv.sh`** (2026-10-05) — cloud-only
   (`CLAUDE_CODE_REMOTE=true`; a no-op on a laptop). Detaches
   `cyclaw-gotchas/driver.sh venv` so the Python 3.12 venv at
   `/root/.venv-cyclaw-312` builds while the session starts; a manual
   `driver.sh venv` waits on the same lock and then reports `venv ready`. The
   driver uses `uv` when on PATH (cold build 122 s vs 413 s with pip, measured
   2026-10-05) and pip otherwise. Log: `$TMPDIR/cyclaw-session-start-venv.log`.

**Why no hook ends in `|| true`.** From before 2026-08-22 until 2026-09-04 a
`UserPromptSubmit` hook pointed at a file deleted on `main`; its
`2>/dev/null || true` tail made it a silent no-op on every prompt for weeks.
The fix was to unwire it (a ~22KB per-prompt injection was the wrong cost
anyway — the loader above is the gated replacement), and every hook since
exits 0 on its own so nothing hides a failure. The same rule removed the
`PreCompact`/`SessionEnd` hooks orphaned by `memory-orchestrator`'s deletion
and the `python-coding-agent` persona loader (issue #1351).

**Historical remote-environment pitfall.** Earlier cloud sessions received
Windows-local `CLAUDE_CONFIG_DIR` and `CLAUDE_CODE_DEBUG_LOGS_DIR` values on
Linux. A Windows drive path is relative there and can create a literal `C:...`
directory containing session state. The tracked root `.gitignore` keeps its
`/C:*` guard, and the git security gate checks for session residue separately.
Those old observations do not establish the current remote environment.
If this recurs, inspect the active environment's variables and have the
operator remove platform-specific overrides from the shared environment;
do not commit personal paths or try to repair hosted settings through this
repository's `settings.json`.

## Key Conventions

- Skill folders match the `name:` in SKILL.md frontmatter (a mismatch makes
  audits keyed on either name miss the other — `CyClaw-Sandbox` had one until
  issue #1351). Most are `kebab-case`; two ship mixed-case by convention
  (`CyClaw-Optimize`, `CyClaw-Sandbox`).
- All SKILL.md files use YAML frontmatter: `name:`, `description:`
- Claude Code commits as the session runtime's identity (cloud:
  `Claude <noreply@anthropic.com>`; local: the operator's own git identity),
  never as `CyClaw Agent`, the former agentic loop's identity. The loop was
  removed on 2026-10-18, and its leftover identity module
  (`utils/agent_identity.py`) on 2026-10-23. The sync hook does not sign commits or guarantee
  GitHub's Verified status. See `CLAUDE.md` §10.
