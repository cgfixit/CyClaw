#!/usr/bin/env python3
"""Unit tests for classify-failure.py"""

import sys
import subprocess
import json
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the module using importlib to handle hyphenated name
import importlib.util
spec = importlib.util.spec_from_file_location("classify_failure", Path(__file__).parent.parent / "classify-failure.py")
classify_failure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classify_failure)
classify = classify_failure.classify


def test_classify_timeout():
    """Timeout should be classified as flaky."""
    log = "Error: timed out waiting for response after 30s"
    result = classify(log, "test-suite")
    assert result["class"] == "flaky"
    assert "timed out" in result["signal"].lower()


def test_classify_runner_lost():
    """Runner lost should be classified as flaky."""
    log = "##[error]The runner has crashed with a fatal error"
    result = classify(log, "ci-job")
    assert result["class"] == "flaky"


def test_classify_rate_limit():
    """Rate limit should be classified as flaky."""
    log = "Error 429: Too Many Requests (rate limited)"
    result = classify(log, "api-check")
    assert result["class"] == "flaky"


def test_classify_assertion_error():
    """AssertionError should be classified as code."""
    log = """
    test_foo.py::test_bar FAILED

    >       assert result == expected
    E       AssertionError: expected 5, got 4
    """
    result = classify(log, "pytest")
    assert result["class"] == "code"
    assert "AssertionError" in result["signal"]


def test_classify_lint_error():
    """Lint error should be classified as code."""
    log = """
    /path/to/file.py:42:1: E501 line too long (120 > 88 characters)
    /path/to/file.py:45:1: F401 'unused' imported but unused
    """
    result = classify(log, "ruff")
    assert result["class"] == "code"


def test_classify_type_error():
    """TypeError should be classified as code."""
    log = """
    Traceback (most recent call last):
      File "test.py", line 5, in <module>
        foo.bar()
    TypeError: 'NoneType' object is not subscriptable
    """
    result = classify(log, "mypy")
    assert result["class"] == "code"


def test_classify_build_error():
    """Build error should be classified as code."""
    log = "Error: compilation failed with 3 errors"
    result = classify(log, "build")
    assert result["class"] == "code"


def test_classify_cancelled():
    """Cancelled run should be classified as flaky."""
    log = "Job cancelled by workflow"
    result = classify(log, "ci-job")
    assert result["class"] == "flaky"


def test_classify_unknown():
    """Unknown error should be classified as unknown."""
    log = "Something weird happened but we don't know what"
    result = classify(log, "mystery")
    assert result["class"] == "unknown"
    assert len(result["signal"]) > 0


def test_classify_empty_log():
    """Empty log should be unknown."""
    result = classify("", "empty")
    assert result["class"] == "unknown"
    assert result["signal"] == "empty log"


def test_via_stdin():
    """Test calling classify-failure.py via stdin."""
    script = Path(__file__).parent.parent / "classify-failure.py"

    log = "Error: timed out waiting for 30 seconds"
    result = subprocess.run(
        [sys.executable, str(script), "integration-test"],
        input=log,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["class"] == "flaky"
    assert output["check"] == "integration-test"


if __name__ == "__main__":
    # Run all tests
    test_classify_timeout()
    print("✓ test_classify_timeout")

    test_classify_runner_lost()
    print("✓ test_classify_runner_lost")

    test_classify_rate_limit()
    print("✓ test_classify_rate_limit")

    test_classify_assertion_error()
    print("✓ test_classify_assertion_error")

    test_classify_lint_error()
    print("✓ test_classify_lint_error")

    test_classify_type_error()
    print("✓ test_classify_type_error")

    test_classify_build_error()
    print("✓ test_classify_build_error")

    test_classify_cancelled()
    print("✓ test_classify_cancelled")

    test_classify_unknown()
    print("✓ test_classify_unknown")

    test_classify_empty_log()
    print("✓ test_classify_empty_log")

    test_via_stdin()
    print("✓ test_via_stdin")

    print("\nAll tests passed!")
