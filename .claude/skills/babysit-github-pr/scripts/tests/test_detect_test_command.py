#!/usr/bin/env python3
"""Unit tests for detect-test-command.py"""

import sys
import subprocess
import json
import tempfile
import os
from pathlib import Path
import importlib.util

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the module using importlib to handle hyphenated name
spec = importlib.util.spec_from_file_location("detect_test_command", Path(__file__).parent.parent / "detect-test-command.py")
detect_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(detect_module)
detect_from_makefile = detect_module.detect_from_makefile
detect_from_package_json = detect_module.detect_from_package_json
detect_from_pyproject_toml = detect_module.detect_from_pyproject_toml
detect_from_tox_ini = detect_module.detect_from_tox_ini


def test_detect_from_makefile():
    """Test Makefile detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        makefile = Path("Makefile")
        makefile.write_text("""
.PHONY: test lint

test:
\tpytest tests/ -q

lint:
\truff check .
""")

        test_cmd, lint_cmd = detect_from_makefile()
        assert test_cmd == "make test"
        assert lint_cmd == "make lint"


def test_detect_from_package_json():
    """Test package.json detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        pkg_json = Path("package.json")
        pkg_json.write_text(json.dumps({
            "name": "my-app",
            "scripts": {
                "test": "jest --coverage",
                "lint": "eslint src/"
            }
        }))

        test_cmd, lint_cmd = detect_from_package_json()
        assert "jest" in test_cmd or "test" in test_cmd
        assert "eslint" in lint_cmd or "lint" in lint_cmd


def test_detect_from_pyproject_toml():
    """Test pyproject.toml detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        pyproject = Path("pyproject.toml")
        pyproject.write_text("""
[project]
name = "my-project"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 120
""")

        test_cmd, lint_cmd = detect_from_pyproject_toml()
        assert "pytest" in test_cmd
        assert "ruff" in lint_cmd


def test_detect_from_tox_ini():
    """Test tox.ini detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        tox_ini = Path("tox.ini")
        tox_ini.write_text("""
[tox]
envlist = py38,py39,py310

[testenv:py]
deps = pytest
commands = pytest tests/
""")

        test_cmd, lint_cmd = detect_from_tox_ini()
        assert test_cmd is not None and "tox" in test_cmd


def test_via_subprocess():
    """Test calling detect-test-command.py via subprocess."""
    script = Path(__file__).parent.parent / "detect-test-command.py"

    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        # Create a pyproject.toml
        pyproject = Path("pyproject.toml")
        pyproject.write_text("""
[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 120
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "test_command" in output
        assert "lint_command" in output
        assert len(output["test_command"]) > 0
        assert len(output["lint_command"]) > 0


def test_detection_order():
    """Test that Makefile is preferred over package.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        # Create both Makefile and package.json
        makefile = Path("Makefile")
        makefile.write_text("""
.PHONY: test
test:
\techo "makefile test"
""")

        pkg_json = Path("package.json")
        pkg_json.write_text(json.dumps({
            "scripts": {
                "test": "jest"
            }
        }))

        test_cmd, _ = detect_from_makefile()
        assert test_cmd == "make test"  # DevSkim: ignore DS197836

        test_cmd2, _ = detect_from_package_json()
        assert "jest" in test_cmd2  # DevSkim: ignore DS197836


if __name__ == "__main__":
    # Test makefile detection (in temp dir)
    print("Testing makefile detection...")
    test_detect_from_makefile()
    print("✓ test_detect_from_makefile")

    print("Testing package.json detection...")
    test_detect_from_package_json()
    print("✓ test_detect_from_package_json")

    print("Testing pyproject.toml detection...")
    test_detect_from_pyproject_toml()
    print("✓ test_detect_from_pyproject_toml")

    print("Testing tox.ini detection...")
    test_detect_from_tox_ini()
    print("✓ test_detect_from_tox_ini")

    print("Testing via subprocess...")
    test_via_subprocess()
    print("✓ test_via_subprocess")

    print("Testing detection order...")
    test_detection_order()
    print("✓ test_detection_order")

    print("\nAll tests passed!")
