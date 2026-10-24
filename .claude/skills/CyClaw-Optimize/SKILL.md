---
name: CyClaw-Optimize
description: Methodically scan the CyClaw main branch for code, CI, security, financial-risk, and maintainability optimization opportunities, then open a small set of focused, reviewable pull requests only when each chunk earns its keep (not a fixed PR quota). Use when asked to optimize CyClaw, find competitive/trade-bot advantages, harden CI, audit for risk, propose improvements, or open optimization PRs against main. Not auto-invocable — it opens PRs against main, so it only runs when explicitly asked.
disable-model-invocation: true
---

# CyClaw-Optimize

**Persona:** You are a modern AI engineer specializing in Python and extremely
familiar with the CyClaw architecture — FastAPI RAG gateway (`gate.py`),
LangGraph 12-node security topology (`graph.py`), ChromaDB + BM25 hybrid
retrieval, local LLM via Ollama with a triple-gated Grok (xAI) and/or Claude
fallback, the MCP hybrid server, the out-of-band `agentic/` connectors
(`fsconnect/`, the filesystem bridge, and `netconnect/`, the passive LAN
inventory; the GitHub layer, the real-repo loop and `sqlconnect/` were
removed 2026-10-18), and the out-of-band `sync/`
Dropbox pipeline — all of which ship platform launchers for **macOS** (primary
target) and **Windows** (close secondary) under `macos/` and `powershell/`.
You read code for leverage: performance, security, financial risk / oversight
in assumptions, auditability, and maintainability.

**What this skill does:** drives a time-boxed scan of the **main** branch,
groups findings into a **small set of reviewable PR-sized chunks** (about 1–4
when several independent fixes earn their keep — **a guideline, not a quota**;
do not invent low-value PRs to hit a number), and opens one focused pull request
per kept chunk on a branch cut from the **topology base** Step 3.5 assigns —
never committing to `main` directly. A human decides when to merge/close.
Prefer merging this session's drafts **lowest PR number → highest**, parent
before child when stacked.

**How it's driven:** the deterministic setup + scan-seed is a committed
harness, `bootstrap.sh`. The scan itself is a read-only subagent. PR dedup and
PR creation are GitHub MCP tool calls. Paths below are relative to the repo
root (the `<unit>` dir).

---

## Run (agent path)

### Step 0 — Bootstrap (harness)

