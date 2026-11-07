#!/usr/bin/env bash
# Delegate from this checkout, independent of the invoking directory.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export CYCLAW_REPORT_DIR="${CYCLAW_REPORT_DIR:-${TMPDIR:-/tmp}/cyclaw-sandbox-report}"
cd "$REPO_ROOT"
exec "$BASH" "$REPO_ROOT/.claude/skills/CyClaw-Sandbox/smoke.sh" "$@"
