"""Parity contract: the local PR checker and the CI PR checker apply the same rules.

``scripts/check-pr-template.sh`` (the pre-flight a human or coding agent runs
before opening a PR) and ``.github/workflows/pr-template-check.yml`` (the
blocking CI check) are two implementations of one rule set, each failure
tagged with the same ``[key]``. This test runs both on shared fixtures and
asserts identical key sets, and asserts every body heading of
``.github/PULL_REQUEST_TEMPLATE.md`` is required by both, so the "complete
template" rule cannot silently fall behind the template.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check-pr-template.sh"
WORKFLOW = REPO / ".github" / "workflows" / "pr-template-check.yml"
TEMPLATE = REPO / ".github" / "PULL_REQUEST_TEMPLATE.md"

# Template sections that instruct the author (branch name, title) rather than
# being sections of the PR body; the checkers enforce them as the branch and
# title rules instead.
_INSTRUCTION_HEADINGS = {"Branch naming (required for agent-opened PRs)", "Title"}

_KEY_LINE = re.compile(r"^\s*- \[([a-z0-9-]+)\]", re.MULTILINE)

_BASH = shutil.which("bash") or ""
_NODE = shutil.which("node") or ""

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not (_BASH and _NODE and shutil.which("perl")),
    reason="needs bash, perl and node (POSIX legs only)",
)

GOOD_BODY = """## Proposed changes
Fix the thing. No invariant changes.

## Types of changes
- [x] Bugfix (non-breaking change which fixes an issue)
- [ ] New feature

## Benefits / why
- Fewer bugs.

## Risks to monitor
- None new.

## Checklist
- [x] Commit messages follow the title prefix convention above
- [ ] Full sandbox validation has been run

## Further comments
Ran ruff.

```markdown
## ELI5
an example inside a fence does not count
```

## Suggested merge order of open PRs
_Trial merges verified against main @ abc1234 on 2026-10-10._

**This PR** · Safe ✅

## ELI5
It fixes the thing.

