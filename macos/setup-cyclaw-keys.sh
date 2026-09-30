#!/usr/bin/env bash
# Bootstrap CyClaw API keys on macOS Apple Silicon.
#
# Autogenerates CYCLAW_API_KEY (openssl rand -hex 20 — the value setup-guide.md
# and README document) and prompts for the operator-supplied tokens CyClaw
# cannot invent: Telegram, Claude (ANTHROPIC_API_KEY — llm/client.py never
# reads CLAUDE_API_KEY), Grok, and GitHub. Skip is allowed on every prompt.
#
# Persistence (survives reboot; matches macos/ conventions + cyclaw-privacy):
#   1. ~/.CyClaw/.env stays the default home for ordinary settings (ports,
#      paths, mode flags, model names, feature toggles). Mode 600. The rc
#      block sources that file. Secret-classified names are not exported.
#   2. Secrets go to the macOS Keychain. launchd and invoke-cyclaw.sh read
#      them just in time into the cyclaw process. Classification (allowlist
#      plus *_API_KEY / *_TOKEN / *_SECRET / *_PASSWORD) is
#      macos/cyclaw-public-env.sh. This script does not write those names
#      into .env unless --write-env-file is set.
#   3. An existing allowlisted secret line is copied into Keychain (if that
#      item is missing) and then removed. Other lines stay. No backup file
#      is written. A pattern match with no Keychain service is left in place.
#
# Keychain store never puts a secret on `security`'s argv (same contract as
# cyclaw-keychain-set.sh): generated / typed values go through a 0600 temp
# file and /usr/bin/expect, or a TTY prompt. `ps` cannot see them.
#
# Usage:
#   bash macos/setup-cyclaw-keys.sh
#   bash macos/setup-cyclaw-keys.sh --skip-prompts --no-print-key
#   bash macos/setup-cyclaw-keys.sh --rotate --skip-prompts --fill-browser
#   bash macos/setup-cyclaw-keys.sh --schedule-rotate monthly
#   cyclaw                       # invoke reads Keychain into that process
#
# Options:
#   --rotate            replace an existing CYCLAW_API_KEY
#   --skip-prompts      no Telegram/Claude/Grok/GitHub prompts (autogen only)
#   --grok-dummy        set GROK_API_KEY=dummy (offline / pytest)
#   --no-keychain       skip Keychain (not recommended; launchd will 401)
#   --write-env-file    OPT-IN: also write secret lines into the dotenv
#                       (mode 600). Loud warning. Launchers and the rc block
#                       still do not export those lines. Default is Keychain.
#   --no-env-file       do not create or refresh ~/.CyClaw/.env. Existing
#                       allowlisted secret lines are still moved to Keychain.
#   --no-repo-env       do not write secret lines into a checkout .env
#   --no-profile-edit   do not touch the cyclaw() installer block. The keys
#                       block is still rewritten so it cannot export secrets.
#   --no-print-key      do not print the generated CYCLAW_API_KEY
#   --print-key         print it (default when a new key is generated)
#   --copy-key          put CYCLAW_API_KEY on the pasteboard (pbcopy; not argv)
#   --no-copy-key       do not touch the pasteboard
#   --clipboard-ttl N   clear the pasteboard after N seconds if it still holds
#                       the key (default 90; 0 = leave it)
#   --open-consoles     open the loopback RAG console
#   --fill-browser      inject the key into #apiKeyInput on
#                       127.0.0.1 only (never localStorage / never a cookie —
#                       that is the console contract). Implies --open-consoles
#                       and --copy-key.
#   --schedule-rotate monthly|weekly|never
#                       write (never load) a LaunchAgent that re-runs
#                       --rotate --skip-prompts --no-print-key. Prints the
#                       launchctl bootstrap command.
#   --unschedule-rotate bootout + delete that LaunchAgent
#   --restart-servers   after a successful write, best-effort free the
#                       configured gate loopback port so a stale
#                       process is not still holding the old CYCLAW_API_KEY.
#                       Does not start the servers (open a new shell + cyclaw).
#   --gate-port PORT    RAG console (default 8787 / CYCLAW_GATE_PORT)
#   --repo-path PATH    CyClaw checkout. Plaintext .env only with --write-env-file.
#   --help
#
# Target: macOS 14+ Apple Silicon (arm64), bash 3.2 / zsh, BSD userland.
# No Homebrew required. Tests set CYCLAW_SETUP_KEYS_SKIP_PLATFORM=1.
#
# Privacy (cyclaw-privacy): never log secret values, never write them to
# config.yaml, never put them in argv of a child we do not control. step()
# messages name services and variable names only.

set -euo pipefail

case "$-" in
  *x*)
    echo "[cyclaw] error: refusing to run with xtrace on (would print secrets). Re-run without bash -x." >&2
    exit 1
    ;;
esac

usage() {
  awk 'NR>=3 && /^#/ { sub(/^# ?/, ""); print; next } NR>=3 { exit }' "$0"
}

step() { printf '[cyclaw] %s\n' "$1"; }
warn() { printf '[cyclaw] WARNING: %s\n' "$1" >&2; }

# Documented Keychain service names (telegram + generate_service_plist.py)
# plus matching com.cgfixit.cyclaw.* names for the other env vars.
KC_API="com.cgfixit.cyclaw.api-key"
KC_TELEGRAM="com.cgfixit.cyclaw.telegram-bot-token"
KC_GROK="com.cgfixit.cyclaw.grok-api-key"
KC_ANTHROPIC="com.cgfixit.cyclaw.anthropic-api-key"
KC_GH="com.cgfixit.cyclaw.gh-token"

ROTATE=0
SKIP_PROMPTS=0
GROK_DUMMY=0
DO_KEYCHAIN=1
WRITE_ENV_FILE=0
NO_ENV_FILE=0
NO_REPO_ENV=0
DO_PUBLIC_ENV=1
DO_ENV_FILE=0
DO_REPO_ENV=0
DO_PROFILE=1
REPO_PATH_EXPLICIT=0
PRINT_KEY="auto"
COPY_KEY="auto"
CLIP_TTL=90
OPEN_CONSOLES=0
FILL_BROWSER=0
SCHEDULE_ROTATE=""
UNSCHEDULE_ROTATE=0
RESTART_SERVERS=0
GATE_PORT="${CYCLAW_GATE_PORT:-8787}"
REPO_PATH=""

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
    --rotate) ROTATE=1; shift ;;
    --skip-prompts|--yes) SKIP_PROMPTS=1; shift ;;
    --grok-dummy) GROK_DUMMY=1; shift ;;
    --no-keychain) DO_KEYCHAIN=0; shift ;;
    --write-env-file) WRITE_ENV_FILE=1; shift ;;
    --no-env-file) NO_ENV_FILE=1; shift ;;
    --no-repo-env) NO_REPO_ENV=1; shift ;;
    --no-profile-edit) DO_PROFILE=0; shift ;;
    --no-print-key) PRINT_KEY="never"; shift ;;
    --print-key) PRINT_KEY="always"; shift ;;
    --copy-key) COPY_KEY="always"; shift ;;
    --no-copy-key) COPY_KEY="never"; shift ;;
    --clipboard-ttl)
      CLIP_TTL="${2:?--clipboard-ttl requires a value}"
      case "$CLIP_TTL" in
        ''|*[!0-9]*)
          echo "--clipboard-ttl requires a non-negative integer (got '$CLIP_TTL')" >&2
          exit 1
          ;;
      esac
      shift 2
      ;;
    --open-consoles) OPEN_CONSOLES=1; shift ;;
    --fill-browser) FILL_BROWSER=1; OPEN_CONSOLES=1; COPY_KEY="always"; shift ;;
    --schedule-rotate)
      SCHEDULE_ROTATE="${2:?--schedule-rotate requires monthly, weekly, or never}"
      shift 2
      ;;
    --unschedule-rotate) UNSCHEDULE_ROTATE=1; shift ;;
    --restart-servers) RESTART_SERVERS=1; shift ;;
    --gate-port)
      GATE_PORT="${2:?--gate-port requires a value}"
      shift 2
      ;;
    --repo-path) REPO_PATH="${2:?--repo-path requires a value}"; REPO_PATH_EXPLICIT=1; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

