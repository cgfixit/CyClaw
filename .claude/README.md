# `.claude/` — project skills and workflows

Quick reference for Claude Code assistance patterns in CyClaw.

## Skills

The skills directory holds many more skills than the handful below (operational,
refactor-loop, and agent skills). For the **authoritative, complete list**, see the
**§9 "Skills"** section of the root [`CLAUDE.md`](../CLAUDE.md) — kept in
sync there so a second list does not drift. The current tree has **23 project
skills and 28 slash commands**, including five standalone commands. A few common entry points:

These are Claude Code slash commands typed into the session, not shell
commands — the fence below is `text` on purpose, because pasting these into a
terminal only produces "No such file or directory".

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

All `*-refactor` skills follow the same seven-step cycle:

1. **Measure** — baseline the current state (tests, latency, log coverage)
2. **Assess** — identify the highest-leverage gap
3. **Execute** — make one focused change
4. **Test** — verify correctness via smoke test or pytest
5. **Commit** — commit with a clear message
6. **Track** — record progress in `/tmp/refactor-CyClaw.md`
7. **Loop** — repeat until all stopping criteria are met

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

This directory intentionally vendors only the **project** scope — every skill
in `CLAUDE.md` §9's tables lives under `.claude/skills/` here, one folder per
skill, named for the `name:` in its `SKILL.md` frontmatter. User-scope and
built-in skills are **not** copied in, for three concrete reasons:

1. **YAGNI / no current caller.** No CyClaw code path or documented workflow
   invokes them — they serve the operator across unrelated repos, not this
   project.
2. **Drift risk.** Built-in skills are maintained upstream by Claude Code
   itself; a vendored copy would silently diverge from the version other
   sessions actually run, defeating the point of "official" tooling.
3. **Scope leakage.** User-scope skills are tied to an operator's own identity
   and working style, not to CyClaw. Checking them into a shared repo would
   expose that context to everyone who clones it — out of scope for a project
   `.claude/` tree.

If a personal or built-in skill genuinely becomes load-bearing for CyClaw
(a documented workflow starts depending on it), add it to `.claude/skills/`
at that point and update `CLAUDE.md` §9 — not before.

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

**Remote-environment env-var misconfiguration (root cause of the stray
`C:\Users\...` directory).** The Claude Code remote execution environment for
this repo injects Windows-local values into Linux containers:

- `CLAUDE_CONFIG_DIR=C:\Users\<user>\.claude\` — on Linux this is a
  *relative* path, so Claude Code materializes a literal `C:\Users\...`
  directory at the repo root and uses it as live config storage. Observed
  breakage in-session: session-start hook output, task tracking (lock file
  `ENOENT`), and skill sync all landed in the stray directory.
- `CLAUDE_CODE_DEBUG_LOGS_DIR=C:\Users\<you>\.claude\debug` — an
  unsubstituted template; invalid on every OS (`<`/`>` are illegal in
  Windows paths too).

Repo-side mitigation (this commit): a root `.gitignore` guard (`/C:*`) so the
stray directory — which contains live session state — can never be staged by
a broad `git add`. Operator-side fix (cannot be done from the repo): edit the
environment's variables at claude.ai → Code → environment settings and
remove both entries. Neither belongs in a shared remote environment —
`C:\Users\<user>\.claude\` is already Claude Code's *default* config
location on Windows, so the variable adds nothing there either; per-machine
overrides belong in that machine's own shell profile. `settings.json` cannot
fix this: `CLAUDE_CONFIG_DIR` is read at CLI startup before project settings
load, and pinning it in the repo would break every other machine.

**Verification follow-up (2026-08-11, fresh remote session).** The operator-side
fix above landed half-way, verified live from a new cloud container for this
repo:

- `CLAUDE_CONFIG_DIR` — **removed**. Session state (hook output, task
  tracking, skill sync) lands in the default config location again, no stray
  `C:\...` directory materializes anywhere on the container filesystem, and
  `git status` stays clean. The `/C:*` guard stays as defense-in-depth.
- `CLAUDE_CODE_DEBUG_LOGS_DIR` — **still injected**. The variable was edited
  (the `<you>` template now carries a real Windows username) instead of
  removed, so every Linux container still receives a Windows-local path — and
  a personal username — in its environment. No stray directory is currently
  produced by this one, but the removal instruction above still applies:
  claude.ai → Code → environment settings, delete the entry.

## Key Conventions

- Skill folders match the `name:` in SKILL.md frontmatter (a mismatch makes
  audits keyed on either name miss the other — `CyClaw-Sandbox` had one until
  issue #1351). Most are `kebab-case`; two ship mixed-case by convention
  (`CyClaw-Optimize`, `CyClaw-Sandbox`).
- All SKILL.md files use YAML frontmatter: `name:`, `description:`
- Refactor progress is tracked in `/tmp/refactor-CyClaw.md`
- Claude Code commits as the session runtime's identity (cloud:
  `Claude <noreply@anthropic.com>`, signed so GitHub shows it Verified; local:
  the operator's own git identity), never as `CyClaw Agent`, which belongs to
  CyClaw's own agentic loop (`utils/agent_identity.py`). See `CLAUDE.md` §10.
