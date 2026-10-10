"""Render the draft-PR title check and body for a published real-repo run.

``_publish_record`` in ``agentic/cli.py`` used to open its pull request with a
one-line body, which the blocking ``pr-template-check.yml`` job (and its local
twin ``scripts/check-pr-template.sh``) rejects: CyClaw requires a complete fill
of ``.github/PULL_REQUEST_TEMPLATE.md``. So every PR the loop opened was red on
arrival. This module builds a template-complete body from the persisted
``RealRepoRunRecord`` alone, as a pure function: no clone, no network, no
model call, and the clock is a parameter.

What the body may contain is exactly what the record already stores and the
run/status commands already print: the operator's ``--instruction`` (scanned
for injection shapes before the run), the operator's check names, the fixed
gate tokens each iteration's decision produced, the changed paths, and digests.
It never contains model-written prose. The title is ``record.commit_message``,
a caller-supplied fixed string (``run_real_repo_loop``'s docstring), so it is
validated here, never rewritten.

Every interpolated value is escaped so it cannot forge structure the checker
reads: a line starting with ``#`` (a fake ``## ELI5``), a run of three
backticks or an HTML comment (both stripped by the checker before it looks for
headings), or a trailing ``Last updated:`` line.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from agentic.real_repo_run_store import RealRepoRunRecord

# Same prefixes and exemptions as the tracked commit-msg hook and
# scripts/check-pr-template.sh's `title` rule (CLAUDE.md section 5).
TITLE_PREFIXES = (
    "invariant",
    "governance",
    "fsconnect",
    "agentic",
    "rag",
    "harness",
    "security",
    "docs",
    "infra",
    "fix",
    "feat",
)
_TITLE_RE = re.compile(r"^\[(" + "|".join(TITLE_PREFIXES) + r")\] - \S")
_TITLE_EXEMPT_RE = re.compile(r"^(Merge |Revert |fixup! |squash! |Amend! )|^(chore|build|ci)\(deps\)")

# Long enough for any real instruction, short enough that a pasted ticket
# cannot turn the PR body into a wall of text.
MAX_INSTRUCTION_CHARS = 2000
# Characters that can start or close Markdown structure inside a line.
_MD_SPECIAL_RE = re.compile(r"([\\`*_\[\]<>#|!~])")


def pr_title_problem(title: str | None) -> str | None:
    """Return why ``title`` fails the ``[prefix] - Sentence`` rule, or None when it passes."""
    if not title or not title.strip():
        return "commit_message is empty"
    if "\n" in title or "\r" in title:
        return "commit_message must be a single line to serve as a PR title"
    if _TITLE_EXEMPT_RE.match(title) or _TITLE_RE.match(title):
        return None
    return f"commit_message must read `[prefix] - Short sentence` with prefix one of {', '.join(TITLE_PREFIXES)}"


def _md_inline(text: object) -> str:
    """Escape ``text`` for one line of Markdown: no line breaks, no live markup.

    ``str()`` first: a record written before check names were type-checked can
    hold a non-string. A zero-width space after ``@`` keeps a model-chosen path
    or pasted text from @-mentioning, and so notifying, a GitHub user or team.
    """
    flat = " ".join(str(text).split())
    return _MD_SPECIAL_RE.sub(r"\\\1", flat).replace("@", "@\u200b")


def _quote_block(text: str, limit: int) -> list[str]:
    """Render operator text as an escaped blockquote, truncated at ``limit`` chars."""
    clipped = text[:limit]
    lines = [f"> {_md_inline(line)}" if line.strip() else ">" for line in clipped.splitlines()] or ["> (empty)"]
    if len(text) > limit:
        lines.append(f"> ... (truncated at {limit} characters; the full text is in the run record)")
    return lines


def _us_eastern(now_utc: datetime) -> tuple[datetime, str]:
    """US Eastern wall time for ``now_utc`` without needing tz data on disk.

    ``zoneinfo`` has no database on a stock Windows runtime (``tzdata`` is
    only in the test lock), so the 2007 US rule is applied directly: daylight
    time from 02:00 local on the second Sunday of March to 02:00 local on the
    first Sunday of November.
    """
    year = now_utc.year

    def nth_sunday(month: int, n: int) -> int:
        first = datetime(year, month, 1)
        return 1 + (6 - first.weekday()) % 7 + 7 * (n - 1)

    # 02:00 EST = 07:00 UTC; 02:00 EDT = 06:00 UTC.
    dst_start = datetime(year, 3, nth_sunday(3, 2), 7, tzinfo=UTC)
    dst_end = datetime(year, 11, nth_sunday(11, 1), 6, tzinfo=UTC)
    if dst_start <= now_utc < dst_end:
        return now_utc - timedelta(hours=4), "EDT"
    return now_utc - timedelta(hours=5), "EST"


def last_updated_stamp(now: datetime) -> str:
    """The template's required last line, ``Last updated: YYYY-MM-DD HH:MM ET``."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    eastern, _ = _us_eastern(now.astimezone(UTC))
    return f"Last updated: {eastern:%Y-%m-%d %H:%M} ET"


def _box(ticked: bool, label: str) -> str:
    return f"- [{'x' if ticked else ' '}] {label}"