require_port "gate port (--gate-port / CYCLAW_GATE_PORT)" "$GATE_PORT"

# Non-secret settings stay in ~/.CyClaw/.env. Secret lines are opt-in.
# --no-env-file / --no-repo-env still win if both are set.
if [ "$WRITE_ENV_FILE" -eq 1 ]; then
  DO_ENV_FILE=1
  DO_REPO_ENV=1
fi
if [ "$NO_ENV_FILE" -eq 1 ]; then
  DO_ENV_FILE=0
  DO_PUBLIC_ENV=0
fi
if [ "$NO_REPO_ENV" -eq 1 ]; then
  DO_REPO_ENV=0
fi
if [ "$DO_ENV_FILE" -eq 1 ] || [ "$DO_REPO_ENV" -eq 1 ]; then
  warn "PLAINTEXT OPT-IN: --write-env-file stores secrets in a dotenv file."
  warn "The file is mode 600, and it is still plaintext on disk."
  warn "The rc block and invoke-cyclaw.sh do not export those secret lines. Prefer Keychain (the default)."
fi

case "$SCHEDULE_ROTATE" in
  ""|monthly|weekly|never) ;;
  *)
    echo "[cyclaw] --schedule-rotate accepts monthly, weekly, or never (got '$SCHEDULE_ROTATE')" >&2
    exit 1
    ;;
esac

# -- platform -----------------------------------------------------------------

_require_platform() {
  if [ "${CYCLAW_SETUP_KEYS_SKIP_PLATFORM:-}" = "1" ]; then
    return 0
  fi
  if [ "$(uname -s)" != "Darwin" ]; then
    echo "[cyclaw] this script is for macOS Apple Silicon only (uname -s is $(uname -s))." >&2
    exit 1
  fi
  if [ "$(uname -m)" != "arm64" ]; then
    echo "[cyclaw] Apple Silicon (arm64) required; this Mac reports $(uname -m)." >&2
    echo "[cyclaw] Intel Macs cannot satisfy CyClaw's pinned torch wheel. See setup-guide.md." >&2
    exit 1
  fi
  local ver major
  ver="$(sw_vers -productVersion 2>/dev/null || true)"
  major="${ver%%.*}"
  if [ -n "$major" ] && [ "$major" -lt 14 ] 2>/dev/null; then
    warn "macOS 14 Sonoma is the CyClaw floor (detected ${ver}). Continuing anyway."
  fi
}

_require_platform

if [ "$UNSCHEDULE_ROTATE" -eq 1 ] && [ ! -t 0 ]; then
  SKIP_PROMPTS=1
fi

if [ "$SKIP_PROMPTS" -eq 0 ] && [ ! -t 0 ]; then
  echo "[cyclaw] interactive prompts need a TTY. Re-run in a terminal, or pass --skip-prompts." >&2
  exit 1
fi

# -- paths --------------------------------------------------------------------

# $0 is reliable when invoked as `bash path/to/script`; CDPATH must not
# hijack `cd` (same class of footgun install-cyclaw.sh documents).
_SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -f "$_SCRIPT_DIR/cyclaw-public-env.sh" ]; then
  # shellcheck disable=SC1091
  . "$_SCRIPT_DIR/cyclaw-public-env.sh"
else
  echo "[cyclaw] error: cyclaw-public-env.sh is not beside setup-cyclaw-keys.sh" >&2
  exit 1
fi
HOME_DIR="${CYCLAW_HOME:-$HOME/.CyClaw}"
ACCOUNT="$(id -un)"

reject_shell_metachars() {
  case "$1" in
    *'"'*|*\`*|*'$'*|*\\*)
      echo "cyclaw: refusing a path containing shell metacharacters (\", \`, \$, or \\): $1" >&2
      exit 1
      ;;
  esac
}

_looks_like_repo() {
  [ -f "$1/gate.py" ]
}

REPO_DIR=""
_find_repo() {
  local cand
  if [ -n "$REPO_PATH" ]; then
    if ! _looks_like_repo "$REPO_PATH"; then
      echo "--repo-path '$REPO_PATH' does not look like a CyClaw checkout (missing gate.py)." >&2
      exit 1
    fi
    REPO_DIR="$(CDPATH= cd -- "$REPO_PATH" && pwd)"
    reject_shell_metachars "$REPO_DIR"
    return 0
  fi
  for cand in \
    "${CYCLAW_REPO:-}" \
    "$PWD" \
    "$_SCRIPT_DIR/.." \
    "$HOME_DIR/repo"
  do
    [ -n "$cand" ] || continue
    [ -d "$cand" ] || continue
    if _looks_like_repo "$cand"; then
      REPO_DIR="$(CDPATH= cd -- "$cand" && pwd)"
      reject_shell_metachars "$REPO_DIR"
      return 0
    fi
  done
  return 0
}

_find_repo

mkdir -p "$HOME_DIR"
chmod 700 "$HOME_DIR" 2>/dev/null || true
HOME_DIR="$(CDPATH= cd -- "$HOME_DIR" && pwd)"
reject_shell_metachars "$HOME_DIR"
ENV_FILE="$HOME_DIR/.env"

# -- quoting / dotenv ---------------------------------------------------------

# Single-quote for a POSIX assignment. 'foo'bar' -> 'foo'\''bar'
_shell_single_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

_validate_secret() {
  case "$1" in
    "") return 1 ;;
    *$'\n'*|*$'\r'*) return 1 ;;
  esac
  return 0
}

# Rewrite one KEY= assignment in a dotenv file. Never prints the value.
# Accepts both `KEY=` and `export KEY=` forms on the way in; writes `export`.
_env_upsert() {
  local file="$1" key="$2" value="$3" tmp quoted old_umask
  if ! _validate_secret "$value"; then
    echo "[cyclaw] refusing to store an empty or multi-line value for $key" >&2
    return 1
  fi
  quoted="$(_shell_single_quote "$value")"
  old_umask="$(umask)"
  umask 077
  tmp="$(mktemp "${TMPDIR:-/tmp}/cyclaw.env.XXXXXX")"
  if [ -f "$file" ]; then
    # grep -v returns 1 when every line matches (empty result) — do not trip set -e.
    grep -v -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" > "$tmp" || true
  else
    printf '%s\n' "# CyClaw secrets — chmod 600. Managed by macos/setup-cyclaw-keys.sh." > "$tmp"
    printf '%s\n' "# Do not commit. Do not copy into config.yaml. Do not paste into chat logs." >> "$tmp"
  fi
  printf 'export %s=%s\n' "$key" "$quoted" >> "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file"
  umask "$old_umask"
}

_env_has() {
  local file="$1" key="$2"
  [ -f "$file" ] || return 1
  grep -E -q "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" 2>/dev/null
}

# Inverse of _shell_single_quote. Also accepts a bare token or one pair of
# double quotes (we never write those, but a hand-edited .env might have them).
_env_unquote() {
  local raw="$1" inner
  case "$raw" in
    \'*\')
      inner="${raw#\'}"
      inner="${inner%\'}"
      # Remaining '\'' is the encoding _shell_single_quote writes for `'`.
      printf '%s' "$inner" | sed "s/'\\\\''/'/g"
      ;;
    \"*\")
      inner="${raw#\"}"
      inner="${inner%\"}"
      printf '%s' "$inner"
      ;;
    *)
      printf '%s' "$raw"
      ;;
  esac
}

