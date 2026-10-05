#!/usr/bin/env bash
# Linux storage for CYCLAW_API_KEY, sourced by macos/invoke-cyclaw.sh.
#
# macOS keeps the key in the Keychain (setup-cyclaw-keys.sh). Linux has no
# Keychain, so before this the launcher could neither generate nor store a
# key there, and every state-changing route answered 401.
#
# Contract:
#   - Lookup order: libsecret (secret-tool) first, then the key file.
#   - libsecret attributes: service com.cgfixit.cyclaw.api-key (the same
#     service name the macOS Keychain item uses) and account $(id -un).
#   - Key file: ${XDG_CONFIG_HOME:-$HOME/.config}/cyclaw/api-key. Directory
#     0700, file 0600, written under umask 077 through a temp file and mv.
#     A file that is a symlink, is owned by someone else, or is readable by
#     group/other is refused (return 2), never repaired or overwritten.
#   - A new key is 40 hex chars (20 random bytes), as on macOS.
#   - The value is never an argv token of any process (it reaches
#     secret-tool on stdin through the printf builtin), never printed, never
#     logged, and never written to a dotenv file. xtrace is refused.
#   - Test hook: CYCLAW_SECRET_TOOL=<path> selects a secret-tool binary;
#     CYCLAW_SECRET_TOOL=none disables libsecret.
#
# Return codes for cyclaw_linux_load_api_key / cyclaw_linux_ensure_api_key:
#   0 key loaded (or already set), 1 no key / could not store, 2 refused.

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "cyclaw-linux-key: source this file; do not execute it" >&2
  exit 1
fi

_CYCLAW_LINUX_KEY_SERVICE="com.cgfixit.cyclaw.api-key"
_CYCLAW_LINUX_KEY_LABEL="CyClaw API key"

cyclaw_linux_key_file() {
  printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/cyclaw/api-key"
}

_cyclaw_linux_refuse_xtrace() {
  case "$-" in
    *x*)
      echo "[cyclaw] error: refusing to handle CYCLAW_API_KEY with xtrace on (would print it). Re-run without bash -x." >&2
      return 1
      ;;
  esac
  return 0
}

# Prints the secret-tool path, or returns 1 when libsecret is not usable.
_cyclaw_linux_secret_tool() {
  local tool="${CYCLAW_SECRET_TOOL:-}"
  if [ "$tool" = "none" ]; then
    return 1
  fi
  if [ -n "$tool" ]; then
    [ -x "$tool" ] || return 1
    printf '%s\n' "$tool"
    return 0
  fi
  command -v secret-tool 2>/dev/null || return 1
}

_cyclaw_linux_stat() {
  # $1 = linux format, $2 = BSD format, $3 = path
  stat -c "$1" -- "$3" 2>/dev/null || stat -f "$2" -- "$3" 2>/dev/null
}

_cyclaw_linux_secret_lookup() {
  "$1" lookup service "$_CYCLAW_LINUX_KEY_SERVICE" account "$(id -un)" 2>/dev/null
}

cyclaw_linux_load_api_key() {
  local tool="" value="" file="" mode="" owner=""
  _cyclaw_linux_refuse_xtrace || return 2
  if [ -n "${CYCLAW_API_KEY:-}" ]; then
    return 0
  fi
  if tool="$(_cyclaw_linux_secret_tool)"; then
    value="$(_cyclaw_linux_secret_lookup "$tool")" || value=""
    if [ -n "$value" ]; then
      export CYCLAW_API_KEY="$value"
      value=""
      return 0
    fi
  fi
  file="$(cyclaw_linux_key_file)"
  if [ ! -e "$file" ] && [ ! -L "$file" ]; then
    return 1
  fi
  if [ -L "$file" ] || [ ! -f "$file" ]; then
    echo "[cyclaw] error: refusing $file: not a regular file. Remove it and re-run." >&2
    return 2
  fi
  owner="$(_cyclaw_linux_stat %u %u "$file")" || owner=""
  if [ "$owner" != "$(id -u)" ]; then
    echo "[cyclaw] error: refusing $file: not owned by $(id -un). Remove it and re-run." >&2
    return 2
  fi
  mode="$(_cyclaw_linux_stat %a %Lp "$file")" || mode=""
  case "$mode" in
    600|400) ;;
    *)
      echo "[cyclaw] error: refusing $file: mode ${mode:-unknown}, expected 600. Run: chmod 600 \"$file\"" >&2
      return 2
      ;;
  esac
  IFS= read -r value < "$file" || true
  if [ -z "$value" ]; then
    echo "[cyclaw] error: refusing $file: empty. Remove it and re-run to generate a new key." >&2
    return 2
  fi
  export CYCLAW_API_KEY="$value"
  value=""
  return 0
}

