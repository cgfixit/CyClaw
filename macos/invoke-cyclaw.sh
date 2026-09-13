#!/usr/bin/env bash
# Launches the CyClaw RAG gateway (gate.py / static/terminal.html).
#
# macOS (Apple Silicon arm64) and Linux, bash or zsh.
# - RAG gateway (gate.py / static/terminal.html): 127.0.0.1:8787
# Uses the per-user venv under ~/.CyClaw/venv and the repo at $CYCLAW_REPO
# (or ~/.CyClaw/repo). Ctrl+C stops the server.
#
# Usage:
#   cyclaw
#   bash macos/invoke-cyclaw.sh --no-browser --gate-port 8788
#
# Options:
#   --gate-port PORT  RAG gateway / terminal.html port (default 8787)
#   --no-browser      do not open a browser; just serve
#   --repo PATH       explicit path to the CyClaw checkout (overrides $CYCLAW_REPO)

set -euo pipefail

GATE_PORT="${CYCLAW_GATE_PORT:-8787}"
NO_BROWSER=0
REPO_OVERRIDE=""

# Validate a port before it reaches `uvicorn --port` and the printed URL.
# Without this a typo ("--gate-port 87go") is echoed as a working-looking URL
# and then fails deep inside uvicorn's own argument parsing.
require_port() {
  case "$2" in
    ''|*[!0-9]*)
      echo "$1 requires a numeric port (got '$2')" >&2
      exit 1
      ;;
  esac
  if [ "$2" -lt 1 ] || [ "$2" -gt 65535 ]; then
    echo "$1 must be between 1 and 65535 (got '$2')" >&2
    exit 1
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --gate-port)
      GATE_PORT="${2:?--gate-port requires a value}"
      shift 2
      ;;
    --no-browser)
      NO_BROWSER=1
      shift
      ;;
    --repo)
      REPO_OVERRIDE="${2:?--repo requires a value}"
      shift 2
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Validated after the parse loop so the env-var default above (CYCLAW_GATE_PORT)
# gets the same check as the flag -- an operator who exports a bad value in
# their rc file would otherwise skip validation entirely.
require_port "gate port (--gate-port / CYCLAW_GATE_PORT)" "$GATE_PORT"

HOME_DIR="${CYCLAW_HOME:-$HOME/.CyClaw}"
if [ -n "$REPO_OVERRIDE" ]; then
  REPO_DIR="$REPO_OVERRIDE"
else
  REPO_DIR="${CYCLAW_REPO:-$HOME_DIR/repo}"
fi

VENV_PY="$HOME_DIR/venv/bin/python"
if [ ! -f "$REPO_DIR/gate.py" ]; then
  echo "CyClaw repo not found at '$REPO_DIR' (missing gate.py). Run install-cyclaw.sh first (or pass --repo)." >&2
  exit 1
fi
if [ ! -x "$VENV_PY" ]; then
  # Same 3.12 probe as install-cyclaw.sh. Bare `python3` on macOS is often
  # 3.11 (Xcode CLT / unversioned Homebrew), and CyClaw requires 3.12.
  VENV_PY=""
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
      if [ "$ver" = "3.12" ]; then
        VENV_PY="$(command -v "$candidate")"
        break
      fi
    fi
  done
  if [ -z "$VENV_PY" ] || [ ! -x "$VENV_PY" ]; then
    echo "No venv at $HOME_DIR/venv and no Python 3.12.x on PATH. Re-run install-cyclaw.sh." >&2
    exit 1
  fi
fi

export CYCLAW_HOME="$HOME_DIR"
export CYCLAW_REPO="$REPO_DIR"
export CYCLAW_GATE_PORT="$GATE_PORT"

echo "[cyclaw] repo     : $REPO_DIR"
echo "[cyclaw] home     : $HOME_DIR"
echo "[cyclaw] terminal : http://127.0.0.1:$GATE_PORT  (RAG gateway / static/terminal.html)"
echo "[cyclaw] Ctrl+C stops the server"

# Load persisted keys into THIS process so gate.py inherits them.
# ~/.CyClaw/.env is chmod 600 and gitignored. Never print its contents.
# xtrace would dump every assignment — refuse rather than leak.
# ponytail: one copy here (shim + cyclaw() + direct script all exec this).
_dotenv_mode() {
  if [ "$(uname -s)" = "Darwin" ]; then
    # Pin BSD stat: a GNU stat earlier on PATH interprets -f differently,
    # so valid private dotenv files could fail the permission check.
    /usr/bin/stat -f %Lp "$1" 2>/dev/null || true
  else
    stat -c %a "$1" 2>/dev/null || true
  fi
}

_source_dotenv() {
  local f="$1"
  local mode=""
  [ -f "$f" ] || return 1
  mode="$(_dotenv_mode "$f")"
  case "$mode" in
    600|400) ;;
    *)
      # Name the file and the remedy. Without them the operator sees only a
      # mode number here and "CYCLAW_API_KEY not set" below, and the actual
      # cause -- a dotenv other local accounts can read -- goes unstated.
      echo "[cyclaw] warn : refusing to source $f (mode ${mode:-unknown}; want 600 or 400). Fix with: chmod 600 $f" >&2
      return 1
      ;;
  esac
  # Preserve source failure across export-state cleanup so the caller can
  # try the repo dotenv when loading the preferred file fails.
  # shellcheck disable=SC1090
  local source_status=0
  local had_allexport=0
  case "$-" in *a*) had_allexport=1 ;; esac
  set -a
  . "$f" || source_status=$?
  # Restore the caller's export policy; an unconditional set +a would disable
  # a setting that may have been enabled before this helper was called.
  if [ "$had_allexport" -eq 0 ]; then
    set +a
  fi
  return "$source_status"
}