# Extract a KEY's value from a dotenv we wrote (export KEY='...').
# Only used to sync an existing .env into Keychain. Never echoed.
_env_get() {
  local file="$1" key="$2" line
  [ -f "$file" ] || return 1
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" | tail -n 1)" || return 1
  line="${line#*=}"
  _env_unquote "$line"
}

# -- Keychain -----------------------------------------------------------------

_SECURITY_BIN=""
_KEYCHAIN_READ_STATE=""
_KEYCHAIN_READ_VALUE=""
_KEYCHAIN_READ_RC=0

_resolve_security() {
  if [ -n "$_SECURITY_BIN" ]; then
    return 0
  fi
  if [ "${CYCLAW_SETUP_KEYS_SKIP_PLATFORM:-}" = "1" ] && [ "${CYCLAW_SETUP_KEYS_STDIN_STORE:-}" = "1" ]; then
    # Test harness only: permit its fake security(1) to come from PATH.
    _SECURITY_BIN="$(command -v security 2>/dev/null || true)"
  elif [ -x /usr/bin/security ]; then
    _SECURITY_BIN="/usr/bin/security"
  else
    _SECURITY_BIN="$(command -v security 2>/dev/null || true)"
  fi
  [ -n "$_SECURITY_BIN" ]
}

_keychain_read() {
  local service="$1" value="" rc=0
  _KEYCHAIN_READ_STATE=""
  _KEYCHAIN_READ_VALUE=""
  _KEYCHAIN_READ_RC=0

  if ! _resolve_security; then
    _KEYCHAIN_READ_STATE="tool_error"
    _KEYCHAIN_READ_RC=127
    return 1
  fi

  # Attribute lookup proves presence without requesting secret data or
  # triggering the item's read ACL. Only a genuine not-found result may fall
  # through to another source or key generation.
  if "$_SECURITY_BIN" find-generic-password -a "$ACCOUNT" -s "$service" >/dev/null 2>&1; then
    :
  else
    rc=$?
    _KEYCHAIN_READ_RC="$rc"
    if [ "$rc" -eq 44 ]; then
      _KEYCHAIN_READ_STATE="missing"
    else
      _KEYCHAIN_READ_STATE="tool_error"
    fi
    return 1
  fi

  if value="$("$_SECURITY_BIN" find-generic-password -a "$ACCOUNT" -s "$service" -w 2>/dev/null)"; then
    if [ -z "$value" ]; then
      _KEYCHAIN_READ_STATE="empty"
      return 1
    fi
    _KEYCHAIN_READ_STATE="readable"
    _KEYCHAIN_READ_VALUE="$value"
    return 0
  else
    rc=$?
    _KEYCHAIN_READ_STATE="unreadable"
    _KEYCHAIN_READ_RC="$rc"
    return 1
  fi
}

# Store the contents of a 0600 file as a generic password. The secret is
# never an argv token of `security` (bare `-w`, same as cyclaw-keychain-set.sh).
_keychain_store_file() {
  local service="$1" secret_file="$2"
  if [ ! -f "$secret_file" ]; then
    echo "[cyclaw] internal: missing secret file for $service" >&2
    return 1
  fi

  # Test / CI path: the fake `security` stub reads stdin after a bare -w.
  if [ "${CYCLAW_SETUP_KEYS_STDIN_STORE:-}" = "1" ]; then
    "$_SECURITY_BIN" add-generic-password -a "$ACCOUNT" -s "$service" -T /usr/bin/security -U -w < "$secret_file"
    return $?
  fi

  if [ -x /usr/bin/expect ]; then
    # expect reads the secret from the file (not its own argv) and types it
    # into security's TTY prompt. log_user 0 keeps it off the transcript.
    /usr/bin/expect <<EXPECT_EOF
set timeout 30
set fh [open "$secret_file" r]
set secret [read -nonewline \$fh]
close \$fh
log_user 0
spawn -noecho /usr/bin/security add-generic-password -a "$ACCOUNT" -s "$service" -T /usr/bin/security -U -w
expect {
  -re {(?i)password} { send -- "\$secret\r"; exp_continue }
  eof
}
catch wait result
exit [lindex \$result 3]
EXPECT_EOF
    return $?
  fi

  if [ -x "$_SCRIPT_DIR/cyclaw-keychain-set.sh" ] && [ -t 0 ]; then
    warn "expect not found; falling back to interactive Keychain prompt for $service"
    "$_SCRIPT_DIR/cyclaw-keychain-set.sh" "$service"
    return $?
  fi

  warn "could not store service=$service in Keychain (no expect, no TTY); aborting before dotenv write"
  return 1
}

_keychain_store_value() {
  local service="$1" value="$2" tmp rc old_umask
  old_umask="$(umask)"
  umask 077
  tmp="$(mktemp "${TMPDIR:-/tmp}/cyclaw.kc.XXXXXX")"
  # Cleartext secret lives in $tmp until `security` reads it below. The
  # straight-line `rm -f` covers the success path only, and
  # _keychain_store_file can sit on a Keychain unlock prompt indefinitely --
  # a Ctrl-C there used to leave the key behind in $TMPDIR forever. Same trap
  # idiom as _fill_browser; bash runs an EXIT trap on SIGINT too.
  trap 'rm -f "$tmp"' EXIT
  printf '%s' "$value" > "$tmp"
  chmod 600 "$tmp"
  umask "$old_umask"
  rc=0
  _keychain_store_file "$service" "$tmp" || rc=$?
  rm -f "$tmp"
  trap - EXIT
  return "$rc"
}

# -- persist one secret -------------------------------------------------------

# Tracks names we actually wrote (never values) for the closing summary.
_STORED_NAMES=""
_NOTE() { _STORED_NAMES="${_STORED_NAMES}${_STORED_NAMES:+ }$1"; }
# Names stored in Keychain on this run. Migration strips their plaintext
# lines without a second Keychain read.
_PERSISTED_NAMES=""
_mark_persisted() { _PERSISTED_NAMES="${_PERSISTED_NAMES} $1"; }

