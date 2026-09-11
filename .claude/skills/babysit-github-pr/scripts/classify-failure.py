#!/usr/bin/env python3
"""
Classify CI/check failures as flaky, code, or unknown.

Reads GitHub action run log (from `gh run view --log-failed`) on stdin.
Outputs JSON: {"class": "flaky|code|unknown", "signal": "...", "check": "..."}
"""

import sys
import json
import re

# Flaky patterns: common transient failures that should be retried
FLAKY_PATTERNS = [
    r"(timed out|timeout|timed out waiting)",
    r"(Connection reset|connection reset by peer)",
    r"(runner lost|runner exited|runner has crashed)",
    r"(rate limit|rate limited|429|Too Many Requests)",
    r"cancelled by workflow|job cancelled|workflow cancelled",
    r"(GitHub API returned HTTP 503|Service Unavailable|500 Internal Server Error)",
    r"(Temporary failure|temporarily unavailable)",
]

# Code failure patterns: real bugs that need fixing
CODE_FAILURE_PATTERNS = [
    r"AssertionError",
    r"(FAILED|ERROR|FAIL)",
    r"TypeError|AttributeError|KeyError|ValueError",
    r"(E501|E401|E302|F401|F811)",  # ruff codes
    r"(import .* not found|ModuleNotFoundError)",
    r"(test failed|tests? failed|test passed)",
    r"(syntax error|parse error|IndentationError)",
    r"(build failed|build error|compilation failed)",
    r"(linting failed|lint error|style error)",
]


def classify(log_text: str, check_name: str = "unknown") -> dict:
    """
    Classify a failure log as flaky, code, or unknown.

    Returns:
        {
            "class": "flaky" | "code" | "unknown",
            "signal": "<matched pattern or reason>",
            "check": "<check name>"
        }
    """
    if not log_text or not log_text.strip():
        return {"class": "unknown", "signal": "empty log", "check": check_name}

    # Check flaky patterns first
    for pattern in FLAKY_PATTERNS:
        match = re.search(pattern, log_text, re.IGNORECASE | re.MULTILINE)
        if match:
            return {
                "class": "flaky",
                "signal": match.group(0).strip(),
                "check": check_name,
            }

    # Check code failure patterns
    for pattern in CODE_FAILURE_PATTERNS:
        match = re.search(pattern, log_text, re.IGNORECASE | re.MULTILINE)
        if match:
            return {
                "class": "code",
                "signal": match.group(0).strip(),
                "check": check_name,
            }

    # Unknown: no pattern matched
    # Extract first non-empty line as signal
    signal = next(
        (line.strip() for line in log_text.split("\n") if line.strip()),
        "no signal detected"
    )
    if len(signal) > 100:
        signal = signal[:100] + "..."

    return {
        "class": "unknown",
        "signal": signal,
        "check": check_name,
    }


def main():
    """Read log from stdin, classify, output JSON."""
    log_text = sys.stdin.read()

    # Try to extract check name from environment or stdin
    check_name = sys.argv[1] if len(sys.argv) > 1 else "unknown"

    result = classify(log_text, check_name)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
