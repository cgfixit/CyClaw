---
name: add-comment
description: Scan the codebase for lines or sections that lack comments and would confuse a newcomer, then add human-readable, ELI5-toned but technically accurate comments explaining WHY the code does what it does. Comment-only — never changes logic. Use when asked to improve code readability, add comments, explain confusing code, or make CyClaw friendlier for a newcomer to read.
disable-model-invocation: true
---

# Add Comment

**Persona:** You are the friendly senior engineer who annotates a codebase the
way you'd explain it out loud to someone new to the team — plain English,
accurate, a little warm, never condescending. You are not rewriting logic,
renaming things, or reformatting; you are adding a sentence or two above the
lines that would otherwise make a newcomer stop and go "wait, why does this
do that?" You leave everything that already reads clearly alone.

**Why this skill exists:** comment-only changes are the safest possible
category of polish: they cannot alter runtime behavior, cannot violate an
invariant, and are trivially reviewable. This skill formalizes that specific
kind of pass, in the same chunked, PR-per-concern spirit as
`/CyClaw-Optimize`, so a large "add comments everywhere" sweep doesn't turn
into one unreviewable diff.

**Style reference — read before writing a single comment:** the owner wants
this skill's tone to mirror the comment style in two of his personal repos.
Fetch a sample from each (WebFetch, or `add_repo` when available) and match
its voice, adjusted for the language at hand:

1. https://github.com/cgfixit/Pick-a-Politician/blob/master/main.py
2. https://github.com/cgfixit/Blackjack/blob/master/Blackjack/Blackjack/main.cpp

Owner's note: use those for styling only; be *more* detailed and technically
helpful than they are, especially on unclear, complex, or cross-file
functions. If neither sample can be fetched, say so in the PR body and fall
back to the generic shape in §"Comment style" below — approachable,
plain-English, ELI5-flavored, technically precise.

---

## Run

### Step 1 — Scope the pass

Pick a bounded target before scanning: one module, one directory (e.g.
`retrieval/`, `utils/`), or a short list of files named by the user. Do not
attempt "the whole repo" in one pass — CyClaw is a real-sized codebase and an
unbounded pass produces an unreviewable diff. If the user didn't name a scope,
propose one (start with the module with the most complexity per the
`CyClaw-Optimize` bootstrap's largest-file list, or the file the user was just
looking at) and confirm before proceeding.

**Files that need extra care or are off-limits — check this before scanning
a file:**
- `data/personality/soul.md` — **never touch.** Soul mutation requires a
  human `reason` string via `PersonalityManager` (Invariant I5); a skill has
  no standing to invoke that gate. Comments are not exempt — don't touch this
  file at all.
- `graph.py` node/edge wiring, `gate.py` auth logic, `utils/sanitizer.py`
  `banned_patterns`/regex logic — these encode five of the six invariants
  (I1–I4, I6) and the sanitizer contract (§3/§4 of `CLAUDE.md`). Comments
  *may* be added here, but only with extra care: read `INVARIANTS.md` first,
  never let a comment imply a routing/gating behavior that isn't exactly what
  the code does (a wrong comment here is worse than no comment — it misleads
  the next security reviewer), and run `/invariant-guard` after editing.
- Auto-generated files, vendored/third-party code, and anything under
  `data/`, `index/`, `.venv/` — skip entirely; comments there either get
  overwritten or aren't yours to annotate.
- `config.yaml` — comments here already carry the repo's "why, with PR
  reference" convention (`CLAUDE.md` §5); match that existing density rather
  than adding an ELI5 pass on top of it.

### Step 2 — Identify genuinely under-commented, confusing lines

Within scope, look for the specific pattern CLAUDE.md itself calls out:
non-obvious behavior with no explanation. Concrete triggers, not a general
"more comments are better" heuristic:

- A regex, magic number, or config-derived constant used without explanation
  of what it means or why that value (e.g. an RRF score threshold, a retry
  count, a cache size).
- A branch or early-return whose *reason* isn't obvious from the code alone
  (e.g. why a particular error is swallowed, why an operation is skipped
  under some condition).
- A workaround for a library quirk, a CVE, or a Windows/POSIX difference —
  these are exactly the "why, with PR reference" comments CLAUDE.md already
  asks for elsewhere in the repo; extend the same practice, don't invent a
  new one.
- Non-obvious ordering dependencies (e.g. why one setup step must run before
  another) — CyClaw has several of these already commented (telemetry kill
  before heavy imports); look for uncommented ones with the same shape.
- A function whose name/signature doesn't convey what tricky thing it does
  internally.

**Do NOT touch:**
- Any line/block that already has an adequate comment, even if you'd phrase
  it differently — CLAUDE.md's density-matching rule means "different" is
  not "better" here.
- Self-explanatory code (a getter, a simple loop, a well-named variable
  assignment) — commenting the obvious is noise, not readability.
- Anything that would require adding a `TODO`/`FIXME` — CyClaw has none by
  policy (`CLAUDE.md` §5 Code); if a line needs a TODO to explain
  it honestly, that's a code-quality finding to report, not something to
  comment around.

### Step 3 — Comment style

Each comment should read like a short, friendly walkthrough — the kind of
thing you'd say to a new teammate pointing at their screen — while staying
exactly technically correct. Two to three sentences at most; match the
surrounding file's existing comment density rather than out-writing it.

Generic shape (calibrate against the two style samples above):

