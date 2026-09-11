#!/bin/bash
# verify.sh: Verification script for the babysit-github-pr skill.
# Runs syntax checks, unit tests, and basic smoke tests.
# Exit codes: 0=pass, 1=fail, 3=missing deps

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check for required tools
check_deps() {
    local missing_deps=()

    for tool in jq python3 bash git; do
        if ! command -v "$tool" &>/dev/null; then
            missing_deps+=("$tool")
        fi
    done

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        echo "ERROR: Missing required tools: ${missing_deps[*]}" >&2
        return 3
    fi
}

# Verify shell script syntax
verify_shell_scripts() {
    echo "Checking shell script syntax..."

    for script in "$SCRIPT_DIR"/scripts/*.sh; do
        if ! bash -n "$script" 2>/dev/null; then
            echo "ERROR: Syntax error in $script" >&2
            return 1
        fi
    done

    echo "✓ All shell scripts have valid syntax"
}

# Verify Python script syntax
verify_python_scripts() {
    echo "Checking Python script syntax..."

    for script in "$SCRIPT_DIR"/scripts/*.py; do
        if ! python3 -m py_compile "$script" 2>/dev/null; then
            echo "ERROR: Syntax error in $script" >&2
            return 1
        fi
    done

    echo "✓ All Python scripts have valid syntax"
}

# Run unit tests
run_unit_tests() {
    echo "Running unit tests..."

    cd "$SCRIPT_DIR"

    if ! python3 scripts/tests/test_classify_failure.py >/dev/null 2>&1; then
        echo "ERROR: classify-failure tests failed" >&2
        python3 scripts/tests/test_classify_failure.py
        return 1
    fi

    if ! python3 scripts/tests/test_detect_test_command.py >/dev/null 2>&1; then
        echo "ERROR: detect-test-command tests failed" >&2
        python3 scripts/tests/test_detect_test_command.py
        return 1
    fi

    echo "✓ All unit tests passed"
}

# Smoke test: verify scripts produce expected output
smoke_test() {
    echo "Running smoke tests..."

    cd "$SCRIPT_DIR"

    # Test classify-failure with empty input
    if ! echo "" | python3 scripts/classify-failure.py test >/dev/null 2>&1; then
        echo "ERROR: classify-failure smoke test failed" >&2
        return 1
    fi

    # Test detect-test-command
    if ! python3 scripts/detect-test-command.py >/dev/null 2>&1; then
        echo "ERROR: detect-test-command smoke test failed" >&2
        return 1
    fi

    # Test help output (note: output goes to stderr)
    local babysit_output=$(bash scripts/run-babysit.sh 2>&1 || true)
    if ! echo "$babysit_output" | grep -q "Usage:"; then
        echo "ERROR: run-babysit.sh help output failed" >&2
        echo "Output was: $babysit_output" >&2
        return 1
    fi

    echo "✓ All smoke tests passed"
}

# Verify documentation
verify_docs() {
    echo "Checking documentation..."

    if [[ ! -f "$SCRIPT_DIR/SKILL.md" ]]; then
        echo "ERROR: SKILL.md not found" >&2
        return 1
    fi

    if [[ ! -f "$SCRIPT_DIR/README.md" ]]; then
        echo "ERROR: README.md not found" >&2
        return 1
    fi

    # Check for key sections
    if ! grep -q "^name: babysit-github-pr" "$SCRIPT_DIR/SKILL.md"; then
        echo "ERROR: SKILL.md missing proper frontmatter" >&2
        return 1
    fi

    if ! grep -q "Installation" "$SCRIPT_DIR/README.md"; then
        echo "ERROR: README.md missing Installation section" >&2
        return 1
    fi

    echo "✓ Documentation OK"
}

# Main
main() {
    echo "=== Verifying babysit-github-pr skill ==="

    check_deps || return $?
    verify_docs || return 1
    verify_shell_scripts || return 1
    verify_python_scripts || return 1
    run_unit_tests || return 1
    smoke_test || return 1

    echo ""
    echo "✓ All verifications passed!"
    return 0
}

main "$@"
