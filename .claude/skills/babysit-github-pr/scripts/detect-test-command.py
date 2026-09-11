#!/usr/bin/env python3
"""
Detect test and lint commands from project configuration files.

Detection order:
1. Makefile (targets: test, tests, check, test-all)
2. package.json (scripts: test, lint)
3. pyproject.toml (pytest/tox config)
4. tox.ini (envs)
5. .github/workflows/*.yml (run: steps)
6. Ask user if ambiguous or not found

Outputs JSON: {"test_command": "...", "lint_command": "..."}
"""

import sys
import json
import re
import os
from pathlib import Path
from typing import Optional, Tuple


def detect_from_makefile() -> Tuple[Optional[str], Optional[str]]:
    """Extract test and lint targets from Makefile."""
    makefile = Path("Makefile")
    if not makefile.exists():
        return None, None

    content = makefile.read_text()
    test_cmd, lint_cmd = None, None

    # Look for test targets
    for target in ["test", "tests", "check", "test-all"]:
        if re.search(rf"^{target}:", content, re.MULTILINE):
            test_cmd = f"make {target}"
            break

    # Look for lint targets
    for target in ["lint", "linting", "check-lint", "style"]:
        if re.search(rf"^{target}:", content, re.MULTILINE):
            lint_cmd = f"make {target}"
            break

    return test_cmd, lint_cmd


def detect_from_package_json() -> Tuple[Optional[str], Optional[str]]:
    """Extract test and lint scripts from package.json."""
    pkg_file = Path("package.json")
    if not pkg_file.exists():
        return None, None

    try:
        import json as json_module
        pkg = json_module.loads(pkg_file.read_text())
        scripts = pkg.get("scripts", {})

        test_cmd = None
        for key in ["test", "tests"]:
            if key in scripts:
                test_cmd = f"npm {scripts[key]}" if " " not in scripts[key] else f"npm run {key}"
                break

        lint_cmd = None
        for key in ["lint", "linting", "eslint"]:
            if key in scripts:
                lint_cmd = f"npm {scripts[key]}" if " " not in scripts[key] else f"npm run {key}"
                break

        return test_cmd, lint_cmd
    except (json.JSONDecodeError, KeyError):
        return None, None


def detect_from_pyproject_toml() -> Tuple[Optional[str], Optional[str]]:
    """Extract pytest/tox config from pyproject.toml."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return None, None

    content = pyproject.read_text()

    test_cmd = None
    lint_cmd = None

    # Default pytest command for Python projects
    if "[tool.pytest" in content or "pytest" in content:
        test_cmd = "pytest tests/ -q"

    # Check for ruff linting
    if "[tool.ruff" in content or "ruff" in content:
        lint_cmd = "ruff check --select F,B,S ."

    # Check for mypy
    if "[tool.mypy" in content and not lint_cmd:
        lint_cmd = "mypy ."

    return test_cmd, lint_cmd


def detect_from_tox_ini() -> Tuple[Optional[str], Optional[str]]:
    """Extract test command from tox.ini."""
    tox_file = Path("tox.ini")
    if not tox_file.exists():
        return None, None

    content = tox_file.read_text()

    test_cmd = None
    # Look for py or test envs
    if re.search(r"^\[testenv:py", content, re.MULTILINE):
        test_cmd = "tox -e py"
    elif re.search(r"^\[testenv:test", content, re.MULTILINE):
        test_cmd = "tox -e test"

    return test_cmd, None


def detect_from_workflows() -> Tuple[Optional[str], Optional[str]]:
    """Scrape test/lint commands from .github/workflows/*.yml."""
    workflows_dir = Path(".github/workflows")
    if not workflows_dir.exists():
        return None, None

    test_cmd, lint_cmd = None, None

    for workflow_file in workflows_dir.glob("*.yml"):
        try:
            content = workflow_file.read_text()

            # Look for pytest
            if "pytest" in content and not test_cmd:
                match = re.search(r"run:\s*(.+pytest.+?)(?:\n|$)", content, re.IGNORECASE)
                if match:
                    test_cmd = match.group(1).strip()

            # Look for ruff
            if "ruff" in content and not lint_cmd:
                match = re.search(r"run:\s*(.+ruff.+?)(?:\n|$)", content, re.IGNORECASE)
                if match:
                    lint_cmd = match.group(1).strip()

            # Look for npm test
            if "npm test" in content and not test_cmd:
                test_cmd = "npm test"

            if test_cmd and lint_cmd:
                break
        except Exception:
            continue

    return test_cmd, lint_cmd


def main():
    """Detect test/lint commands and output JSON."""
    # Detection order (first match wins)
    sources = [
        detect_from_makefile,
        detect_from_package_json,
        detect_from_pyproject_toml,
        detect_from_tox_ini,
        detect_from_workflows,
    ]

    test_cmd = None
    lint_cmd = None

    for detector in sources:
        t, l = detector()
        if not test_cmd and t:
            test_cmd = t
        if not lint_cmd and l:
            lint_cmd = l
        if test_cmd and lint_cmd:
            break

    result = {
        "test_command": test_cmd or "pytest tests/ -q",  # safe default for Python
        "lint_command": lint_cmd or "ruff check --select F,B,S .",  # safe default
    }

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