Last updated: 2026-10-10 02:30 ET
"""

GOOD = {"body": GOOD_BODY, "title": "[fix] - Fix the thing", "branch": "claude/fix-thing", "files": ["utils/x.py"]}


def _case(**overrides: object) -> dict:
    case = dict(GOOD)
    case.update(overrides)
    return case


CASES: dict[str, tuple[dict, set[str]]] = {
    "complete": (GOOD, set()),
    "crlf": (_case(body=GOOD_BODY.replace("\n", "\r\n")), set()),
    "no-further-comments": (
        _case(body=GOOD_BODY.replace("## Further comments\nRan ruff.\n", "")),
        {"further-comments"},
    ),
    "unticked-boxes": (
        _case(body=GOOD_BODY.replace("- [x]", "- [ ]")),
        {"types-ticked", "checklist-ticked"},
    ),
    "eli5-not-last-and-placeholder-stamp": (
        _case(
            body=GOOD_BODY.replace("Last updated: 2026-10-10 02:30 ET", "## Notes\nLast updated: YYYY-MM-DD HH:MM ET")
        ),
        {"eli5-last", "stamp"},
    ),
    "stamp-not-last": (_case(body=GOOD_BODY + "\n🤖 footer\n"), {"stamp"}),
    "heading-only-in-fence": (
        _case(
            body=GOOD_BODY.replace(
                "## Suggested merge order of open PRs", "```\n## Suggested merge order of open PRs\n```"
            )
        ),
        {"merge-order"},
    ),
    "core-path-no-invariant": (
        _case(body=GOOD_BODY.replace(" No invariant changes.", ""), files=["graph.py"]),
        {"invariant"},
    ),
    "core-path-with-invariant": (_case(files=["config.yaml"]), set()),
    "bad-title-and-branch": (_case(title="fix the thing", branch="cc/sweet-goodall"), {"title", "branch"}),
    "title-without-space-dash": (_case(title="[fix]- Fix"), {"title"}),
    "exempt-title-and-bot-branch": (_case(title='Revert "[fix] - Fix the thing"', branch="dependabot/pip/x"), set()),
    "deps-title": (_case(title="chore(deps): bump x", branch="renovate/x"), set()),
    "tiny": (
        _case(body="tiny"),
        {
            "proposed-changes",
            "types",
            "benefits",
            "risks",
            "checklist",
            "further-comments",
            "merge-order",
            "eli5",
            "trial-merge",
            "stamp",
            "too-short",
        },
    ),
}


def _script_keys(case: dict, tmp_path: Path, body_path: Path | None = None) -> tuple[int, set[str]]:
    if body_path is None:
        body_path = tmp_path / "body.md"
        body_path.write_bytes(case["body"].encode("utf-8"))
    files = tmp_path / "files.txt"
    files.write_text("\n".join(case["files"]) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [
            _BASH,
            str(SCRIPT),
            "--title",
            case["title"],
            "--branch",
            case["branch"],
            "--changed-files",
            str(files),
            str(body_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, set(_KEY_LINE.findall(proc.stderr))


_HARNESS = """
const fs = require("fs");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const out = { failed: null, comments: [] };
const github = {
  rest: {
    pulls: { listFiles: () => {} },
    issues: {
      listComments: () => {},
      updateComment: async (a) => { out.comments.push(a.body); },
      createComment: async (a) => { out.comments.push(a.body); },
    },
  },
  paginate: async (fn) => (fn === github.rest.pulls.listFiles ? input.files.map((f) => ({ filename: f })) : []),
};
const context = {
  repo: { owner: "o", repo: "r" },
  payload: { pull_request: { number: 1, body: input.body, title: input.title, head: { ref: input.branch } } },
};
const core = { setFailed: (m) => { out.failed = m; }, info: () => {} };
(async () => {
__SCRIPT__
})().then(() => console.log(JSON.stringify(out)), (e) => { console.error(e); process.exit(3); });
"""


def _workflow_js() -> str:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["check"]["steps"]
    return next(s["with"]["script"] for s in steps if "github-script" in s.get("uses", ""))


def _workflow_keys(case: dict, tmp_path: Path) -> tuple[int, set[str]]:
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS.replace("__SCRIPT__", _workflow_js()), encoding="utf-8")
    proc = subprocess.run(
        [_NODE, str(harness)],
        input=json.dumps(case),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    keys = set(_KEY_LINE.findall("\n".join(out["comments"])))
    return (1 if out["failed"] else 0), keys


@pytest.mark.parametrize("name", sorted(CASES))
def test_script_and_workflow_agree(name: str, tmp_path: Path) -> None:
    case, expected = CASES[name]
    script_rc, script_keys = _script_keys(case, tmp_path)
    wf_rc, wf_keys = _workflow_keys(case, tmp_path)
    assert script_keys == expected, f"script: {sorted(script_keys)}"
    assert wf_keys == expected, f"workflow: {sorted(wf_keys)}"
    assert script_rc == wf_rc == (1 if expected else 0)


def _commit_msg_prefixes() -> list[str]:
    hook = (REPO / ".githooks" / "commit-msg").read_text(encoding="utf-8")
    match = re.search(r"^allowed='([^']+)'", hook, flags=re.MULTILINE)
    assert match, "commit-msg hook lost its allowed= prefix list"
    return match.group(1).split("|")


def test_title_prefixes_match_the_commit_msg_hook(tmp_path: Path) -> None:
    # The squash-merge commit subject is the PR title, so both checkers must
    # accept exactly the commit-msg hook's prefixes.
    for prefix in [*_commit_msg_prefixes(), "chore", "Fix", "wip"]:
        expected = set() if prefix in _commit_msg_prefixes() else {"title"}
        case = _case(title=f"[{prefix}] - Do the thing")
        assert _script_keys(case, tmp_path)[1] == expected, prefix
        assert _workflow_keys(case, tmp_path)[1] == expected, prefix


def _template_body_headings() -> list[str]:
    prose = re.sub(r"```.*?```", "", TEMPLATE.read_text(encoding="utf-8"), flags=re.DOTALL)
    found = re.findall(r"^## (.+)$", prose, flags=re.MULTILINE)
    return [h.strip() for h in found if h.strip() not in _INSTRUCTION_HEADINGS]


def test_every_template_body_section_is_required_by_both(tmp_path: Path) -> None:
    headings = _template_body_headings()
    assert len(headings) >= 8, headings
    for heading in headings:
        stripped = GOOD_BODY.replace(f"## {heading}\n", "")
        # A new template section must be added to GOOD_BODY and to both checkers.
        assert stripped != GOOD_BODY, f"GOOD_BODY lacks template section `## {heading}`"
        case = _case(body=stripped)
        script_rc, _ = _script_keys(case, tmp_path)
        wf_rc, _ = _workflow_keys(case, tmp_path)
        assert script_rc == 1 and wf_rc == 1, (
            f"dropping `## {heading}` passed (script rc={script_rc}, workflow rc={wf_rc})"
        )


def test_shipped_template_passes_its_own_self_check(tmp_path: Path) -> None:
    rc, keys = _script_keys(_case(), tmp_path, body_path=TEMPLATE)
    assert (rc, keys) == (0, set())