if [ -z "${CYCLAW_API_KEY:-}" ]; then
  case "$-" in
    *x*) echo "[cyclaw] error: refusing to source .env with xtrace on (would print secrets). Re-run without bash -x." >&2; exit 1 ;;
  esac
  # Chained on the result, not `-f`: a refused HOME file must not shadow the repo copy.
  _source_dotenv "$HOME_DIR/.env" || _source_dotenv "$REPO_DIR/.env" || true
fi

if [ -z "${CYCLAW_API_KEY:-}" ]; then
  echo "[cyclaw] warn : CYCLAW_API_KEY not set — Soul / ops state-changing routes will 401. Typing the key in the browser cannot configure the server; source ~/.CyClaw/.env or set the env var, then restart." >&2
fi

# --- cleanup on exit / signals ---
GATE_PID=""
cleanup() {
  trap - EXIT INT TERM
  if [ -n "$GATE_PID" ] && kill -0 "$GATE_PID" 2>/dev/null; then
    echo "[cyclaw] stopping RAG gateway (pid $GATE_PID)..."
    kill "$GATE_PID" 2>/dev/null || true
    wait "$GATE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$REPO_DIR"

# Canonical telemetry/update-check block, exported into THIS shell so the
# server (and every child it spawns) inherits it BEFORE any interpreter
# starts -- including the bare `uvicorn gate:app` below, whose own module-level
# kill fires only after uvicorn's stack has loaded. Single source of truth:
# utils/telemetry_kill.py renders the lines; nothing here hand-copies a key.
# Positioned after the .env sourcing above so the canonical values overwrite
# any hostile dotenv value, mirroring apply_telemetry_kill()'s own overwrite
# semantics. Non-fatal on failure: every entry point re-applies at import.
# -S -E: the helper interpreter itself must not run site init (no
# sitecustomize/.pth auto-instrumentation hook can fire before the module
# emits the safe exports) and must ignore ambient PYTHONPATH. The module
# is stdlib-only and repo-local, so isolation costs nothing (Codex P1).
if _kill_env="$("$VENV_PY" -S -E -m utils.telemetry_kill --export shell 2>/dev/null)"; then
  eval "$_kill_env"
else
  echo "[cyclaw] warn : could not export telemetry-kill block (children still self-apply at import)" >&2
fi

# --- start RAG gateway (serves terminal.html) ---
# Stay on uvicorn so --gate-port / CYCLAW_GATE_PORT still bind. --no-proxy-headers
# matches gate._serve and the Dockerfile CMD: uvicorn defaults proxy_headers=True
# with forwarded_allow_ips 127.0.0.1, so a loopback peer could mint a fresh
# 60/min rate-limit bucket by varying X-Forwarded-For.
if "$VENV_PY" -c "import uvicorn" 2>/dev/null; then
  "$VENV_PY" -m uvicorn gate:app --host 127.0.0.1 --port "$GATE_PORT" --log-level warning --no-proxy-headers &
else
  echo "[cyclaw] error: uvicorn not available in $VENV_PY. Install deps first." >&2
  exit 1
fi
GATE_PID=$!
# Poll /health, but check the process is still alive on each pass. gate.py
# exits fast on a missing retrieval index, an already-bound port, or an
# invalid config -- polling only the socket let a gate that died on startup
# fall through silently: a browser opened on a dead port and the final wait
# blocked forever with no diagnostic. Surface the real cause instead.
GATE_READY=0
for i in 1 2 3 4 5; do
  if ! kill -0 "$GATE_PID" 2>/dev/null; then
    wait "$GATE_PID" 2>/dev/null || true
    # Cleared first so the EXIT trap's cleanup() does not try to kill a pid
    # that has already been reaped.
    GATE_PID=""
    echo "[cyclaw] error: RAG gateway exited during startup (port $GATE_PORT)." >&2
    echo "[cyclaw]        Common causes: the retrieval index is not built" >&2
    echo "[cyclaw]        (run '\"$VENV_PY\" -m retrieval.indexer'), port $GATE_PORT is" >&2
    echo "[cyclaw]        already in use, or config.yaml is invalid." >&2
    exit 1
  fi
  if curl -sf --max-time 2 "http://127.0.0.1:$GATE_PORT/health" >/dev/null 2>&1; then
    GATE_READY=1
    break
  fi
  sleep 0.4
done
# Still alive but not answering yet is normal on a cold start (the embedding
# model and index load lazily), so warn rather than abort.
if [ "$GATE_READY" -eq 0 ]; then
  echo "[cyclaw] warn : RAG gateway not answering /health yet; still starting (pid $GATE_PID)" >&2
fi

# --- open browser (best-effort) ---
if [ "$NO_BROWSER" -eq 0 ]; then
  (
    sleep 1.5
    if command -v open >/dev/null 2>&1; then
      open "http://127.0.0.1:$GATE_PORT"
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "http://127.0.0.1:$GATE_PORT" >/dev/null 2>&1
    fi
  ) &
  disown 2>/dev/null || true
fi

# Poll the gateway pid so a death after startup triggers cleanup and exits
# the script with the child's status. Do not use bash-4.3 wait-any here:
# macOS /bin/bash is 3.2.
CHILD_EXIT_STATUS=0
while true; do
  if ! kill -0 "$GATE_PID" 2>/dev/null; then
    echo "[cyclaw] RAG gateway process (pid $GATE_PID) exited" >&2
    if wait "$GATE_PID" 2>/dev/null; then
      CHILD_EXIT_STATUS=0
    else
      CHILD_EXIT_STATUS=$?
    fi
    GATE_PID=""
    break
  fi
  # Wait a bit; any signal still fires the cleanup trap.
  sleep 1
done
exit "$CHILD_EXIT_STATUS"
