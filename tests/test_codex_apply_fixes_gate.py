"""Execute the apply-fixes issue-comment gate against synthetic GitHub responses."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/codex-apply-fixes.yml"
_NODE = shutil.which("node") or ""
pytestmark = pytest.mark.skipif(not _NODE, reason="node is not installed")
_SHA = "a" * 40
_COMMENT = {"id": 20, "user": {"login": "cgfixit"}, "body": f"@codex apply fixes {_SHA}"}
_BOT = {"id": 10, "user": {"login": "github-actions[bot]", "type": "Bot"}, "body": "Fix this finding."}
_PR = {
    "state": "open",
    "user": {"login": "cgfixit"},
    "head": {"sha": _SHA, "ref": "codex/example", "repo": {"full_name": "cgfixit/CyClaw"}},
    "base": {"sha": "b" * 40},
}


def _run_gate(comment: dict, comments: list[dict], pr: dict = _PR) -> dict:
    steps = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["gate"]["steps"]
    script = next(step for step in steps if step.get("id") == "gate")["with"]["script"]
    harness = "\n".join(
        [
            "const out = {}, fails = [];",
            "const core = {setOutput: (k,v) => {out[k]=v;}, setFailed: m => fails.push(m), info: () => {}};",
            "process.env.TRIGGERING_ACTOR = 'cgfixit';",
            f"const comment = {json.dumps(comment)}, comments = {json.dumps(comments)}, pr = {json.dumps(pr)};",
            "const context = {repo: {owner: 'cgfixit', repo: 'CyClaw'}, actor: 'cgfixit',",
            "  eventName: 'issue_comment', payload: {comment, issue: {number: 1}}};",
            "const github = {",
            "  graphql: async () => {throw new Error(\"Field 'replyTo' doesn't exist on type 'IssueComment'\");},",
            "  paginate: async () => comments,",
            "  rest: {issues: {listComments: {}}, pulls: {get: async () => ({data: pr})},",
            "    repos: {get: async () => ({data: {default_branch: 'main'}})}}",
            "};",
            "(async () => {",
            script,
            "})().then(() => process.stdout.write(JSON.stringify({out, fails})))",
            "  .catch(error => {console.error(error.message); process.exitCode = 1;});",
        ]
    )
    # Same 120s budget as test_claude_workflow_security_contract.py: a stalled
    # node spawn on the Windows runner, not the milliseconds of script work.
    result = subprocess.run([_NODE, "-e", harness], capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_issue_comment_selects_latest_prior_bot_without_graphql() -> None:
    older = {**_BOT, "id": 5}
    human = {**_BOT, "id": 15, "user": {"login": "cgfixit", "type": "User"}}
    future = {**_BOT, "id": 25}
    result = _run_gate(_COMMENT, [older, _BOT, human, future])
    assert result["fails"] == []
    assert result["out"]["head_sha"] == _SHA
    assert json.loads(result["out"]["parent_json"])["id"] == _BOT["id"]


def test_issue_comment_still_requires_a_prior_bot() -> None:
    for comments in [[], [{**_BOT, "id": 25}], [{**_BOT, "user": {"login": "outsider", "type": "User"}}]]:
        result = _run_gate(_COMMENT, comments)
        assert result["fails"] == ["Apply-fixes requires a prior bot comment on this PR."]
        assert "head_sha" not in result["out"]


def test_issue_comment_still_requires_exact_sha_and_owner() -> None:
    cases = [
        ({**_COMMENT, "body": "@codex apply fixes"}, "requires '@codex apply fixes"),
        ({**_COMMENT, "body": f"@codex apply fixes {'b' * 40}"}, "head changed since approval"),
        ({**_COMMENT, "user": {"login": "outsider"}}, "Only the repository owner"),
    ]
    for comment, error in cases:
        result = _run_gate(comment, [_BOT])
        assert len(result["fails"]) == 1
        assert error in result["fails"][0]
        assert "head_sha" not in result["out"]


def test_issue_comment_still_refuses_forks_and_default_branch() -> None:
    for head, error in [
        ({**_PR["head"], "repo": {"full_name": "outsider/CyClaw"}}, "fork PRs"),
        ({**_PR["head"], "ref": "main"}, "default branch"),
    ]:
        result = _run_gate(_COMMENT, [_BOT], {**_PR, "head": head})
        assert len(result["fails"]) == 1
        assert error in result["fails"][0]
        assert "head_sha" not in result["out"]
