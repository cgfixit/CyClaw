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
#   --print-pairing-url
#                     print the one-time console pairing URL to stdout (for a
#                     headless or SSH session; works with --no-browser). Without
#                     it the URL is printed only when stdout is a terminal and
#                     there is no desktop to open a browser on.
#   --repo PATH       explicit path to the CyClaw checkout (overrides $CYCLAW_REPO)

set -euo pipefail

GATE_PORT="${CYCLAW_GATE_PORT:-8787}"
NO_BROWSER=0
PRINT_PAIR_URL=0
REPO_OVERRIDE=""

# Validate a port before it is exported as CYCLAW_GATE_PORT and printed.
# Without this a typo ("--gate-port 87go") is echoed as a working-looking URL
# and then fails inside gate.main().
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
    --print-pairing-url)
      PRINT_PAIR_URL=1
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

# Port stays GATE_PORT / CYCLAW_GATE_PORT, not api.port. A missing runtime
# helper or unreadable config keeps the default URL; gate.py reports startup errors.
CONSOLE_URL="http://127.0.0.1:$GATE_PORT"
if CONSOLE_PROBE="$("$VENV_PY" "$REPO_DIR/utils/gateway_url.py" \
  "$REPO_DIR/config.yaml" --port "$GATE_PORT" 2>/dev/null)" && [ -n "$CONSOLE_PROBE" ]; then
  CONSOLE_URL="$CONSOLE_PROBE"
fi
SCHEME="${CONSOLE_URL%%:*}"

echo "[cyclaw] repo     : $REPO_DIR"
echo "[cyclaw] home     : $HOME_DIR"
echo "[cyclaw] terminal : $CONSOLE_URL  (RAG gateway / static/terminal.html)"
echo "[cyclaw] Ctrl+C stops the server"

# Load non-secret settings from dotenv, then secrets from Keychain into THIS
# process only. Secret lines in .env are scrubbed and never passed to gate.py.
# xtrace would dump every assignment — refuse rather than leak.
# shim + cyclaw() + a direct script all exec this file.
_INVOKE_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
_CYCLAW_SECRET_HELPER=""
for _cand in "$_INVOKE_DIR/cyclaw-keychain-load.sh" "$REPO_DIR/macos/cyclaw-keychain-load.sh"; do
  if [ -f "$_cand" ]; then
    _CYCLAW_SECRET_HELPER="$_cand"
    break
  fi
done
if [ -z "$_CYCLAW_SECRET_HELPER" ]; then
  echo "[cyclaw] error: cyclaw-keychain-load.sh not found beside the launcher or in $REPO_DIR/macos" >&2
  exit 1
fi
# shellcheck disable=SC1090
. "$_CYCLAW_SECRET_HELPER"

_remember_secret_preset
case "$-" in
  *x*) echo "[cyclaw] error: refusing to source .env with xtrace on (would print secrets). Re-run without bash -x." >&2; exit 1 ;;
esac
# Chained on the result, not `-f`: a refused HOME file must not shadow the repo copy.
# Secret names in either file are discarded; Keychain is the only secret source.
_source_dotenv "$HOME_DIR/.env" || _source_dotenv "$REPO_DIR/.env" || true
_load_os_secrets "$HOME_DIR/.env" "$REPO_DIR/.env" || exit 1

# The selected flag/env port also owns the printed URL; dotenv must not move
# only the child listener to a different port after that URL was resolved.
export CYCLAW_GATE_PORT="$GATE_PORT"

# First run on this Mac: no key in the Keychain yet. setup-cyclaw-keys.sh
# generates one (openssl rand -hex 20) and stores it without the value ever
# being an argv token; it is then loaded into this process like any other
# secret. It touches no shell profile and writes no dotenv file here.
if [ -z "${CYCLAW_API_KEY:-}" ] && [ "$(uname -s)" = "Darwin" ] && [ -f "$REPO_DIR/macos/setup-cyclaw-keys.sh" ]; then
  echo "[cyclaw] key  : no CYCLAW_API_KEY in the Keychain; generating one"
  if bash "$REPO_DIR/macos/setup-cyclaw-keys.sh" --skip-prompts --no-print-key --no-copy-key \
       --no-profile-edit --no-env-file --no-repo-env --repo-path "$REPO_DIR" >/dev/null; then
    _load_os_secrets "$HOME_DIR/.env" "$REPO_DIR/.env" || exit 1
  else
    echo "[cyclaw] warn : could not generate CYCLAW_API_KEY; run macos/setup-cyclaw-keys.sh by hand" >&2
  fi
fi

# First run on Linux: no Keychain, so the key lives in libsecret (secret-tool)
# or, without a usable keyring, in a 0600 file under $XDG_CONFIG_HOME/cyclaw.
# macos/cyclaw-linux-key.sh owns that contract. A key file it refuses (wrong
# owner or mode, symlink) stops the launcher rather than being overwritten.
if [ -z "${CYCLAW_API_KEY:-}" ] && [ "$(uname -s)" = "Linux" ]; then
  _CYCLAW_LINUX_KEY_HELPER=""
  for _cand in "$_INVOKE_DIR/cyclaw-linux-key.sh" "$REPO_DIR/macos/cyclaw-linux-key.sh"; do
    if [ -f "$_cand" ]; then
      _CYCLAW_LINUX_KEY_HELPER="$_cand"
      break
    fi
  done
  if [ -n "$_CYCLAW_LINUX_KEY_HELPER" ]; then
    # shellcheck disable=SC1090
    . "$_CYCLAW_LINUX_KEY_HELPER"
    _linux_key_rc=0
    cyclaw_linux_ensure_api_key || _linux_key_rc=$?
    if [ "$_linux_key_rc" -eq 2 ]; then
      exit 1
    fi
  else
    echo "[cyclaw] warn : cyclaw-linux-key.sh not found beside the launcher or in $REPO_DIR/macos; no API key was generated" >&2
  fi
