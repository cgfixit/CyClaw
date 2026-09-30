#!/usr/bin/env bash
# Load CyClaw secrets into the current process from the macOS Keychain.
#
# Sourced by macos/invoke-cyclaw.sh, macos/setup-cyclaw.sh, and
# macos/setup-from-clone.sh. Not a launcher. The installed copy lives beside
# macos/cyclaw-keychain-env.sh (repo macos/ or ~/.CyClaw/bin).
#
# Contract:
#   - Non-secret dotenv assignments may still be sourced (mode 600 or 400).
#   - Secret names are scrubbed after that source. They are never kept from
#     a file, even when the file is private.
#   - Secrets that are still unset are read from Keychain via
#     cyclaw-keychain-env.sh. A missing optional item stays unset. A present
#     item that cannot be read aborts the caller. There is no plaintext fallback.
#   - xtrace is refused before any secret is assigned. Values are never printed.
#
# Secret classification lives in macos/cyclaw-public-env.sh: an allowlist
# (the names below) plus the suffix pattern *_API_KEY *_TOKEN *_SECRET
# *_PASSWORD. Non-secret settings in ~/.CyClaw/.env are still sourced.
# Secret-classified names are scrubbed after that source and filled from
# the Keychain. There is no plaintext fallback.

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "cyclaw-keychain-load: source this file; do not execute it" >&2
  exit 1
fi

_CYCLAW_LOAD_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_CYCLAW_LOAD_DIR/cyclaw-public-env.sh" ]; then
  # shellcheck disable=SC1091
  . "$_CYCLAW_LOAD_DIR/cyclaw-public-env.sh"
fi

_CYCLAW_SECRET_NAMES="CYCLAW_API_KEY TELEGRAM_BOT_TOKEN GROK_API_KEY ANTHROPIC_API_KEY GH_TOKEN GITHUB_TOKEN CLAUDE_API_KEY"
_CYCLAW_SCRUB_NAMES="$_CYCLAW_SECRET_NAMES"

_remember_one_secret_preset() {
  local name="$1"
  case " ${_CYCLAW_SECRET_PRESET-} " in
    *" ${name} "*) return 0 ;;
  esac
  # ${!name+x} is not "is the named variable set" (bash parses the + as part
  # of the indirect name). The name is classified before this runs.
  if eval "test \"\${$name+x}\""; then
    _CYCLAW_SECRET_PRESET="${_CYCLAW_SECRET_PRESET} ${name}"
    eval "_CYCLAW_PRESET_${name}=\${$name}"
  fi
}

_remember_secret_preset() {
  local name
  _CYCLAW_SECRET_PRESET=""
  _CYCLAW_SCRUB_NAMES="$_CYCLAW_SECRET_NAMES"
  # Values are saved because sourcing a dotenv overwrites them, and the
  # scrub must put the operator's original value back — not the file's.
  for name in $_CYCLAW_SECRET_NAMES; do
    _remember_one_secret_preset "$name"
  done
}

# Pattern matches in the file (DB_PASSWORD, *_API_KEY, ...) join the scrub
# list before the file is sourced. Allowlist names are already on it.
_remember_secret_presets_in_file() {
  local file="$1" line name
  [ -f "$file" ] || return 0
  command -v cyclaw_is_secret_name >/dev/null 2>&1 || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    name="$(cyclaw_dotenv_assignment_name "$line" 2>/dev/null)" || continue
    [ -n "$name" ] || continue
    cyclaw_is_secret_name "$name" || continue
    case " ${_CYCLAW_SCRUB_NAMES} " in
      *" ${name} "*) ;;
      *) _CYCLAW_SCRUB_NAMES="${_CYCLAW_SCRUB_NAMES} ${name}" ;;
    esac
    _remember_one_secret_preset "$name"
  done < "$file"
}

_scrub_dotenv_secrets() {
  local name preset saved names
  preset="${_CYCLAW_SECRET_PRESET-}"
  names="${_CYCLAW_SCRUB_NAMES:-$_CYCLAW_SECRET_NAMES}"
  for name in $names; do
    case " ${preset} " in
      *" ${name} "*)
        eval "saved=\${_CYCLAW_PRESET_${name}}"
        export "${name}=${saved}"
        eval "unset _CYCLAW_PRESET_${name}"
        saved=""
        ;;
      *) unset "$name" ;;
    esac
  done
}

_dotenv_mode() {
  if [ "$(uname -s)" = "Darwin" ]; then
    # Pin BSD stat: a GNU stat earlier on PATH interprets -f differently,
    # so valid private dotenv files could fail the permission check.
    /usr/bin/stat -f %Lp "$1" 2>/dev/null || true
  else
    stat -c %a "$1" 2>/dev/null || true
  fi
}

