#!/usr/bin/env bash
# CyClaw SessionStart hook -- cloud-only: start building the Python 3.12 test
# venv in the background so it is ready (or nearly) by the time an agent needs
# `pytest`. It runs the same `driver.sh venv` an agent would run by hand, which
# builds /root/.venv-cyclaw-312 outside the repo and takes a lock, so a manual
# `driver.sh venv` issued meanwhile waits for this build instead of racing it.
#
# Exit code is always 0: this hook prepares, it must never block a session.
set -uo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}" 2>/dev/null || exit 0

setsid nohup bash .claude/skills/cyclaw-gotchas/driver.sh venv \
  >> "${TMPDIR:-/tmp}/cyclaw-session-start-venv.log" 2>&1 < /dev/null &
exit 0