_persist() {
  local env_name="$1" service="$2" value="$3" extra="${4:-}"
  if ! _validate_secret "$value"; then
    echo "[cyclaw] refusing empty/multi-line value for $env_name" >&2
    return 1
  fi

  if [ "$DO_KEYCHAIN" -eq 1 ]; then
    if ! _resolve_security; then
      warn "security(1) is unavailable; refusing to persist $env_name only to dotenv"
      return 1
    fi
    if ! _keychain_store_value "$service" "$value"; then
      warn "Keychain store failed for $env_name (service=$service); dotenv files were not changed"
      return 1
    fi
    step "Keychain: stored $env_name (service=$service account=$ACCOUNT)"
    _mark_persisted "$env_name"
    if [ -n "$extra" ]; then
      _mark_persisted "$extra"
    fi
  fi

  if [ "$DO_ENV_FILE" -eq 1 ]; then
    _env_upsert "$ENV_FILE" "$env_name" "$value"
    if [ -n "$extra" ]; then
      _env_upsert "$ENV_FILE" "$extra" "$value"
    fi
    step "wrote $env_name to $ENV_FILE (mode 600)"
  fi

  if [ "$DO_REPO_ENV" -eq 1 ] && [ -n "$REPO_DIR" ]; then
    _env_upsert "$REPO_DIR/.env" "$env_name" "$value"
    if [ -n "$extra" ]; then
      _env_upsert "$REPO_DIR/.env" "$extra" "$value"
    fi
    step "wrote $env_name to $REPO_DIR/.env (gitignored, mode 600)"
  fi

  # Current process only. A non-sourced run cannot export into the parent
  # tab — invoke-cyclaw.sh reads Keychain into the gateway process.
  export "${env_name}=${value}"
  if [ -n "$extra" ]; then
    export "${extra}=${value}"
  fi
  _NOTE "$env_name"
}

# -- rc source block + plaintext migration ------------------------------------

KEYS_START="# >>> cyclaw keys >>>"
KEYS_END="# <<< cyclaw keys <<<"

# The rc block loads non-secret settings from the dotenv. It must not be a
# raw `. .env`, which would export secret lines into every shell.
# --no-profile-edit does not skip this rewrite. A half-written block is left
# untouched and fails the run: deleting up to a missing end marker would eat
# the rest of the rc file.
_keys_rc_targets() {
  printf '%s\n' "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile" "$HOME/.bashrc"
}

_keys_rc_malformed() {
  local rc bad=0
  while IFS= read -r rc; do
    [ -f "$rc" ] || continue
    if grep -qxF "$KEYS_START" "$rc" 2>/dev/null; then
      if ! grep -qxF "$KEYS_END" "$rc" 2>/dev/null; then
        echo "[cyclaw] malformed cyclaw keys block in $rc (start without end); left unchanged" >&2
        bad=1
      fi
    elif grep -qxF "$KEYS_END" "$rc" 2>/dev/null; then
      echo "[cyclaw] malformed cyclaw keys block in $rc (end without start); left unchanged" >&2
      bad=1
    fi
  done < <(_keys_rc_targets)
  [ "$bad" -eq 0 ]
}

_strip_keys_rc_block() {
  local rc="$1" tmp
  grep -qxF "$KEYS_START" "$rc" 2>/dev/null || return 0
  tmp="$(mktemp "${TMPDIR:-/tmp}/cyclaw.rc.XXXXXX")"
  awk -v s="$KEYS_START" -v e="$KEYS_END" '
    $0 == s { skip = 1; next }
    skip && $0 == e { skip = 0; next }
    !skip { print }
  ' "$rc" > "$tmp"
  mv "$tmp" "$rc"
}

detect_rc_file() {
  case "${SHELL:-}" in
    */zsh) printf '%s\n' "$HOME/.zshrc" ;;
    *)
      if [ "$(uname -s)" = "Darwin" ]; then
        local candidate
        for candidate in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
          if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
          fi
        done
        printf '%s\n' "$HOME/.bash_profile"
      elif [ -f "$HOME/.bash_profile" ]; then
        printf '%s\n' "$HOME/.bash_profile"
      else
        printf '%s\n' "$HOME/.bashrc"
      fi
      ;;
  esac
}

_install_keys_rc_block() {
  local rc="$1" helper
  helper="$HOME_DIR/bin/cyclaw-public-env.sh"
  reject_shell_metachars "$helper"
  reject_shell_metachars "$ENV_FILE"
  [ -f "$rc" ] || touch "$rc"
  {
    echo ""
    echo "$KEYS_START"
    echo "# Non-secret CyClaw settings only. Secret-classified names are not exported."
    echo "if [ -f \"$helper\" ]; then"
    echo "  . \"$helper\""
    echo "  cyclaw_source_public_env \"$ENV_FILE\" || true"
    echo "fi"
    echo "$KEYS_END"
  } >> "$rc"
  step "rc source block loads non-secret settings from $ENV_FILE ($rc)"
}

_ensure_keys_rc_blocks() {
  local rc primary
  # --no-profile-edit is accepted and does not skip this rewrite. Leaving a
  # raw source of the dotenv would keep exporting secrets into every shell.
  if [ "$DO_PROFILE" -eq 0 ]; then
    echo "[cyclaw] note : --no-profile-edit does not skip the keys rc rewrite" >&2
  fi
  _keys_rc_malformed || return 1
  while IFS= read -r rc; do
    [ -f "$rc" ] || continue
    if grep -qxF "$KEYS_START" "$rc" 2>/dev/null; then
      _strip_keys_rc_block "$rc"
      step "replaced cyclaw keys source block in $rc (secrets are not exported)"
    fi
  done < <(_keys_rc_targets)
  primary="$(detect_rc_file)"
  _install_keys_rc_block "$primary"
}

_name_was_persisted() {
  case " ${_PERSISTED_NAMES} " in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

# Delete one KEY= line. Non-secret lines and comments stay. Never prints
# the value. Never writes a backup. The file itself stays: it is the home
# for ordinary settings even after the last secret line is removed.
_env_remove_key() {
  local file="$1" key="$2" tmp old_umask
  [ -f "$file" ] || return 0
  _env_has "$file" "$key" || return 0
  old_umask="$(umask)"
  umask 077
  tmp="$(mktemp "${TMPDIR:-/tmp}/cyclaw.env.XXXXXX")"
  grep -v -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" > "$tmp" || true
  if ! grep -q '[^[:space:]]' "$tmp"; then
    cyclaw_public_env_header > "$tmp"
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file"
  umask "$old_umask"
}

_migrate_one_line() {
  local file="$1" env_name="$2" service="$3" value=""
  _env_has "$file" "$env_name" || return 0
  if [ "$DO_KEYCHAIN" -ne 1 ]; then
    warn "left plaintext $env_name in $file (--no-keychain). Launchers will not load it."
    return 0
  fi
  if _name_was_persisted "$env_name"; then
    _env_remove_key "$file" "$env_name"
    step "removed plaintext $env_name from $file (Keychain $service holds it). No backup was written."
    return 0
  fi
  if _keychain_read "$service"; then
    _KEYCHAIN_READ_VALUE=""
    _env_remove_key "$file" "$env_name"
    step "removed plaintext $env_name from $file (Keychain $service already holds it). No backup was written."
    return 0
  fi
  case "$_KEYCHAIN_READ_STATE" in
    missing)
      value="$(_env_get "$file" "$env_name")"
      if ! _validate_secret "$value"; then
        warn "left plaintext $env_name in $file (value empty or multi-line; not stored)"
        value=""
        return 0
      fi
      if ! _keychain_store_value "$service" "$value"; then
        warn "left plaintext $env_name in $file (Keychain store failed; the file is still the only copy)"
        value=""
        return 0
      fi
      value=""
      _mark_persisted "$env_name"
      _env_remove_key "$file" "$env_name"
      step "moved $env_name from $file into Keychain ($service) and removed the plaintext line. No backup was written."
      ;;
    *)
      warn "left plaintext $env_name in $file (Keychain $service is ${_KEYCHAIN_READ_STATE:-unreadable}; not deleting the only readable copy)"
      ;;
  esac
}

