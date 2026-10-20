"""Regression contract for claude.yml's read/write split (#1709 item 1).

claude.yml answers an owner ``@claude`` comment. The ``gate`` job refuses fork
PRs and picks a mode: ``read`` by default, ``write`` only when the comment's
last line is the approval phrase. The mode is enforced by which job runs and
that job's ``permissions``, not by the prompt. These tests run the gate's real
embedded script under Node against mocked PRs and comments, and pin the
permissions each job holds.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "claude.yml"
_NODE = shutil.which("node") or ""

_SAME_REPO = {"head": {"repo": {"full_name": "cgfixit/CyClaw"}}, "state": "open"}
_APPROVAL = "write access approved for this PR"


def _jobs() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _gate_script() -> str:
    gate = next(step for step in _jobs()["gate"]["steps"] if step.get("id") == "gate")
    return gate["with"]["script"]


def _run_gate(pr: dict, body: str) -> dict:
    # Drive the embedded actions/github-script body with stand-ins for the
    # github/core/context globals it uses; no network, no real Actions runtime.
    harness = (
        "const out = {}, fails = [];\n"
        "const core = {setOutput: (k, v) => { out[k] = v; }, setFailed: (m) => fails.push(m)};\n"
        "const context = {repo: {owner: 'cgfixit', repo: 'CyClaw'}, issue: {number: 1},\n"
        f"  payload: {{comment: {{body: {json.dumps(body)}}}}}}};\n"
        f"const prData = {json.dumps(pr)};\n"
        "const github = {rest: {pulls: {get: async () => ({data: prData})}}};\n"
        "(async () => {\n" + _gate_script() + "\n})().then(() => {\n"
        "  process.stdout.write(JSON.stringify({out, fails}));\n"
        "});\n"
    )
    result = subprocess.run(
        [_NODE, "-e", harness], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(result.stdout)


needs_node = pytest.mark.skipif(not _NODE, reason="node is not installed")


@needs_node
@pytest.mark.parametrize(
    "body",
    [
        "@claude review this",
        f"@claude what does '{_APPROVAL}' do?",
        f"{_APPROVAL}\n@claude fix the lint error",
        "@claude fix it\nwrite access approved",
    ],
    ids=["plain", "quoted-mid-line", "not-last-line", "partial-phrase"],
)
def test_read_mode_is_the_default(body: str) -> None:
    result = _run_gate(_SAME_REPO, body)
    assert result == {"out": {"mode": "read"}, "fails": []}


@needs_node
@pytest.mark.parametrize(
    "last_line",
    [_APPROVAL, _APPROVAL.upper(), f"{_APPROVAL}.", f"  {_APPROVAL}!  "],
    ids=["exact", "upper", "period", "padded-bang"],
)
def test_write_mode_needs_the_phrase_as_last_line(last_line: str) -> None:
    result = _run_gate(_SAME_REPO, f"@claude fix the lint error\r\n{last_line}\n")
    assert result == {"out": {"mode": "write"}, "fails": []}


@needs_node
@pytest.mark.parametrize(
    "head_repo",
    [{"full_name": "attacker/CyClaw"}, None],
    ids=["outside-fork", "deleted-fork"],
)
def test_fork_pr_is_refused_even_with_approval(head_repo: dict | None) -> None:
    pr = {**_SAME_REPO, "head": {"repo": head_repo}}
    result = _run_gate(pr, f"@claude fix\n{_APPROVAL}")
    assert result == {"out": {}, "fails": ["Refusing @claude on fork PRs."]}


@needs_node
def test_closed_pr_is_refused() -> None:
    result = _run_gate({**_SAME_REPO, "state": "closed"}, "@claude review")
    assert result == {"out": {}, "fails": ["PR is not open."]}


def test_job_permissions_follow_the_mode() -> None:
    jobs = _jobs()
    assert jobs["gate"]["permissions"] == {"pull-requests": "read"}
    assert jobs["review"]["permissions"]["contents"] == "read"
    assert jobs["write"]["permissions"]["contents"] == "write"
    assert jobs["review"]["if"] == "needs.gate.outputs.mode == 'read'"
    assert jobs["write"]["if"] == "needs.gate.outputs.mode == 'write'"
    for name in ("review", "write"):
        assert jobs[name]["needs"] == "gate"


def test_read_mode_denies_edit_and_commit_tools() -> None:
    action = next(s for s in _jobs()["review"]["steps"] if "claude-code-action" in s.get("uses", ""))
    args = action["with"]["claude_args"]
    for tool in ("Edit", "Write", "Bash(git commit:*)", "WebFetch"):
        assert tool in args