```python
# Why this exists: RRF scores live on a tiny scale — the best possible fused
# score is 2/60 ≈ 0.033 (rank 0 in both legs), nothing like a cosine 0.8.
# This floor only decides the keyword-only degrade (no cosine on any hit);
# hybrid queries are gated by min_semantic_score instead. Don't "fix" it
# upward toward a cosine-looking number: above ~0.033 nothing can pass.
if best_rrf < config["retrieval"]["min_score"]:
```

```python
# (From a sibling project, kept for tone.) The first poll for a brand-new
# wallet has nothing to compare against yet, so we record what's there now
# as the starting point ("priming") instead of replaying its whole history
# as if it were live trades.
if wallet not in self._primed_wallets:
```

Explain WHY, never WHAT — the code already says what it does. Avoid
restating the line in prose ("this increments i by one"). Avoid hedging
language that undersells confidence in something the code plainly does
("this probably…", "I think…") — if genuinely unsure why a line exists, say
so explicitly and flag it for the user rather than guessing.

### Step 4 — Apply in a chunked, reviewable way

Mirror `/CyClaw-Optimize`'s chunking discipline: group by module/concern, one
small-to-medium PR per chunk, never one repo-wide diff. For each chunk:

1. Add the comments — comment lines only; zero changes to executable code,
   whitespace-only reflow, or import order. If a comment genuinely needs
   code nearby to move (rare — e.g. splitting a dense one-liner so a comment
   has somewhere to attach), treat that as a separate, explicitly-flagged
   change and get confirmation first; it's no longer a pure comment change.
2. Run the verify step below before committing.
3. Commit with a `[docs] - ...` subject naming the module (e.g.
   `[docs] - Add ELI5 comments to retrieval score fusion and cache logic`);
   the tracked `commit-msg` hook refuses `docs(...)`-style subjects.
4. Push to a `claude/add-comment-<topic>` branch and open a **draft** PR
   whose body states: what module, why (readability for newcomers), and
   confirms zero logic changes (cite the diff — comment lines and blank
   lines only).

### Step 5 — Verify nothing changed but comments

Comment-only changes are the lowest-risk category that exists here, but
"lowest risk" is not "zero risk" — a malformed comment (e.g. an unterminated
triple-quote used as a comment, a stray `#` that breaks an f-string) can
break syntax. Prove it didn't:

```bash
ruff check --select E,F,I,B,C4,UP,S --ignore E501 <touched files>
python3 -c "import <touched.module>"          # a stray quote breaks here, not in CI
python3 .claude/skills/invariant-guard/check_invariants.py
```

Per CLAUDE.md §5, let GitHub Actions run the suite on the pushed draft; a
comment-only diff needs no local `pytest tests/`.

If the chunk touched any of the extra-care files from Step 1, also read the
diff by hand and confirm no comment asserts something the code doesn't
actually do — a confidently wrong comment in `graph.py` or `utils/sanitizer.py`
is worse than the silence it replaced.

---

## Guardrails

- **Comment-only, always.** This skill never changes control flow, values,
  formatting of code, or imports. If a "better comment" seems to require a
  code change, stop and flag it as a separate finding — don't fold it in.
- **Never touch `data/personality/soul.md`, ever, comments included** — soul
  mutation is gated behind a human `reason` string (Invariant I5); this skill
  has no standing to invoke that gate and soul.md isn't a place for casual
  annotation regardless.
- **Never alter `graph.py` edges, `gate.py` auth logic, or
  `utils/sanitizer.py` `banned_patterns`/regex bodies** while "just adding a
  comment" — these are five of CyClaw's six invariants (I1–I4, I6) plus the
  sanitizer contract. Comments *near* this code are fine with the extra care
  described in Step 1/Step 5; the code itself does not move.
- **No TODO/FIXME comments** — CyClaw has none by policy (`CLAUDE.md` §5);
  don't introduce the first one under cover of this skill.
- **"Why, with PR reference" density** — match the surrounding file's
  existing comment style and density (`CLAUDE.md` §5 Code conventions); don't
  out-comment a terse file or under-comment a dense one.
- **One concern per PR, draft PRs only, never push to `main`** — same rule as
  every other skill in this repo. Branch `claude/add-comment-<topic>`.
- **Don't touch already-well-commented code** — if in doubt whether an
  existing comment is "adequate," leave it; this skill adds coverage, it
  doesn't relitigate existing prose.

## Gotchas

- **A malformed comment can break syntax.** Always run `ruff check` and
  import the touched module after a comment pass, not just a visual diff
  review — a stray quote or an accidentally-uncommented line is an easy
  silent break.
- **Big diffs should be chunked, exactly like `/CyClaw-Optimize`.** Resist
  the temptation to sweep the whole repo in one PR because "it's just
  comments" — reviewability doesn't scale with line count being safe.
- **Don't comment auto-generated files or vendored/third-party code** —
  `data/`, `index/`, anything under a vendored path. It'll either be
  overwritten or isn't yours to annotate.
- **A confidently wrong "why" comment is worse than no comment**, especially
  near the six invariants — if you're not sure why a line exists, say that
  explicitly in the PR body instead of inventing a plausible-sounding reason.
- **This skill is fundamentally an LLM-judgment task, not a deterministic
  checker** — unlike `invariant-guard` or `doc-sync`, there is no
  companion script that mechanically finds "under-commented" lines (what
  counts as confusing is a judgment call). Don't try to force a rigid
  grep-based heuristic to replace Step 2's read-the-code judgment; a script
  here would either over-fire on trivial lines or miss the genuinely
  confusing ones.
