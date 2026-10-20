"""Regression contract for codex.yml's same-repo gate (#1709 item 2).

codex.yml answers an owner ``@codex`` comment with a job that holds
``secrets.CODEX``. An ``issue_comment`` payload carries no head repo, so the
job ``if:`` cannot refuse fork PRs; the "Resolve PR commits" step does it
after ``pulls.get``. These tests run that step's real embedded script under
Node against mocked PRs, and pin that it runs before anything that reads the
PR or holds the key.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "codex.yml"
_NODE = shutil.which("node") or ""

_SAME_REPO = {"base": {"sha": "b"}, "head": {"sha": "h", "repo": {"full_name": "cgfixit/CyClaw"}}, "state": "open"}


def _steps() -> list[dict]:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["codex"]["steps"]


def _gate_script() -> str:
    gate = next(step for step in _steps() if step.get("id") == "pr")
    return gate["with"]["script"]


def _run_gate(pr: dict) -> dict:
    # Drive the embedded actions/github-script body with stand-ins for the
    # github/core/context globals it uses; no network, no real Actions runtime.
    harness = (
        "const out = {}, fails = [];\n"
        "const core = {setOutput: (k, v) => { out[k] = v; }, setFailed: (m) => fails.push(m)};\n"
        "const context = {repo: {owner: 'cgfixit', repo: 'CyClaw'}, payload: {issue: {number: 1}}};\n"
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
def test_same_repo_open_pr_passes_with_shas() -> None:
    result = _run_gate(_SAME_REPO)
    assert result["fails"] == []
    assert result["out"] == {"base-sha": "b", "head-sha": "h"}


@needs_node
@pytest.mark.parametrize(
    "head_repo",
    [{"full_name": "attacker/CyClaw"}, None],
    ids=["outside-fork", "deleted-fork"],
)
def test_fork_pr_is_refused_before_any_output(head_repo: dict | None) -> None:
    pr = {**_SAME_REPO, "head": {"sha": "h", "repo": head_repo}}
    result = _run_gate(pr)
    assert result["fails"] == ["Refusing @codex on fork PRs."]
    assert result["out"] == {}


@needs_node
def test_closed_pr_is_refused() -> None:
    result = _run_gate({**_SAME_REPO, "state": "closed"})
    assert result["fails"] == ["PR is not open."]
    assert result["out"] == {}


@needs_node
def test_repo_name_comparison_ignores_case() -> None:
    pr = {**_SAME_REPO, "head": {"sha": "h", "repo": {"full_name": "CGFixIT/cyclaw"}}}
    assert _run_gate(pr)["fails"] == []


def test_gate_runs_before_checkout_diff_and_codex() -> None:
    names = [step.get("name", "") for step in _steps()]
    uses = [step.get("uses", "") for step in _steps()]
    gate = next(i for i, step in enumerate(_steps()) if step.get("id") == "pr")
    checkout = next(i for i, u in enumerate(uses) if u.startswith("actions/checkout@"))
    diff = names.index("Record owner request and PR diff")
    codex = next(i for i, u in enumerate(uses) if u.startswith("openai/codex-action@"))
    assert gate < checkout < codex
    assert gate < diff < codex
    assert gate == 0
