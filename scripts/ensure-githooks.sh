#!/usr/bin/env bash
# Point this clone at the tracked .githooks/ -- the one setup line every agent
# runs (Claude Code SessionStart, Copilot setup steps, a Codex environment
# setup script, a container entrypoint, or a person after cloning).
#
# Idempotent and never fatal: setup must not fail because of it.
#   - Outside a git work tree, or without .githooks/: does nothing.
#   - core.hooksPath unset at every scope (local, global, system): sets it to
#     .githooks in this repo.
#   - Already .githooks: says so.
#   - Set to anything else, at any scope: leaves it alone and says how to switch, so an
#     operator's deliberate hook manager is never overwritten.
#   - GITHOOKS_SKIP_INSTALL=1: does nothing (operator opt-out).
#
# Pipelines that run git with their own `-c core.hooksPath=...` (CyClaw's
# agentic executor, CGagentHarness's coding pipeline, codex-apply-fixes.yml)
# are unaffected: a command-line value outranks repository config.
set -u

say() { printf '[githooks] %s\n' "$*"; }

[ "${GITHOOKS_SKIP_INSTALL:-}" = "1" ] && { say "GITHOOKS_SKIP_INSTALL=1; leaving core.hooksPath as is."; exit 0; }
root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$root" || exit 0
[ -d .githooks ] || { say "no .githooks/ in this checkout; nothing to install."; exit 0; }

# No --local: the effective value, so a global or system hook manager (husky,
# a shared template) is seen and kept rather than shadowed by a repo-local write.
current="$(git config --get core.hooksPath 2>/dev/null || true)"
case "$current" in
  .githooks | .githooks/ | "$root/.githooks" | "$root/.githooks/")
    say "core.hooksPath is already .githooks." ;;
  "")
    if git config --local core.hooksPath .githooks; then
      say "core.hooksPath set to .githooks (tracked hooks are now active in this clone)."
    else
      say "could not set core.hooksPath; run: git config core.hooksPath .githooks"
      exit 0
    fi ;;
  *)
    say "core.hooksPath is '$current'; leaving it. To use the tracked hooks: git config core.hooksPath .githooks"
    exit 0 ;;
esac

if [ -f .githooks/_security.sh ] && ! command -v gitleaks >/dev/null 2>&1; then
  say "gitleaks not installed: the security gate will use provider-prefix patterns only."
fi
exit 0