# Pattern matches that are not on the Keychain allowlist stay on disk.
# Deleting them would destroy the only copy. Launchers still do not load them.
_warn_unmapped_secret_lines() {
  local file="$1" line name
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    name="$(cyclaw_dotenv_assignment_name "$line" 2>/dev/null)" || continue
    [ -n "$name" ] || continue
    cyclaw_is_secret_name "$name" || continue
    case "$name" in
      CYCLAW_API_KEY|TELEGRAM_BOT_TOKEN|GROK_API_KEY|ANTHROPIC_API_KEY|GH_TOKEN|GITHUB_TOKEN|CLAUDE_API_KEY)
        continue
        ;;
    esac
    warn "left plaintext $name in $file (secret-classified, no Keychain service). Launchers do not load it. The value was not printed."
  done < "$file"
}

_warn_if_token_pair_differs() {
  local file="$1" gh="" gh2=""
  _env_has "$file" "GH_TOKEN" || return 0
  _env_has "$file" "GITHUB_TOKEN" || return 0
  gh="$(_env_get "$file" "GH_TOKEN")"
  gh2="$(_env_get "$file" "GITHUB_TOKEN")"
  if [ "$gh" != "$gh2" ]; then
    warn "GH_TOKEN and GITHUB_TOKEN differ in $file; the Keychain copy follows GH_TOKEN. Values were not printed."
  fi
  gh=""
  gh2=""
}

_repo_secret_file_in_scope() {
  [ -n "$REPO_DIR" ] || return 1
  [ "$REPO_PATH_EXPLICIT" -eq 1 ] || [ "$REPO_DIR" = "$HOME_DIR/repo" ]
}

# Copy leftover secret lines into Keychain, then delete them. Opt-in
# --write-env-file keeps the lines. A checkout .env is touched only for an
# explicit --repo-path or the install layout ~/.CyClaw/repo — never an
# incidental current directory.
_migrate_plaintext_secrets() {
  local file keep
  _migrate_file() {
    file="$1"
    keep="$2"
    [ -f "$file" ] || return 0
    if [ "$keep" -eq 1 ]; then
      return 0
    fi
    _warn_if_token_pair_differs "$file"
    _migrate_one_line "$file" "CYCLAW_API_KEY" "$KC_API"
    _migrate_one_line "$file" "TELEGRAM_BOT_TOKEN" "$KC_TELEGRAM"
    _migrate_one_line "$file" "GROK_API_KEY" "$KC_GROK"
    _migrate_one_line "$file" "ANTHROPIC_API_KEY" "$KC_ANTHROPIC"
    _migrate_one_line "$file" "GH_TOKEN" "$KC_GH"
    _migrate_one_line "$file" "GITHUB_TOKEN" "$KC_GH"
    if _env_has "$file" "CLAUDE_API_KEY"; then
      warn "left CLAUDE_API_KEY in $file. llm/client.py reads ANTHROPIC_API_KEY; this unused name is not loaded and was not copied."
    fi
    _warn_unmapped_secret_lines "$file"
  }
  _migrate_file "$ENV_FILE" "$DO_ENV_FILE"
  if [ -n "$REPO_DIR" ] && { [ "$REPO_PATH_EXPLICIT" -eq 1 ] || [ "$REPO_DIR" = "$HOME_DIR/repo" ]; }; then
    _migrate_file "$REPO_DIR/.env" "$DO_REPO_ENV"
  fi
}

_ensure_public_env_file() {
  local old_umask
  [ "$DO_PUBLIC_ENV" -eq 1 ] || return 0
  if [ -f "$ENV_FILE" ]; then
    chmod 600 "$ENV_FILE" 2>/dev/null || true
    return 0
  fi
  old_umask="$(umask)"
  umask 077
  cyclaw_public_env_header > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  umask "$old_umask"
  step "created $ENV_FILE for non-secret settings (mode 600; secrets stay in the Keychain)"
}

_refresh_installed_launchers() {
  local name src dest
  mkdir -p "$HOME_DIR/bin"
  for name in invoke-cyclaw.sh cyclaw-keychain-load.sh cyclaw-keychain-env.sh cyclaw-public-env.sh; do
    src="$_SCRIPT_DIR/$name"
    dest="$HOME_DIR/bin/$name"
    [ -f "$src" ] || continue
    [ "$src" = "$dest" ] && continue
    if [ ! -f "$dest" ] || ! cmp -s "$src" "$dest" 2>/dev/null; then
      cp "$src" "$dest"
      chmod 755 "$dest"
      step "updated $dest"
    fi
  done
}

ROTATE_LABEL="com.cgfixit.cyclaw.keys-rotate"
ROTATE_PLIST="$HOME/Library/LaunchAgents/${ROTATE_LABEL}.plist"

_install_self() {
  local dest="$HOME_DIR/bin/setup-cyclaw-keys.sh" src
  src="${BASH_SOURCE[0]:-$0}"
  mkdir -p "$HOME_DIR/bin"
  if [ ! -f "$dest" ] || ! cmp -s "$src" "$dest" 2>/dev/null; then
    cp "$src" "$dest"
  fi
  chmod 755 "$dest"
  reject_shell_metachars "$dest"
  printf '%s' "$dest"
}

_unschedule_rotate() {
  local uid dest
  uid="$(id -u 2>/dev/null || echo 0)"
  dest="$ROTATE_PLIST"
  if [ "$(uname -s)" = "Darwin" ] && command -v launchctl >/dev/null 2>&1; then
    launchctl bootout "gui/${uid}/${ROTATE_LABEL}" 2>/dev/null || true
  fi
  if [ -f "$dest" ]; then
    rm -f "$dest"
    step "removed LaunchAgent $ROTATE_LABEL"
  else
    step "no $ROTATE_LABEL LaunchAgent on disk"
  fi
}

