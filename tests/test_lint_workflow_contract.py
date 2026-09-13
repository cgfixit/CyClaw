"""Regression contract for changed-file handling in the lint workflow."""

from pathlib import Path

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "lint.yml"


def test_changed_python_paths_stay_nul_delimited_until_flake8_argv() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "git diff --name-only -z" in text
    assert "mapfile -d ''" in text
    assert 'flake8 -- "${FILES[@]}"' in text
    assert "CHANGED_FILES" not in text


def test_lint_push_covers_documented_feature_prefixes() -> None:
    """Push lint must fire for every vendor prefix the PR template allows,
    plus cursor/** used by Cursor Cloud agents. lora-finetune.yml already
    listed agent/CyClaw/cyclaw; lint.yml had only claude/grok/codex/kimi.
    """
    text = _WORKFLOW.read_text(encoding="utf-8")
    push = text.split("push:", 1)[1].split("pull_request:", 1)[0]
    for prefix in (
        "claude/**",
        "grok/**",
        "codex/**",
        "kimi/**",
        "agent/**",
        "CyClaw/**",
        "cyclaw/**",
        "cursor/**",
    ):
        assert f"'{prefix}'" in push, f"lint.yml push filters missing {prefix}"
