"""Regression contract for script-lint.yml's shellcheck scope and strictness."""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "script-lint.yml"


def _shellcheck_step() -> str:
    text = _WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: shellcheck every tracked shell script")
    end = text.index("psscriptanalyzer-powershell:", start)
    return text[start:end]


def test_shellcheck_scope_is_every_tracked_shell_script_not_macos_only() -> None:
    """The gate was macos/*.sh only; skill, scripts/ and hook scripts then
    accumulated SC2155/SC2034 warnings unseen. Scope must follow git, so a new
    script is linted without anyone editing a hand-kept list."""
    step = _shellcheck_step()
    assert "git ls-files -- '*.sh'" in step
    assert "find macos" not in step


def test_extensionless_githooks_are_linted() -> None:
    """`*.sh` does not match .githooks/commit-msg etc., so each bash-shebang
    hook must be named in the step explicitly."""
    step = _shellcheck_step()
    hooks = [
        p
        for p in (_ROOT / ".githooks").iterdir()
        if p.is_file()
        and not p.suffix
        and p.read_text(encoding="utf-8", errors="replace").startswith(("#!/usr/bin/env bash", "#!/bin/bash"))
    ]
    assert hooks, "expected bash hooks under .githooks"
    for hook in hooks:
        assert f".githooks/{hook.name}" in step, f"script-lint.yml does not shellcheck {hook.name}"


def test_shellcheck_stays_fail_closed_with_no_rule_exclusions() -> None:
    step = _shellcheck_step()
    assert "shellcheck --norc -S warning --" in step
    assert not re.search(r"shellcheck[^\n]*\s(-e|--exclude)\b", step)
    assert "continue-on-error" not in step
    assert "|| true" not in step


def test_script_lint_push_covers_documented_feature_prefixes() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    push = text.split("push:", 1)[1].split("pull_request:", 1)[0]
    for prefix in ("claude/**", "grok/**", "codex/**", "kimi/**", "agent/**", "CyClaw/**", "cyclaw/**", "cursor/**"):
        assert f"'{prefix}'" in push, f"script-lint.yml push filters missing {prefix}"
