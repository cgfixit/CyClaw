#!/usr/bin/env bash
# CyClaw SessionStart hook -- model-gated fable-protocol loader.
#
# Injects .claude/skills/fable-protocol/SKILL.md as additionalContext at every
# SessionStart (startup / resume / clear / compact) ONLY when the session model
# is Sonnet-tier (2026-09-16, issue #1351 follow-up: switched from an opt-out
# blocklist -- inject unless Fable-tier -- to an opt-in allowlist -- inject only
# for Sonnet). Rationale: the protocol exists to make a model apply the
# disciplines a stronger one applies by default; Sonnet is the tier that
# benefits most for the cost. Opus, Haiku, Fable, and any absent/unrecognized
# model string are all skipped now -- Opus and Fable get the skill on demand
# (/fable-protocol) rather than a ~1.5KB auto-inject on every session start.
#
# Why SessionStart and not per prompt: SessionStart is the ONLY hook event whose
# stdin JSON carries the model (`model`, optional -- verified against the Claude
# Code 2.1.261 hook schema: base {session_id, transcript_path, cwd,
# permission_mode?} + SessionStart {source, agent_type?, model?}; UserPromptSubmit
# carries only {prompt}). A mid-session `/model` switch fires no hook at all, so
# this cannot re-gate on it -- run /fable-protocol by hand after switching TO
# Sonnet mid-session; see .claude/README.md. Per-prompt injection of this file
# was also deliberately unwired on 2026-09-04 (cost + attack surface).
#
# Exit code is always 0: this hook advises, it must never block a session.
# Diagnostics go to stderr; stdout carries only the hook JSON (or nothing).
set -uo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
skill="$repo_root/.claude/skills/fable-protocol/SKILL.md"
[ -f "$skill" ] || { echo "[fable-loader] $skill missing; nothing injected" >&2; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "[fable-loader] jq not on PATH; nothing injected" >&2; exit 0; }

input=$(cat 2>/dev/null || true)
model=$(printf '%s' "$input" | jq -r '.model // empty' 2>/dev/null || true)
# tr, not ${var,,}: macOS ships bash 3.2, which lacks case-conversion expansion.
model_lc=$(printf '%s' "$model" | tr '[:upper:]' '[:lower:]')

case "$model_lc" in
  *sonnet*)
    echo "[fable-loader] model '$model' is Sonnet-tier: injecting fable-protocol (SessionStart only; a mid-session /model switch does not re-run this hook)" >&2
    ;;
  *)
    echo "[fable-loader] model '${model:-unknown}' is not Sonnet-tier; fable-protocol not injected (available on demand via /fable-protocol)" >&2
    exit 0 ;;
esac

jq -cn --rawfile ctx "$skill" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$ctx}}'
exit 0