fi

if [ -z "${CYCLAW_API_KEY:-}" ] && [ "$(uname -s)" = "Linux" ]; then
  echo "[cyclaw] warn : CYCLAW_API_KEY is not set and could not be stored in libsecret or $(printf '%s' "${XDG_CONFIG_HOME:-$HOME/.config}")/cyclaw/api-key. Soul / ops state-changing routes will 401." >&2
elif [ -z "${CYCLAW_API_KEY:-}" ]; then
  echo "[cyclaw] warn : CYCLAW_API_KEY is not in the Keychain (service com.cgfixit.cyclaw.api-key) and was not already set. Soul / ops state-changing routes will 401. Typing the key in the browser cannot configure the server. Re-run macos/setup-cyclaw-keys.sh; this launcher does not read that secret from .env." >&2
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
# starts -- including `gate.py` below, whose own module-level kill fires
# only after heavy imports have loaded. Single source of truth:
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
# gate.py, not `uvicorn gate:app`: only main() -> _serve() applies the
# loopback bind guard, api.tls certfile/keyfile, and proxy_headers=False.
# --gate-port / CYCLAW_GATE_PORT still bind because gate._listen_port reads
# the env this script already exported.
# One-time pairing code: the browser opens at #pair=<code> and trades it for
# the console cookie, so operator tools are unlocked without the key ever
# reaching the page (utils/console_session.py). gate.py takes the code out of
# its own environment at import; it is unset here once the gateway has it.
PAIR_CODE=""
if { [ "$NO_BROWSER" -eq 0 ] || [ "$PRINT_PAIR_URL" -eq 1 ]; } && [ -n "${CYCLAW_API_KEY:-}" ]; then
  PAIR_CODE="$("$VENV_PY" -S -E -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null || true)"
fi
if [ -n "$PAIR_CODE" ]; then
  export CYCLAW_CONSOLE_PAIRING_CODE="$PAIR_CODE"
fi
"$VENV_PY" gate.py &
GATE_PID=$!
unset CYCLAW_CONSOLE_PAIRING_CODE
# Poll /health, but check the process is still alive on each pass. gate.py
# exits fast on a missing retrieval index, an already-bound port, or an
# invalid config -- polling only the socket let a gate that died on startup
# fall through silently: a browser opened on a dead port and the final wait
# blocked forever with no diagnostic. Surface the real cause instead.
GATE_READY=0
for _ in 1 2 3 4 5; do
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
  if [ "$SCHEME" = "https" ]; then
    if curl -sfk --max-time 2 "$CONSOLE_URL/health" >/dev/null 2>&1; then
      GATE_READY=1
      break
    fi
  else
    if curl -sf --max-time 2 "$CONSOLE_URL/health" >/dev/null 2>&1; then
      GATE_READY=1
      break
    fi
  fi
  sleep 0.4
done
# Still alive but not answering yet is normal on a cold start (the embedding
# model and index load lazily), so warn rather than abort.
if [ "$GATE_READY" -eq 0 ]; then
  echo "[cyclaw] warn : RAG gateway not answering /health yet; still starting (pid $GATE_PID)" >&2
fi

# --- open browser (best-effort) ---
# `open` only on macOS: on Debian/Ubuntu `open` is openvt(1). xdg-open only
# with a desktop session; without DISPLAY/WAYLAND_DISPLAY it has nothing to
# open and the one-time link used to be lost on headless installs.
BROWSER_OPENER=""
if [ "$(uname -s)" = "Darwin" ] && command -v open >/dev/null 2>&1; then
  BROWSER_OPENER="open"
elif command -v xdg-open >/dev/null 2>&1 && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
  BROWSER_OPENER="xdg-open"
fi

# The pairing URL carries a one-time secret (single use, short TTL; see
# utils/console_session.py). Print it only on explicit request or to an
# interactive terminal with no browser to hand it to -- never to stderr or a
# log, so it does not land in the journal, nohup.out, or CI output.
if [ -n "$PAIR_CODE" ]; then
  if [ "$PRINT_PAIR_URL" -eq 1 ] || { [ -t 1 ] && [ "$NO_BROWSER" -eq 0 ] && [ -z "$BROWSER_OPENER" ]; }; then
    if [ "$PRINT_PAIR_URL" -eq 1 ] && [ ! -t 1 ]; then
      echo "[cyclaw] warn : --print-pairing-url with stdout not a terminal; the one-time pairing link is going to a pipe or file. Delete any copy once paired." >&2
    fi
    echo "[cyclaw] pair : ${CONSOLE_URL%/}/#pair=$PAIR_CODE  (one-time link; open it in a browser that can reach this machine)"
  fi
fi

if [ "$NO_BROWSER" -eq 0 ] && [ -n "$BROWSER_OPENER" ]; then
  (
    sleep 1.5
    OPEN_URL="$CONSOLE_URL"
    if [ -n "$PAIR_CODE" ]; then
      OPEN_URL="${CONSOLE_URL%/}/#pair=$PAIR_CODE"
    fi
    if [ "$BROWSER_OPENER" = "open" ]; then
      open "$OPEN_URL"
    else
      xdg-open "$OPEN_URL" >/dev/null 2>&1
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