Run the harness. It reports the git identity commits will carry (the session runtime's), fetches
`origin/main`, positions you on a fresh working branch cut from `origin/main`
(creating it if you pass a name), and prints a repo inventory that seeds the
scan:

```bash
bash .claude/skills/CyClaw-Optimize/bootstrap.sh "claude/cyclaw-optimize-<topic>"
```

Use the driver-matched prefix from the PR template (`claude/` for Claude
Code, `codex/`, `kimi/`, …; `agent/` only when the driver is unknown). Omit
the branch argument to run read-only against the current branch. The script
never force-resets an existing branch that already has commits.

### Step 1 — Time-boxed scan (subagent, ~4 minutes)

Dispatch **one read-only `Explore` subagent** to scan for ~4 minutes. Do not
let it edit anything. Give it the persona and the concrete areas to sweep.
This is the prompt that worked this session (adapt the topic, keep the
structure):

> You are a modern AI engineer specializing in Python and deeply familiar with
> the CyClaw architecture. Repo root is the CWD. Spend ~4 minutes on a
> READ-ONLY scan for concrete optimization / fix opportunities suitable for
> small-to-medium focused PRs. Sweep: `.github/workflows/*.yml` (caching,
> action SHA pinning, `cancel-in-progress`, matrix gaps — **nothing needing a
> license/secret/key**); `tests/` (coverage gaps, logic errors, brittle
> fixtures, missing assertions); `agentic/` and `sync/` (bugs, inefficient
> loops, redundant logic, error-handling and financial/oversight-assumption
> risk); `agentic/fsconnect/` and `agentic/netconnect/`,
> with **macOS as the primary target** (Darwin-specific path handling in
> `pathsafe.py`, `macos/*.sh` installer/launcher scripts) and **Windows as a
> close secondary** (`powershell/*.ps1` scripts, `pathsafe.py`'s `_win_*`
> helpers) — Windows read/list/stat authority is covered natively
> (`tests/test_fsconnect_pathsafe_windows.py`, a blocking CI step); only
> Windows *writes* remain a tracked deferral
> (`docs/work/FSCONNECT_SQL_ROADMAP.md`, "Windows write authority" under "Deferred proposals");
> `llm/client.py` + `graph.py` (outdated Grok/xAI model names &
> endpoints, retry/timeout, performance); `config.yaml` (risky defaults);
> `pyproject.toml` / `constraints.txt` / `locks/*.txt` (loose/outdated
> pins, missing imports); readability/auditability anywhere. Return 6–10
> DISTINCT findings, each with: title, file path(s) + line numbers, one-line
> description, category, effort (small/medium). End with a suggested grouping
> into a small set of PR-sized chunks (only as many as earn a PR — not a fixed five). Cite real code — do not invent.

You may keep reading code after the 4 minutes; the time-box only governs the
initial sweep.

### Step 2 — Dedup against open PRs (MCP) — do this BEFORE picking focus areas

List open PRs and drop any candidate area already covered by an open PR. Also
explicitly skip the known-stale "null allowed origins in `config.yaml`" idea —
it is out of scope.

```text
mcp__github__list_pull_requests(owner="cgfixit", repo="CyClaw", state="open")
```

> Gotcha (verified): this call returns a very large payload. Parse it down to
> `number` + `title` only — e.g. read the saved tool-result file with a small
> `python3 -c "import json; ..."` over `number`/`title` — rather than dumping
> it into context.

### Step 3 — Select focus areas and announce them

From the deduped findings, choose only the PR-sized chunks that clearly earn
their keep. **Count is a guideline, not a target:** about 1–4 focused PRs is
typical when several independent fixes are real; **one solid PR is better than
four thin ones**, and zero is correct when nothing remains after dedup. Never
split or invent work just to fill a slot. Each chunk = **1–2 major concepts OR
3–5 minor tasks**, cross-file/cross-concept where it adds value. State, in one
line each, which section of code each PR will touch and why (the leverage:
performance / security / financial-risk / auditability / maintainability).
Prefer chunks that are independently reviewable and easily restorable through
GitHub — subject to Step 3.5 when they share files.

### Step 3.5 — Plan branch topology for shared files (prevents merge-loss / conflicts)

Always START from `origin/main` (Step 0 / the bootstrap cuts the first branch
there — that is correct). The strategy below only changes **where you cut the
2nd-and-later branch when it edits a file an earlier chunk also edits.**

Before creating any branches, build a **file → chunks** map and find every file
touched by more than one chunk. The usual shared files: `.github/workflows/ci.yml`
(everyone appends to the `--cov` list; pytest auto-discovers test files),
`config.yaml`, `constraints.txt` / `pyproject.toml` / `locks/`, `CLAUDE.md`. For each
shared file pick ONE strategy:

- **(A) Consolidate** — put *all* edits to that shared file in a single chunk/PR
  (or a dedicated "CI wiring" PR). Best when the edits are small and related
  (e.g. each chunk only appends one line to the ci.yml test list). The other
  chunks then touch only their own new files and carry no ci.yml edit.
- **(B) Stack** — cut the later branch from the *earlier branch* instead of
  `origin/main`, so the later PR already contains the earlier's edit to the
  shared file. Set the later PR's **base to the earlier branch** on GitHub (not
  `main`). Stacked PRs must merge parent-first; rebase the child after the
  parent merges. Best when chunks are large and otherwise independent.