_cyclaw_linux_generate_key() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 20
    return
  fi
  od -An -N20 -tx1 /dev/urandom | tr -d ' \n'
}

# Value arrives as a shell-function argument and leaves on stdin via the
# printf builtin, so it is never on secret-tool's argv.
_cyclaw_linux_store_secret_tool() {
  local tool="$1" value="$2" readback=""
  printf '%s' "$value" | "$tool" store --label="$_CYCLAW_LINUX_KEY_LABEL" \
    service "$_CYCLAW_LINUX_KEY_SERVICE" account "$(id -un)" >/dev/null 2>&1 || return 1
  # A keyring that accepts a write but cannot read it back (no unlocked
  # collection on a headless box) is not storage. Fall back to the file.
  readback="$(_cyclaw_linux_secret_lookup "$tool")" || readback=""
  if [ "$readback" != "$value" ]; then
    readback=""
    return 1
  fi
  readback=""
  return 0
}

_cyclaw_linux_store_file() {
  local value="$1" file dir
  file="$(cyclaw_linux_key_file)"
  dir="${file%/*}"
  (
    umask 077
    mkdir -p -- "$dir" || exit 1
    if [ -L "$dir" ]; then
      echo "[cyclaw] error: refusing $dir: symlink" >&2
      exit 1
    fi
    chmod 700 -- "$dir" || exit 1
    tmp="$(mktemp "$dir/.api-key.XXXXXX")" || exit 1
    if printf '%s\n' "$value" > "$tmp" && chmod 600 -- "$tmp" && mv -f -- "$tmp" "$file"; then
      exit 0
    fi
    rm -f -- "$tmp"
    exit 1
  )
}

cyclaw_linux_ensure_api_key() {
  local rc=0 value="" tool="" file=""
  cyclaw_linux_load_api_key || rc=$?
  if [ "$rc" -ne 1 ]; then
    # 0 loaded, 2 refused: a refused file is never overwritten.
    return "$rc"
  fi
  echo "[cyclaw] key  : no CYCLAW_API_KEY in libsecret or the key file; generating one"
  value="$(_cyclaw_linux_generate_key)" || value=""
  case "$value" in
    *[!0-9a-f]*|"")
      value=""
      echo "[cyclaw] error: could not generate CYCLAW_API_KEY (no openssl or /dev/urandom)" >&2
      return 1
      ;;
  esac
  if [ "${#value}" -ne 40 ]; then
    value=""
    echo "[cyclaw] error: could not generate CYCLAW_API_KEY (short read)" >&2
    return 1
  fi
  if tool="$(_cyclaw_linux_secret_tool)" && _cyclaw_linux_store_secret_tool "$tool" "$value"; then
    export CYCLAW_API_KEY="$value"
    value=""
    echo "[cyclaw] key  : stored in libsecret"
    return 0
  fi
  file="$(cyclaw_linux_key_file)"
  if _cyclaw_linux_store_file "$value"; then
    export CYCLAW_API_KEY="$value"
    value=""
    echo "[cyclaw] key  : stored in $file"
    return 0
  fi
  value=""
  echo "[cyclaw] error: could not store a generated CYCLAW_API_KEY in libsecret or $file" >&2
  return 1
}