# Source non-secret assignments. Secret names that the file exports are
# removed again before this returns, including when the file itself fails.
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
  if command -v _remember_secret_presets_in_file >/dev/null 2>&1; then
    _remember_secret_presets_in_file "$f" || true
  fi
  case "$-" in *a*) had_allexport=1 ;; esac
  set -a
  . "$f" || source_status=$?
  # Restore the caller's export policy; an unconditional set +a would disable
  # a setting that may have been enabled before this helper was called.
  if [ "$had_allexport" -eq 0 ]; then
    set +a
  fi
  _scrub_dotenv_secrets || true
  return "$source_status"
}

_security_bin() {
  if [ "${CYCLAW_KEYCHAIN_ENV_TEST_MODE:-}" = "1" ] || \
     [ "${CYCLAW_UNINSTALL_TEST_MODE:-}" = "1" ] || \
     [ "${CYCLAW_SETUP_KEYS_SKIP_PLATFORM:-}" = "1" ]; then
    command -v security 2>/dev/null || true
    return 0
  fi
  if [ -x /usr/bin/security ]; then
    printf '%s\n' /usr/bin/security
    return 0
  fi
  command -v security 2>/dev/null || true
}

_cyclaw_keychain_helper() {
  local dir
  dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  if [ -f "$dir/cyclaw-keychain-env.sh" ]; then
    printf '%s\n' "$dir/cyclaw-keychain-env.sh"
    return 0
  fi
  echo "[cyclaw] error: cyclaw-keychain-env.sh is not beside cyclaw-keychain-load.sh ($dir)" >&2
  return 1
}

# 0 loaded or already set or absent. 1 present but unreadable / tool error.
_load_one_keychain_secret() {
  local service="$1" var="$2" helper="$3" bin="$4" value="" rc=0
  if [ -n "${!var:-}" ]; then
    return 0
  fi
  if [ -z "$bin" ]; then
    return 0
  fi
  if "$bin" find-generic-password -a "$(id -un)" -s "$service" >/dev/null 2>&1; then
    :
  else
    rc=$?
    if [ "$rc" -eq 44 ]; then
      return 0
    fi
    echo "[cyclaw] error: could not query the Keychain for $var (service $service, security exit $rc). Not reading .env." >&2
    return 1
  fi
  # cyclaw-keychain-env.sh exports the value and execs. The child printf
  # expands the variable; the parent never puts the secret on argv.
  if ! value="$("$helper" "$service" "$var" -- /bin/sh -c 'printf %s "$'"$var"'"')"; then
    echo "[cyclaw] error: Keychain item for $var (service $service) could not be read. Not falling back to .env." >&2
    return 1
  fi
  if [ -z "$value" ]; then
    echo "[cyclaw] error: Keychain item for $var (service $service) is empty. Not falling back to .env." >&2
    return 1
  fi
  export "$var=$value"
  value=""
  return 0
}

_warn_dotenv_secret_lines() {
  local file="$1" line name
  [ -n "$file" ] || return 0
  [ -f "$file" ] || return 0
  if ! command -v cyclaw_dotenv_assignment_name >/dev/null 2>&1; then
    return 0
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    name="$(cyclaw_dotenv_assignment_name "$line" 2>/dev/null)" || continue
    [ -n "$name" ] || continue
    cyclaw_is_secret_name "$name" || continue
    echo "[cyclaw] warn : $name is in $file but launchers do not load secrets from dotenv." >&2
    echo "[cyclaw] warn : re-run macos/setup-cyclaw-keys.sh to copy an allowlisted key into the Keychain and remove that plaintext line." >&2
  done < "$file"
}

# Arguments are dotenv paths to warn about (names only, never values).
_load_os_secrets() {
  local helper="" bin="" file
  case "$-" in
    *x*)
      echo "[cyclaw] error: refusing to load Keychain secrets with xtrace on (would print secrets). Re-run without bash -x." >&2
      return 1
      ;;
  esac
  helper="$(_cyclaw_keychain_helper)" || return 1
  bin="$(_security_bin)"
  if [ -z "$bin" ]; then
    echo "[cyclaw] warn : security(1) is unavailable. Keychain secrets were not loaded, and plaintext .env lines are not used." >&2
  else
    _load_one_keychain_secret "com.cgfixit.cyclaw.api-key" "CYCLAW_API_KEY" "$helper" "$bin" || return 1
    _load_one_keychain_secret "com.cgfixit.cyclaw.telegram-bot-token" "TELEGRAM_BOT_TOKEN" "$helper" "$bin" || return 1
    _load_one_keychain_secret "com.cgfixit.cyclaw.grok-api-key" "GROK_API_KEY" "$helper" "$bin" || return 1
    _load_one_keychain_secret "com.cgfixit.cyclaw.anthropic-api-key" "ANTHROPIC_API_KEY" "$helper" "$bin" || return 1
    _load_one_keychain_secret "com.cgfixit.cyclaw.gh-token" "GH_TOKEN" "$helper" "$bin" || return 1
    if [ -n "${GH_TOKEN:-}" ] && [ -z "${GITHUB_TOKEN:-}" ]; then
      export "GITHUB_TOKEN=$GH_TOKEN"
    fi
  fi
  for file in "$@"; do
    _warn_dotenv_secret_lines "$file"
  done
  return 0
}

