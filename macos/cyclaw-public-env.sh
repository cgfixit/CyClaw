#!/usr/bin/env bash
# Non-secret CyClaw dotenv loader.
#
# Sourced by shell rc blocks, macos/cyclaw-keychain-load.sh, and
# macos/setup-cyclaw-keys.sh. Not a launcher. Bash 3.2 and zsh.
#
# ~/.CyClaw/.env is the default home for ordinary settings: ports, paths,
# mode flags, model names, feature toggles. Secret-classified names are
# not exported from that file. Those values live in the macOS Keychain and
# are read into the cyclaw process only.
#
# A name is secret-classified when either is true:
#   1. Allowlist (CyClaw's own keys):
#        CYCLAW_API_KEY
#        TELEGRAM_BOT_TOKEN
#        GROK_API_KEY
#        ANTHROPIC_API_KEY
#        GH_TOKEN
#        GITHUB_TOKEN
#        CLAUDE_API_KEY
#   2. Suffix pattern (case-sensitive):
#        *_API_KEY  *_TOKEN  *_SECRET  *_PASSWORD
# CLAUDE_API_KEY is on the allowlist so it is never loaded. llm/client.py
# does not read it, and setup does not copy it into the Keychain.
# Names that match the pattern but are not on the allowlist are not loaded
# and are not given a Keychain service. Setup leaves those lines in place
# and warns, so the only copy is not deleted.

if [ -n "${BASH_SOURCE:-}" ] && [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "cyclaw-public-env: source this file; do not execute it" >&2
  exit 1
fi

cyclaw_is_secret_name() {
  case "$1" in
    CYCLAW_API_KEY|TELEGRAM_BOT_TOKEN|GROK_API_KEY|ANTHROPIC_API_KEY|GH_TOKEN|GITHUB_TOKEN|CLAUDE_API_KEY)
      return 0
      ;;
    *_API_KEY|*_TOKEN|*_SECRET|*_PASSWORD)
      return 0
      ;;
  esac
  return 1
}

# Same predicate under the name cyclaw-keychain-load.sh calls.
_is_cyclaw_secret_name() {
  cyclaw_is_secret_name "$1"
}

cyclaw_public_env_header() {
  cat <<'EOF'
# CyClaw non-secret settings (mode 600).
# Ports, paths, mode flags, model names, and feature toggles belong here.
# Secret-classified names do not: the allowlist in macos/cyclaw-public-env.sh,
# plus any name ending in _API_KEY, _TOKEN, _SECRET, or _PASSWORD.
# Those are read from the macOS Keychain when cyclaw starts.
EOF
}

cyclaw_dotenv_mode() {
  if [ "$(uname -s)" = "Darwin" ]; then
    /usr/bin/stat -f %Lp "$1" 2>/dev/null || true
  else
    stat -c %a "$1" 2>/dev/null || true
  fi
}

# Print the assignment name, or return 1 for blanks, comments, and junk.
cyclaw_dotenv_assignment_name() {
  local line="$1" body
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  case "$line" in
    ''|\#*) return 1 ;;
  esac
  body="$line"
  case "$body" in
    export\ *|export$'\t'*) body="${body#export}" ;;
  esac
  body="${body#"${body%%[![:space:]]*}"}"
  case "$body" in
    *=*) ;;
    *) return 1 ;;
  esac
  body="${body%%=*}"
  body="${body%"${body##*[![:space:]]}"}"
  case "$body" in
    *[!A-Za-z0-9_]*) return 1 ;;
    [A-Za-z_]*) printf '%s\n' "$body" ;;
    *) return 1 ;;
  esac
}

cyclaw_dotenv_assignment_value() {
  local line="$1" raw="$1" inner
  raw="${raw#*=}"
  case "$raw" in
    \'*\')
      inner="${raw#\'}"
      inner="${inner%\'}"
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

cyclaw_file_has_secret_assignment() {
  local file="$1" line name
  [ -f "$file" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    name="$(cyclaw_dotenv_assignment_name "$line" 2>/dev/null)" || continue
    [ -n "$name" ] || continue
    if cyclaw_is_secret_name "$name"; then
      return 0
    fi
  done < "$file"
  return 1
}

# Export non-secret assignments only. Does not execute the file as a script.
cyclaw_export_nonsecret_assignments() {
  local file="$1" line name val
  while IFS= read -r line || [ -n "$line" ]; do
    name="$(cyclaw_dotenv_assignment_name "$line" 2>/dev/null)" || continue
    [ -n "$name" ] || continue
    if cyclaw_is_secret_name "$name"; then
      continue
    fi
    val="$(cyclaw_dotenv_assignment_value "$line")"
    export "${name}=${val}"
  done < "$file"
}

# Load ordinary settings from a mode 600/400 dotenv into THIS shell.
# A file that still contains a secret-classified assignment is not executed;
# only its non-secret assignments are exported. A clean file is sourced
# (set -a) so it behaves the way ~/.CyClaw/.env always has.
cyclaw_source_public_env() {
  local file="$1" mode="" had_allexport=0 source_status=0
  [ -n "${file:-}" ] || return 1
  [ -f "$file" ] || return 1
  mode="$(cyclaw_dotenv_mode "$file")"
  case "$mode" in
    600|400) ;;
    *)
      echo "[cyclaw] warn : refusing to source $file (mode ${mode:-unknown}; want 600 or 400). Fix with: chmod 600 $file" >&2
      return 1
      ;;
  esac
  if cyclaw_file_has_secret_assignment "$file"; then
    echo "[cyclaw] warn : $file contains secret-classified names. Those lines were not exported. Re-run macos/setup-cyclaw-keys.sh to move allowlisted keys into the Keychain." >&2
    cyclaw_export_nonsecret_assignments "$file"
    return 0
  fi
  case "$-" in *a*) had_allexport=1 ;; esac
  set -a
  # shellcheck disable=SC1090
  . "$file" || source_status=$?
  if [ "$had_allexport" -eq 0 ]; then
    set +a
  fi
  return "$source_status"
}