# Write (never load) a crash-only calendar LaunchAgent. No secret in the plist.
_schedule_rotate() {
  local interval="$1" dest script_path uid logs
  if [ "$interval" = "never" ]; then
    _unschedule_rotate
    return 0
  fi
  script_path="$(_install_self)"
  dest="$ROTATE_PLIST"
  uid="$(id -u 2>/dev/null || echo 0)"
  logs="$HOME/Library/Logs/CyClaw"
  mkdir -p "$(dirname "$dest")" "$logs"
  if [ "$interval" = "weekly" ]; then
    cal_xml="    <key>Weekday</key>
    <integer>0</integer>
    <key>Hour</key>
    <integer>4</integer>
    <key>Minute</key>
    <integer>0</integer>"
  else
    cal_xml="    <key>Day</key>
    <integer>1</integer>
    <key>Hour</key>
    <integer>4</integer>
    <key>Minute</key>
    <integer>0</integer>"
  fi
  cat > "$dest" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${ROTATE_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${script_path}</string>
    <string>--rotate</string>
    <string>--skip-prompts</string>
    <string>--no-print-key</string>
    <string>--no-copy-key</string>
    <string>--no-profile-edit</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
${cal_xml}
  </dict>
  <key>StandardOutPath</key>
  <string>${logs}/keys-rotate.log</string>
  <key>StandardErrorPath</key>
  <string>${logs}/keys-rotate.log</string>
</dict>
</plist>
EOF
  chmod 644 "$dest"
  step "wrote $dest ($interval). NOT loaded."
  step "to activate: launchctl bootstrap gui/${uid} $dest"
  step "the job runs the frozen copy at $script_path; after updating CyClaw, re-run --schedule-rotate $interval to refresh it"
  step "the job rotates CYCLAW_API_KEY only. Consoles hold the key in memory — re-run --fill-browser after a rotate, or paste once."
}

_warn_if_installed_copy_drifted() {
  local installed="$HOME_DIR/bin/setup-cyclaw-keys.sh" src
  src="${BASH_SOURCE[0]:-$0}"
  [ -f "$installed" ] || return 0
  if ! cmp -s "$src" "$installed"; then
    warn "installed copy at $installed differs from this script; re-run --schedule-rotate to refresh it"
  fi
}

_copy_key() {
  local tmp old_umask
  if ! command -v pbcopy >/dev/null 2>&1; then
    warn "pbcopy not found — skip pasteboard (expected off macOS)"
    return 0
  fi
  # umask before mktemp (it governs the file mktemp creates), and restored
  # afterwards. Both sibling functions -- _env_upsert and
  # _keychain_store_value -- already save/restore; this one set 077 after
  # mktemp and never put it back, so every file the script created later
  # inherited it. Harmless in effect (077 is stricter, not looser) but the
  # asymmetry is the kind that rots into a real bug.
  old_umask="$(umask)"
  umask 077
  tmp="$(mktemp "${TMPDIR:-/tmp}/cyclaw.clip.XXXXXX")"
  umask "$old_umask"
  # Cleartext key lives in $tmp until pbcopy reads it below; cover that window
  # so an interrupted run doesn't leave it behind (same trap idiom as
  # _fill_browser). pbcopy can block on a contended pasteboard.
  trap 'rm -f "$tmp"' EXIT
  printf '%s' "$_api_value" > "$tmp"
  chmod 600 "$tmp"
  # stdin, not argv
  pbcopy < "$tmp"
  rm -f "$tmp"
  trap - EXIT
  step "CYCLAW_API_KEY copied to the pasteboard (not echoed)"
  if [ "$CLIP_TTL" -gt 0 ] 2>/dev/null; then
    (
      sleep "$CLIP_TTL"
      if command -v pbpaste >/dev/null 2>&1; then
        current="$(pbpaste 2>/dev/null || true)"
        if [ "$current" = "$_api_value" ]; then
          printf '' | pbcopy
        fi
      fi
    ) >/dev/null 2>&1 &
    disown
    step "pasteboard will clear in ${CLIP_TTL}s if it still holds this key"
  fi
}

# Fail-soft: signal TCP LISTEN pids on $1. Never abort the caller.
# Port-scoped (not a process-name sweep of python). Duplicated in
# uninstall-cyclaw.sh because this script is copied standalone to
# ~/.CyClaw/bin/.
# kill(1) success only means the signal was sent. Poll LISTEN afterwards
# (~3s, 0.2s steps) before treating the port as free.
_LOOPBACK_PORT_HELD=0
free_loopback_port() {
  local port="$1" pids="" pid="" i=0 still=""
  case "$port" in
    ''|*[!0-9]*)
      warn "refusing to free a non-numeric port ('$port')"
      return 0
      ;;
  esac
  if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    warn "port $port out of range; left listeners alone"
    return 0
  fi
  if ! command -v lsof >/dev/null 2>&1; then
    warn "lsof not found; cannot free listeners on :$port"
    # Unverified: do not let _restart_servers print "ports freed".
    _LOOPBACK_PORT_HELD=1
    return 0
  fi
  # Any bind on this TCP port blocks a later 127.0.0.1 bind (wildcard included).
  pids="$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    return 0
  fi
  for pid in $pids; do
    case "$pid" in
      ''|*[!0-9]*) continue ;;
    esac
    if [ "$pid" = "$$" ] || [ "$pid" -eq 1 ]; then
      continue
    fi
    step "stopping listener pid $pid on :$port"
    kill "$pid" 2>/dev/null || warn "could not signal pid $pid on :$port"
  done
  i=0
  while [ "$i" -lt 15 ]; do
    still="$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -z "$still" ]; then
      return 0
    fi
    sleep 0.2
    i=$((i + 1))
  done
  warn ":$port still has a TCP LISTEN after signaling (pids: $still)"
  _LOOPBACK_PORT_HELD=1
  return 0
}

# Crash-only KeepAlive would respawn a SIGTERM'd launchd job. Boot the gate
# label out first (fail-soft; the harness label is the retired coding
# console's, kept so an older install's agent is still booted out), then free
# the leftover invoke-cyclaw listener.
_bootout_server_agents() {
  local uid label
  uid="$(id -u 2>/dev/null || echo 0)"
  [ "$(uname -s)" = "Darwin" ] || return 0
  command -v launchctl >/dev/null 2>&1 || return 0
  for label in com.cgfixit.cyclaw.gate com.cgfixit.cyclaw.harness; do
    launchctl bootout "gui/${uid}/${label}" 2>/dev/null || true
  done
}

_restart_servers() {
  _LOOPBACK_PORT_HELD=0
  step "freeing loopback listener on :$GATE_PORT (best-effort)..."
  _bootout_server_agents
  free_loopback_port "$GATE_PORT"
  if [ "$_LOOPBACK_PORT_HELD" -eq 0 ]; then
    step "ports freed. Start cyclaw in a new shell to load the new CYCLAW_API_KEY"
  else
    warn ":$GATE_PORT may still be held; start cyclaw in a new shell only after that listener exits"
  fi
  step "browser still holds the old #apiKeyInput until you paste or re-run --fill-browser"
}

_open_consoles() {
  local gate probe py
  gate="http://127.0.0.1:${GATE_PORT}"
  # Key setup also works before Python or a checkout exists; keep that fallback.
  if [ -n "$REPO_DIR" ]; then
    for py in "$HOME_DIR/venv/bin/python" python3.12 python3 python; do
      if probe="$("$py" "$REPO_DIR/utils/gateway_url.py" \
        "$REPO_DIR/config.yaml" --port "$GATE_PORT" 2>/dev/null)" && [ -n "$probe" ]; then
        gate="$probe"
        break
      fi
    done
  fi
  if ! command -v open >/dev/null 2>&1; then
    warn "open(1) not found — open $gate yourself"
    return 0
  fi
  open "$gate" >/dev/null 2>&1 || warn "could not open $gate"
  step "opened $gate (terminal)"
}