def render_pr_body(
    record: RealRepoRunRecord,
    *,
    now: datetime,
    redact: Callable[[str], str],
    include_instruction: bool = False,
) -> str:
    """Build a complete ``.github/PULL_REQUEST_TEMPLATE.md`` fill for a pushed run.

    Pure: the same arguments always produce the same string. ``redact`` is
    required, not defaulted, because check names (and an opted-in
    instruction) are free operator text about to be published: the injection
    scan they passed does not remove secrets or PII, so the caller supplies the
    repository's redactor (``utils.logger.redact_sensitive``).

    The instruction is published as a SHA-256 by default, the same treatment
    ``plan_sha256`` gives the plan: it is often text pasted from a ticket or
    chat, and a regex redactor fails open on any secret shape it does not
    know. ``include_instruction`` (the CLI's ``--publish-instruction``) is the
    operator's explicit choice to quote the redacted text instead.
    """
    title_ok = pr_title_problem(record.commit_message) is None
    files = record.changed_files
    file_lines = [f"- {_md_inline(path)}" for path in files] or ["- (none recorded)"]
    check_lines = [f"- {_md_inline(redact(str(name)))}" for name in record.check_names] or [
        "- (check names not recorded on this run; it predates check_names)"
    ]
    outcome_lines = [
        f"- iteration {step}: {_md_inline(outcome)}" for step, outcome in enumerate(record.iteration_outcomes, 1)
    ] or [f"- {record.iterations} iteration(s); per-iteration outcomes not recorded on this run"]
    if not record.instruction:
        instruction = ["> (not recorded on this run; it predates the instruction field)"]
    elif include_instruction:
        instruction = _quote_block(redact(record.instruction), MAX_INSTRUCTION_CHARS)
    else:
        digest = hashlib.sha256(record.instruction.encode("utf-8")).hexdigest()
        instruction = [f"> SHA-256 {digest} (text withheld; the operator can publish it with --publish-instruction)"]
    provider = _md_inline(record.provider) if record.provider else "local model (LocalProposerClient)"
    branch = _md_inline(record.branch_name or "(none)")

    parts: list[str] = [
        "## Proposed changes",
        "Automated candidate from CyClaw's real-repo-run loop (`agentic/real_repo_loop.py`): "
        + "plan, patch, verify in a jailed clone, then a human approved the commit and its push.",
        "",
        f"- **Run id:** {_md_inline(record.run_id)}",
        f"- **Repository:** {_md_inline(record.repo)}",
        f"- **Branch:** {branch}",
        f"- **Driver:** {provider}",
        f"- **Plan SHA-256:** {_md_inline(record.plan_sha256 or 'none (unplanned run)')}",
        f"- **Acceptance digest:** {_md_inline(record.acceptance_digest or 'none recorded')}",
        f"- **Base HEAD:** {_md_inline(record.acceptance_base_head or 'none recorded')}",
        "",
        "**Operator instruction**",
        "",
        *instruction,
        "",
        "**Invariant / Governance impact:** not assessed by the loop. A reviewer must check the diff "
        + "against the six invariants (`CLAUDE.md` section 3) before merge, and run "
        + "`python3 .claude/skills/invariant-guard/check_invariants.py` if a core file changed.",
        "",
        "## Types of changes",
        "_The loop cannot classify its own change; the reviewer re-ticks these._",
        "",
        _box(False, "Bugfix (non-breaking change which fixes an issue)"),
        _box(False, "New feature (non-breaking change which adds functionality)"),
        _box(False, "Breaking change (fix or feature that would cause existing functionality to not work as expected)"),
        _box(False, "Documentation Update (if none of the other choices apply)"),
        _box(False, "Invariant / Governance refinement"),
        _box(True, "Other: automated real-repo-run candidate, unclassified until review"),
        "",
        "## Benefits / why",
        "The operator asked for the change quoted above; every check below passed on the accepted "
        + "iteration in a disposable copy before a human approved the commit.",
        "",
        "## Risks to monitor",
        "- The patch was written by a model. Passing checks proves only what those checks test.",
        "- Review the full diff, not just this summary: this body lists paths, not content.",
        "- A file written by a rejected earlier iteration stays in the commit when the accepted "
        + "iteration's checks depended on it (see `RealRepoLoopResult.changed_files`).",
        "",
        "## Checklist",
        _box(False, "I have read `docs/THREAT_MODEL.md`, `INVARIANTS.md` and `SECURITY.md`"),
        _box(False, "This change preserves all 6 security invariants and I6 module isolation"),
        _box(False, "Full sandbox validation has been run and passes with no regressions"),
        _box(False, "No new external network dependencies or mandatory online LLM assumptions were introduced"),
        _box(True, "Verification checks passed on the accepted iteration (listed in Further comments)"),
        _box(title_ok, "Commit messages follow the title prefix convention above"),
        "",
        "## Further comments",
        f"**Changed files ({len(files)})**",
        "",
        *file_lines,
        "",
        "**Verification checks (all passed on the accepted iteration)**",
        "",
        *check_lines,
        "",
        "**Iteration outcomes**",
        "",
        *outcome_lines,
        "",
        "## Suggested merge order of open PRs",
        "_No trial merge was run: the loop does not inspect other open PRs. "
        + "Run the template's trial-merge recipe against current `main` before merging._",
        "",
        f"**This PR** (branch {branch}) · Blocked ⛔  ",
        "Impact: automated candidate, unreviewed.  ",
        "Action: human review, then a trial merge against `main`.",
        "",
        "## ELI5",
        "A helper robot was asked to make the change quoted at the top. It wrote the files in a sealed "
        + "copy of the repo, ran the listed checks until they passed, and a person said yes to saving and "
        + "uploading it. Nobody has read the code yet: this PR is the place to do that.",
        "",
        last_updated_stamp(now),
    ]
    return "\n".join(parts) + "\n"