**Why it matters:** two branches cut from the same base that edit the **same or
adjacent lines** of a shared file produce a merge **conflict** — GitHub blocks
the merge button until a human resolves it, and a careless resolution can drop
one side's edit (the "lost changes" failure mode). Non-adjacent edits to the same
file 3-way-merge cleanly, but verify rather than trust luck.

**Verify before opening PRs** — for every pair of branches that share a file, do
a throwaway 3-way merge locally and confirm both edits survive with no conflict:

```bash
git checkout -B _trial origin/main
git merge --no-ff "origin/<branch-A>" && git merge --no-ff "origin/<branch-B>"
grep -q '<A-marker>' "<shared-file>" && grep -q '<B-marker>' "<shared-file>" && echo "both present"
grep -rc '<<<<<<<' "<shared-file>"           # must be 0
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"  # still valid
git checkout main && git branch -D _trial
```

The check is cheap; run it whenever ≥2 chunks touch one file rather than
assuming the regions are disjoint.

**Session merge order:** plan chunks so humans can merge this run's drafts from
**lowest PR number → highest**, with stack **parents always before children**.
That order is the universal default for the rest of this skill (Step 4+), whether
a given PR's GitHub `base` is `main` or a parent branch.

### Step 4 — One focused PR per chunk

Work chunks in **planned merge order** (see Step 3.5): parent / lower-order
first, then children. For each chunk, use its **topology base** — not a blanket
assumption that every branch starts at `main`:

| Topology (Step 3.5) | Cut branch from | GitHub PR `base` |
|---|---|---|
| Independent (no shared-file dependency on another chunk in this run) | `origin/main` | `main` |
| Stacked on an earlier chunk | that earlier chunk's branch | that earlier branch (not `main`) until the parent merges |
| Consolidated | whatever branch owns the shared-file edits | same as that branch's topology |

1. Make the focused change(s). Keep the diff minimal and on-topic; avoid
   touching unrelated files (CLAUDE.md operating contract).
2. Verify (see **Verify** below).
3. Commit with a hook-compliant subject, then push with upstream tracking:

   ```bash
   git add <files of this chunk>
   git commit -m "[fix] - <what changed and why>"     # [prefix] - sentence; the commit-msg hook refuses `type:` subjects
   git push -u origin "<branch-name>"
   ```

   On network failure only, retry up to 4× with exponential backoff
   (2s, 4s, 8s, 16s).
4. Open a **draft** PR via MCP with a `[prefix] - sentence` title and a body
   that follows `.github/PULL_REQUEST_TEMPLATE.md` **verbatim** — copy its
   actual section headers, don't paraphrase or substitute a lighter-weight
   structure. `.github/workflows/pr-template-check.yml` is a BLOCKING CI check:
   it requires all eight sections (`## Proposed changes`, `## Types of
   changes`, `## Benefits / why`, `## Risks to monitor`, `## Checklist`,
   `## Further comments`, `## Suggested merge order of open PRs` with a
   "trial merge" note, and `## ELI5` as the **last heading**), then
   `Last updated: YYYY-MM-DD HH:MM ET` as the body's last non-blank line
   (put any "Generated with" attribution above it), the `[prefix] - ` title,
   the branch allowlist, and the word "invariant" somewhere in the body when a
   core file is touched. State the topology (independent / stacked-on
   `<parent-branch or #N>` / consolidated) in each PR's `Impact:` line.

   ```text
   mcp__github__create_pull_request(
     owner="cgfixit", repo="CyClaw",
     base="main",                      # stacked child: base="<parent-branch-name>", not main
     head="<branch-name>", draft=true,
     title="[fix] - <concise sentence>",
     body="<the template's eight sections, filled in; merge-order entry 'Safe ✅ / independent' or 'Dirty ⚠️ / stacked on <parent>'; ELI5 last; stamp line last>")
   ```

   Then `subscribe_pr_activity` on the new PR and drive it to green
   (CLAUDE.md §4 Git & PR).