# Inject into the in-memory #apiKeyInput field on loopback tabs only. The
# console refuses localStorage and cookies on purpose.
_fill_browser() {
  local secret_file scpt
  if ! command -v osascript >/dev/null 2>&1; then
    warn "osascript not found — paste the key into the console yourself"
    return 0
  fi
  secret_file="$(mktemp "${TMPDIR:-/tmp}/cyclaw.fillkey.XXXXXX")"
  scpt="$(mktemp "${TMPDIR:-/tmp}/cyclaw.fill.XXXXXX")"
  # Cleartext key lives in secret_file until osascript reads it below; cover
  # that window so an interrupted run doesn't leave it behind (same trap
  # idiom as the TTY-echo restore above).
  trap 'rm -f "$secret_file" "$scpt"' EXIT
  umask 077
  printf '%s' "$_api_value" > "$secret_file"
  chmod 600 "$secret_file"
  cat > "$scpt" <<'APPLESCRIPT'
on run argv
  if (count of argv) < 2 then return
  set secretFile to item 1 of argv
  set gatePort to item 2 of argv
  set theKey to do shell script "/bin/cat " & quoted form of secretFile
  if theKey is "" then return
  set js to "var el=document.getElementById('apiKeyInput')||document.getElementById('apiKey');if(el){el.value=" & my jsonString(theKey) & ";try{el.dispatchEvent(new Event('input',{bubbles:true}));}catch(e){}}"
  my fillChrome(js, gatePort)
  my fillSafari(js, gatePort)
end run

on jsonString(s)
  set s to my replaceText(s, "\\", "\\\\")
  set s to my replaceText(s, "\"", "\\\"")
  return "\"" & s & "\""
end jsonString

on replaceText(t, f, r)
  set AppleScript's text item delimiters to f
  set bits to text items of t
  set AppleScript's text item delimiters to r
  set out to bits as text
  set AppleScript's text item delimiters to ""
  return out
end replaceText

on urlAllowed(u, gatePort)
  if u is missing value or u is "" then return false
  set prefixes to {"http://127.0.0.1:" & gatePort, "http://[::1]:" & gatePort}
  repeat with p in prefixes
    if u is p then return true
    if u starts with (p & "/") then return true
    if u starts with (p & "?") then return true
    if u starts with (p & "#") then return true
  end repeat
  return false
end urlAllowed

on fillChrome(js, gatePort)
  tell application "System Events"
    if not (exists process "Google Chrome") then return
  end tell
  try
    tell application "Google Chrome"
      repeat with w in windows
        repeat with t in tabs of w
          try
            if my urlAllowed(URL of t, gatePort) then
              execute t javascript js
            end if
          end try
        end repeat
      end repeat
    end tell
  end try
end fillChrome

on fillSafari(js, gatePort)
  tell application "System Events"
    if not (exists process "Safari") then return
  end tell
  try
    tell application "Safari"
      repeat with w in windows
        repeat with t in tabs of w
          try
            if my urlAllowed(URL of t, gatePort) then
              do JavaScript js in t
            end if
          end try
        end repeat
      end repeat
    end tell
  end try
end fillSafari
APPLESCRIPT
  chmod 600 "$scpt"
  if osascript "$scpt" "$secret_file" "$GATE_PORT" >/dev/null 2>&1; then
    step "filled #apiKeyInput on loopback tabs (memory only — reload clears it)"
  else
    warn "browser fill failed (Safari/Chrome must allow JavaScript from Apple Events). Paste from the clipboard into the key field."
  fi
  rm -f "$secret_file" "$scpt"
  trap - EXIT
}

# -- prompts ------------------------------------------------------------------


# Read a secret with no echo. Empty / "skip" / "s" / "n" means skip.
# Existing presence is announced without revealing the value.
_prompt_secret() {
  local label="$1" env_name="$2" service="$3" outvar="$4" typed="" present=""
  if [ "$SKIP_PROMPTS" -eq 1 ]; then
    eval "$outvar=''"
    return 0
  fi
  if [ "$DO_KEYCHAIN" -eq 1 ]; then
    if _keychain_read "$service"; then
      present="Keychain"
      _KEYCHAIN_READ_VALUE=""
    else
      case "$_KEYCHAIN_READ_STATE" in
        missing) ;;
        empty) warn "Keychain item for $env_name exists but its value is empty" ;;
        unreadable) warn "Keychain item for $env_name exists but could not be read (security exit $_KEYCHAIN_READ_RC)" ;;
        tool_error) warn "could not query the Keychain for $env_name (security exit $_KEYCHAIN_READ_RC)" ;;
      esac
    fi
  fi
  if [ -z "$present" ] && _env_has "$ENV_FILE" "$env_name"; then
    present=".env"
  elif [ -z "$present" ] && [ -n "$(eval "printf '%s' \"\${$env_name:-}\"")" ]; then
    present="environment"
  fi
  if [ -n "$present" ]; then
    printf '[cyclaw] %s (%s) already set via %s. Enter a new value to replace, or press return to keep: ' \
      "$label" "$env_name" "$present" >&2
  else
    printf '[cyclaw] %s (%s) — paste the secret, or press return to skip: ' \
      "$label" "$env_name" >&2
  fi
  # -s: no echo. bash 3.2 supports it. Restore echo on any exit path.
  # INT/TERM must restore echo AND abort (130 / 143). A restore-only trap
  # plus `read || true` would treat Ctrl-C as "skip" and keep writing state.
  _restore_tty_echo() { stty echo 2>/dev/null || true; }
  _prompt_on_int() { _restore_tty_echo; printf '\n' >&2; exit 130; }
  _prompt_on_term() { _restore_tty_echo; printf '\n' >&2; exit 143; }
  trap '_restore_tty_echo' EXIT
  trap '_prompt_on_int' INT
  trap '_prompt_on_term' TERM
  stty -echo 2>/dev/null || true
  IFS= read -r typed || true
  stty echo 2>/dev/null || true
  trap - EXIT INT TERM
  printf '\n' >&2
  case "$typed" in
    ""|skip|SKIP|s|S|n|N)
      eval "$outvar=''"
      return 0
      ;;
  esac
  if ! _validate_secret "$typed"; then
    warn "$env_name rejected (empty or contained a newline) — skipped"
    eval "$outvar=''"
    return 0
  fi
  eval "$outvar=\$typed"
}

# -- CYCLAW_API_KEY (autogenerate) --------------------------------------------

_api_source=""
_api_value=""

if [ "$ROTATE" -eq 0 ]; then
  if [ "$DO_KEYCHAIN" -eq 1 ]; then
    if _keychain_read "$KC_API"; then
      _api_value="$_KEYCHAIN_READ_VALUE"
      _KEYCHAIN_READ_VALUE=""
      _api_source="Keychain"
    else
      case "$_KEYCHAIN_READ_STATE" in
        missing) ;;
        empty)
          echo "[cyclaw] Keychain item for CYCLAW_API_KEY exists but its value is empty; refusing to generate a replacement." >&2
          exit 1
          ;;
        unreadable)
          echo "[cyclaw] Keychain item for CYCLAW_API_KEY exists but could not be read (security exit $_KEYCHAIN_READ_RC)." >&2
          echo "[cyclaw] Unlock the Keychain or repair its ACL, then retry; no replacement key was generated." >&2
          exit 1
          ;;
        tool_error)
          echo "[cyclaw] could not query the Keychain for CYCLAW_API_KEY (security exit $_KEYCHAIN_READ_RC)." >&2
          echo "[cyclaw] Fix security(1) access or pass --no-keychain explicitly; no replacement key was generated." >&2
          exit 1
          ;;
      esac
    fi
  fi
  if [ -z "$_api_source" ] && _env_has "$ENV_FILE" "CYCLAW_API_KEY"; then
    _api_value="$(_env_get "$ENV_FILE" "CYCLAW_API_KEY")"
    _api_source=".env"
  elif [ -z "$_api_source" ] && _repo_secret_file_in_scope && _env_has "$REPO_DIR/.env" "CYCLAW_API_KEY"; then
    # A checkout .env is in scope only for --repo-path or ~/.CyClaw/repo.
    # Reading it here keeps `openssl rand` from replacing the only copy
    # before migration strips the line.
    _api_value="$(_env_get "$REPO_DIR/.env" "CYCLAW_API_KEY")"
    _api_source="repo .env"
  elif [ -z "$_api_source" ] && [ -n "${CYCLAW_API_KEY:-}" ]; then
    _api_value="$CYCLAW_API_KEY"
    _api_source="environment"
  fi