# Drop secret lines from one dotenv only when Keychain already has a
# non-empty copy. Never prints values. Never writes a backup. A missing
# Keychain item leaves the line in place so uninstall cannot destroy the
# only copy; setup-cyclaw-keys.sh is what copies then deletes.
_strip_plaintext_if_keychain() {
  local file="$1" bin="" name service value="" rc=0 tmp old_umask
  [ -n "$file" ] || return 0
  [ -f "$file" ] || return 0
  case "$-" in
    *x*)
      echo "[cyclaw] WARNING: refusing to read Keychain while xtrace is on; left $file unchanged" >&2
      return 0
      ;;
  esac
  bin="$(_security_bin)"
  if [ -z "$bin" ]; then
    echo "[cyclaw] WARNING: security(1) is unavailable; left plaintext lines in $file" >&2
    return 0
  fi
  for name in CYCLAW_API_KEY TELEGRAM_BOT_TOKEN GROK_API_KEY ANTHROPIC_API_KEY GH_TOKEN GITHUB_TOKEN; do
    grep -E -q "^[[:space:]]*(export[[:space:]]+)?${name}=" "$file" 2>/dev/null || continue
    case "$name" in
      CYCLAW_API_KEY) service="com.cgfixit.cyclaw.api-key" ;;
      TELEGRAM_BOT_TOKEN) service="com.cgfixit.cyclaw.telegram-bot-token" ;;
      GROK_API_KEY) service="com.cgfixit.cyclaw.grok-api-key" ;;
      ANTHROPIC_API_KEY) service="com.cgfixit.cyclaw.anthropic-api-key" ;;
      GH_TOKEN|GITHUB_TOKEN) service="com.cgfixit.cyclaw.gh-token" ;;
      *) continue ;;
    esac
    if "$bin" find-generic-password -a "$(id -un)" -s "$service" >/dev/null 2>&1; then
      :
    else
      rc=$?
      if [ "$rc" -eq 44 ]; then
        echo "[cyclaw] WARNING: left plaintext $name in $file (no Keychain item for $service). Re-run setup-cyclaw-keys.sh to move it." >&2
      else
        echo "[cyclaw] WARNING: left plaintext $name in $file (Keychain query failed, security exit $rc)." >&2
      fi
      continue
    fi
    if ! value="$("$bin" find-generic-password -a "$(id -un)" -s "$service" -w 2>/dev/null)"; then
      echo "[cyclaw] WARNING: left plaintext $name in $file (Keychain item exists but could not be read)." >&2
      value=""
      continue
    fi
    if [ -z "$value" ]; then
      echo "[cyclaw] WARNING: left plaintext $name in $file (Keychain item is empty)." >&2
      value=""
      continue
    fi
    value=""
    old_umask="$(umask)"
    umask 077
    tmp="$(mktemp "${TMPDIR:-/tmp}/cyclaw.env.XXXXXX")"
    grep -v -E "^[[:space:]]*(export[[:space:]]+)?${name}=" "$file" > "$tmp" || true
    if grep -E -q "^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=" "$tmp"; then
      chmod 600 "$tmp"
      mv "$tmp" "$file"
      chmod 600 "$file"
    elif grep -q '[^[:space:]]' "$tmp"; then
      # Comments and blanks are the rest of the file. Keep them.
      chmod 600 "$tmp"
      mv "$tmp" "$file"
      chmod 600 "$file"
    else
      if command -v cyclaw_public_env_header >/dev/null 2>&1; then
        cyclaw_public_env_header > "$tmp"
      else
        printf '%s\n' "# CyClaw non-secret settings. Secrets are not stored here." > "$tmp"
      fi
      chmod 600 "$tmp"
      mv "$tmp" "$file"
      chmod 600 "$file"
    fi
    umask "$old_umask"
    echo "[cyclaw] removed plaintext $name from $file (Keychain $service holds it). No backup was written."
  done
  return 0
}