**Merge order for this skill run:** after drafts exist, prefer merging **lowest
PR number → highest** among the PRs this session opened, except where Step 3.5
stacking requires **parent before child**. Write the order into every open PR
using the template's `## Suggested merge order of open PRs` format (3 short
lines per PR: status, impact, action), and re-run the trial merges whenever
`main` moves.

Edge cases (each one was hit or reproduced in this repo, or is plain git):

| Situation | What to do |
|---|---|
| Stacked child, parent **squash**-merged | The child still carries the parent's original commits, so merging it conflicts (reproduced: #1612 onto a squashed #1608 conflicts in `utils/endpoint_trust.py`). Either merge the parent with a merge commit, or `git rebase --onto origin/main <parent-tip-sha> <child>` and `--force-with-lease` (own branch, owner's OK). Never merge `main` into the child as a first resort: it hides the duplicate. |
| Stacked child shows fewer checks | A PR whose base is not `main` skipped CodeQL, Semgrep, Trivy, osv-scanner, secrets and the template check (#1612: 47 checks vs 58-76). Retarget to `main` and wait for the full set before calling it green. |
| PR is still a draft | Drafts cannot be merged. Mark ready for review first; that event re-runs the template check. |
| `main` moved since the trial merge | "Safe" has a shelf life. Re-run the trial merge right before merging, and update the SHA in the note. |
| Dirty PR | Rebase locally, re-run the checks, push. GitHub's "Update branch" adds a merge commit to the PR branch and diverges from any local copy. |
| Force-push | Only on a branch only you push to, only with `--force-with-lease`, only with the owner's OK. It resets review state and the bots' reviewed head. |
| Two PRs edit one shared file (`ci.yml`, `config.yaml`, `CLAUDE.md`, manifests) | Trial-merge both orders before opening either. Lockfiles and generated files are regenerated, never hand-merged. |
| Diff is far larger than the change | Line endings. Compare `git diff --numstat` with `git diff --numstat --ignore-cr-at-eol`; if they differ, restore the original endings (found in #1610: 742/739 lines for a 3-line change; the repo has CRLF files and the owner works on Windows). |
| Squash-merge | The squash message is the permanent record. Edit it; do not leave the concatenated WIP titles. |

If, after scanning, no clear optimization opportunities remain (all covered by
open PRs or out of scope), **confirm that briefly and stop** — do not
manufacture low-value PRs.

---

## Verify (per PR, before pushing)

Follow CLAUDE.md §5's verification order: run the changed code directly,
then lint and the `.claude/skills/*/check_*.py` checkers, then let GitHub
Actions run the suites on the pushed draft. One targeted test file only when
nothing else exercises the path:

```bash
ruff check --select E,F,I,B,C4,UP,S --ignore E501 <touched files>
python3 .claude/skills/invariant-guard/check_invariants.py        # any core-file change
GROK_API_KEY=dummy pytest tests/test_<area>.py -q --tb=short       # at most one file
```

A fresh cloud container has **no** Python deps in any interpreter; the
SessionStart hook starts `driver.sh venv` (`cyclaw-gotchas`) in the
background, and a manual `bash .claude/skills/cyclaw-gotchas/driver.sh venv`
waits for it. CI-/docs-/workflow-only PRs need no local pytest at all.

Optionally run `/code-review` on the diff before opening the PR.

---

## Branch Permissions (pre-granted for this skill)

When **CyClaw-Optimize** is invoked, the user pre-authorises creation and push
of per-chunk branches named `<driver-prefix>/cyclaw-optimize-<topic>`
(`claude/` for Claude Code; the PR template's driver table), each cut from the **topology base**
Step 3.5 assigned (session start / first independent chunk from `origin/main`;
stacked children from their parent branch). Do **not** stop and ask for
permission to push these branches — proceed directly. This applies even when
the session was started on a different designated branch (e.g. `agent/<name>`
from a session-start hook). Each chunk gets its own branch + draft PR; the
designated session branch is used only for the skill file update commit (if
any), never for chunk changes.

---

## Guardrails (CyClaw invariants — do not violate)

- Branch → draft PR → human merges; never commit to `main` (CLAUDE.md §4
  Git & PR, §5).
- Do not re-open an area already covered by an open PR; skip the
  null-allowed-origins `config.yaml` item.
- The six invariants (CLAUDE.md §3) are never an optimization target: no
  graph-edge or gate is weakened to "optimize", and `soul.md` is governed (I5).
- Workflow enhancements must need **no license, secret, or key**.

---

## Gotchas

- **Use the real PR template, not a shorthand.** `.github/PULL_REQUEST_TEMPLATE.md`
  is the source of truth for PR body structure; `.github/workflows/pr-template-check.yml`
  enforces all eight headings, the stamp line, and the title format on every
  PR (blocking). A PR opened with an invented format (`## What` / `## Why` /
  `## Risk` and nothing else) fails this check immediately even when the
  content is good. See Step 4.
- **MCP PR-list payload is huge** — always reduce to `number`/`title` before
  reading (see Step 2). Reading it raw blows the token budget.
- **No deps in a fresh container** — the venv is built by the SessionStart
  hook / `driver.sh venv` (see Verify).
- **Largest-file ≠ worst-file.** `bootstrap.sh` lists the biggest Python
  files (`utils/_unicode_confusables.py` is a data table; `gate.py` and
  `agentic/fsconnect/pathsafe.py` follow) as refactor
  candidates, but size alone isn't a defect — confirm a real issue
  before proposing a refactor PR.
- **Stay in scope per PR.** The whole point is reviewable, restorable chunks;
  resist bundling unrelated fixes because they're "right there."
- **The 4-minute box is for the initial sweep only** — keep reading code
  afterward to confirm each finding before it becomes a PR.
- **Shared-file PRs can collide.** Step 3.5 is not optional when ≥2 chunks
  edit one file: consolidate or stack, trial-merge the pair before opening,
  and after a parent lands refresh open children before merging the next.
- **A red `main` poisons every PR cut from it** (CLAUDE.md §4 Git & PR). Land
  the root-cause fix first, then refresh the rest; diagnose a child PR's red
  CI against `main`'s own state before blaming the diff.
- **Don't "fix" `EMBED_DEVICE`.** `retrieval/embeddings.py` hardcodes
  `EMBED_DEVICE = "cpu"` on purpose — sentence-transformers auto-selects `mps`
  on Apple Silicon otherwise, which caused a real ranking regression (PR
  #734). A finding proposing GPU/`mps` auto-detection here is wrong.
- **Windows `pathsafe` write support is a known, tracked deferral, not a fresh
  finding.** Read/list/stat authority already runs natively on the Windows CI
  leg (`tests/test_fsconnect_pathsafe_windows.py`); only writes remain
  deferred ("Windows write authority" under "Deferred proposals" in `docs/work/FSCONNECT_SQL_ROADMAP.md`).

---

## Example output (shape only — every concrete item below has since landed)

The Step-1 subagent returns grounded findings and a grouping into PR-sized
chunks, each as *title · file:line · one-line description · category ·
effort*. A past run grouped them as: coverage wiring (`ci.yml` `--cov`
list), CI action SHA-pinning + `cancel-in-progress`, LLM-client retry
backoff, and audit-detail redaction. **Count is not a quota** — keep only
chunks that still look high-leverage after dedup; docs-only follow-ups ride
with a related chunk rather than opening a PR of their own.

## Notes

- The operative test for a chunk is "does this fix a real defect or polish what ships?" New capabilities need explicit user justification first (`CLAUDE.md` §6/§7).
- Never push directly to `main`; never force-push without sign-off.
- Re-run `python3 .claude/skills/invariant-guard/check_invariants.py` before opening any PR that touches core files.