fi

if [ -n "$_api_value" ] && [ "$ROTATE" -eq 0 ]; then
  step "CYCLAW_API_KEY already present ($_api_source) — keeping (pass --rotate to replace)"
  _persist "CYCLAW_API_KEY" "$KC_API" "$_api_value"
  GENERATED_NEW=0
else
  if ! command -v openssl >/dev/null 2>&1; then
    echo "[cyclaw] openssl is required to generate CYCLAW_API_KEY (it ships with macOS)." >&2
    exit 1
  fi
  _api_value="$(openssl rand -hex 20)"
  if ! _validate_secret "$_api_value"; then
    echo "[cyclaw] openssl produced an unusable CYCLAW_API_KEY" >&2
    exit 1
  fi
  step "generated CYCLAW_API_KEY (openssl rand -hex 20)"
  _persist "CYCLAW_API_KEY" "$KC_API" "$_api_value"
  GENERATED_NEW=1
fi

# -- optional operator tokens -------------------------------------------------

TELEGRAM_VAL=""
ANTHROPIC_VAL=""
GROK_VAL=""
GH_VAL=""

_prompt_secret "Telegram bot token" "TELEGRAM_BOT_TOKEN" "$KC_TELEGRAM" TELEGRAM_VAL
if [ -n "$TELEGRAM_VAL" ]; then
  _persist "TELEGRAM_BOT_TOKEN" "$KC_TELEGRAM" "$TELEGRAM_VAL"
else
  step "Telegram: skipped"
fi

_prompt_secret "Claude / Anthropic API key" "ANTHROPIC_API_KEY" "$KC_ANTHROPIC" ANTHROPIC_VAL
if [ -n "$ANTHROPIC_VAL" ]; then
  _persist "ANTHROPIC_API_KEY" "$KC_ANTHROPIC" "$ANTHROPIC_VAL"
else
  step "Claude (ANTHROPIC_API_KEY): skipped — llm/client.py reads this name, not CLAUDE_API_KEY"
fi

if [ "$GROK_DUMMY" -eq 1 ]; then
  GROK_VAL="dummy"
  step "GROK_API_KEY=dummy (--grok-dummy; fine for offline / pytest)"
  _persist "GROK_API_KEY" "$KC_GROK" "$GROK_VAL"
else
  _prompt_secret "Grok / xAI API key (type dummy for offline tests)" "GROK_API_KEY" "$KC_GROK" GROK_VAL
  if [ -n "$GROK_VAL" ]; then
    _persist "GROK_API_KEY" "$KC_GROK" "$GROK_VAL"
  else
    step "Grok: skipped — pytest needs any non-empty GROK_API_KEY (try --grok-dummy)"
  fi
fi

_prompt_secret "GitHub token (ghp_ / github_pat_)" "GH_TOKEN" "$KC_GH" GH_VAL
if [ -n "$GH_VAL" ]; then
  # CyClaw agentic reads GH_TOKEN; some gh(1) versions also honour GITHUB_TOKEN.
  _persist "GH_TOKEN" "$KC_GH" "$GH_VAL" "GITHUB_TOKEN"
else
  step "GitHub: skipped — gh stays logged in via its own keyring if you already ran gh auth login"
fi

_migrate_plaintext_secrets
_ensure_public_env_file
_refresh_installed_launchers
_ensure_keys_rc_blocks

if [ "$UNSCHEDULE_ROTATE" -eq 1 ]; then
  _unschedule_rotate
fi
if [ -n "$SCHEDULE_ROTATE" ]; then
  _schedule_rotate "$SCHEDULE_ROTATE"
fi

_should_copy=0
if [ "$COPY_KEY" = "always" ]; then
  _should_copy=1
elif [ "$COPY_KEY" = "auto" ] && [ "$GENERATED_NEW" -eq 1 ]; then
  _should_copy=1
fi
if [ "$_should_copy" -eq 1 ]; then
  _copy_key
fi
if [ "$OPEN_CONSOLES" -eq 1 ]; then
  _open_consoles
fi
if [ "$FILL_BROWSER" -eq 1 ]; then
  # Give the just-opened tabs a moment to load, matching invoke-cyclaw.sh.
  sleep 1.5
  _fill_browser
fi

# -- summary (names and paths only) -------------------------------------------

echo ""
step "done. stored: ${_STORED_NAMES:-nothing new}"
if [ "$DO_PUBLIC_ENV" -eq 1 ]; then
  step "home dotenv : $ENV_FILE (non-secret settings, mode 600)"
else
  step "home dotenv : not created (--no-env-file)"
fi
if [ "$DO_ENV_FILE" -eq 1 ]; then
  step "secrets     : ALSO written to $ENV_FILE (plaintext opt-in; rc and launchers do not export them)"
else
  step "secrets     : Keychain only (pass --write-env-file to also store plaintext)"
fi
if [ "$DO_REPO_ENV" -eq 1 ] && [ -n "$REPO_DIR" ]; then
  step "repo dotenv : $REPO_DIR/.env (plaintext secrets opted in, mode 600)"
else
  step "repo dotenv : secret lines not written"
fi
step "this tab    : cyclaw reads Keychain into that process only"
step "new tabs    : inherit non-secret settings from the rc block, not secrets"
step "launchd     : still uses Keychain via cyclaw-keychain-env.sh — never .env"
step "browser     : consoles keep the key in the #apiKey field only (never localStorage)"
if [ "$FILL_BROWSER" -eq 0 ]; then
  step "            : paste once, or re-run with --fill-browser after cyclaw is up"
fi
_warn_if_installed_copy_drifted

if [ "$RESTART_SERVERS" -eq 1 ]; then
  _restart_servers
fi

if [ "$GENERATED_NEW" -eq 1 ]; then
  step "server      : restart gate.py to load the new CYCLAW_API_KEY"
  step "            : nothing in CyClaw reads .env at runtime; the key was NOT applied live"
  if [ "$RESTART_SERVERS" -eq 0 ]; then
    step "            : a stale :$GATE_PORT listener keeps the old key"
    step "            : pass --restart-servers to free that port, then start cyclaw in a new shell"
  fi
fi

if [ "$GENERATED_NEW" -eq 1 ] && [ "$PRINT_KEY" != "never" ]; then
  echo ""
  step "CYCLAW_API_KEY (copy once; paste into the Soul / operator console):"
  printf '%s\n' "$_api_value"
elif [ "$PRINT_KEY" = "always" ]; then
  echo ""
  step "CYCLAW_API_KEY (copy once; paste into the Soul / operator console):"
  printf '%s\n' "$_api_value"
fi

# Drop locals that held operator-typed secrets. The exported env vars stay.
TELEGRAM_VAL=""
ANTHROPIC_VAL=""
GROK_VAL=""
GH_VAL=""
unset TELEGRAM_VAL ANTHROPIC_VAL GROK_VAL GH_VAL
