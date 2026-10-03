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
# A name is secret-classified when either is true, compared case-insensitively
# so grok_api_key is not exported (PowerShell -like is already case-insensitive):
#   1. Allowlist (CyClaw's own keys):
#        CYCLAW_API_KEY
#        TELEGRAM_BOT_TOKEN
#        GROK_API_KEY
#        ANTHROPIC_API_KEY
#        GH_TOKEN
#        GITHUB_TOKEN
#        CLAUDE_API_KEY
#   2. Suffix pattern:
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
  local name
  name="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
  case "$name" in
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

# One env-line parser for the shell loaders. Prints one record per assignment:
#   name<US>op<US>value
# op is "=" or "+=". Records use ASCII unit separator (0x1f), not tab, so a
# value may contain tabs. Bash 3.2 and zsh.
#
# A line may carry more than one assignment. Recognized forms:
#   NAME=value  NAME+=value  (every such token, not only the first)
#   lowercase names
#   a leading UTF-8 BOM (EF BB BF or U+FEFF)
#   export / declare -x / typeset / readonly, with optional flag words
# Quotes follow shell words, including the '\'' encoding setup writes.
# A later command word stops the scan (`echo NAME=value` is not an assignment).
# An unquoted `;` starts another simple command, which is scanned the same way.
# A command word, brace, or other syntax the scan does not consume makes the
# line partial. Callers must not execute a partial line.
#
# Span records are:
#   start<US>end<US>name<US>op<US>value
# Indexes are into the BOM-stripped line. A trailer follows:
#   @<US>complete    the line was only assignments, keywords, separators, comments
#   @<US>partial     something was left unparsed (fail closed: do not execute)
cyclaw_dotenv_line_spans() {
  local line="$1" n i c word bom status="complete"
  # ANSI-C quotes do not expand inside the ${var#pattern} quotes, so bind
  # the BOM first. UTF-8 locales treat EF BB BF as one character (U+FEFF).
  bom=$'\xef\xbb\xbf'
  case "$line" in
    "$bom"*) line="${line#"$bom"}" ;;
  esac
  bom=$'\ufeff'
  case "$line" in
    "$bom"*) line="${line#"$bom"}" ;;
  esac
  _CYCLAW_SRC="$line"
  _CYCLAW_AT=0
  n=${#_CYCLAW_SRC}
  while [ "$_CYCLAW_AT" -lt "$n" ]; do
    _cyclaw_scan_skip_space
    [ "$_CYCLAW_AT" -lt "$n" ] || break
    c="${_CYCLAW_SRC:$_CYCLAW_AT:1}"
    case "$c" in
      \#) break ;;
      ';'|'|') _CYCLAW_AT=$((_CYCLAW_AT + 1)); continue ;;
      '&') _CYCLAW_AT=$((_CYCLAW_AT + 1)); continue ;;
    esac
    i="$_CYCLAW_AT"
    _cyclaw_scan_read_word
    word="$_CYCLAW_WORD"
    case "$word" in
      export|declare|typeset|readonly)
        _cyclaw_scan_skip_space
        while [ "$_CYCLAW_AT" -lt "$n" ]; do
          c="${_CYCLAW_SRC:$_CYCLAW_AT:1}"
          case "$c" in
            -) ;;
            *) break ;;
          esac
          i="$_CYCLAW_AT"
          _cyclaw_scan_read_word
          case "$_CYCLAW_WORD" in
            -*) ;;
            *) _CYCLAW_AT="$i"; break ;;
          esac
          _cyclaw_scan_skip_space
        done
        continue
        ;;
    esac
    # Not a keyword. Rewind and try an assignment at this word.
    _CYCLAW_AT="$i"
    if _cyclaw_scan_read_assignment; then
      printf '%s\x1f%s\x1f%s\x1f%s\x1f%s\n' \
        "$_CYCLAW_ASSIGN_START" "$_CYCLAW_ASSIGN_END" \
        "$_CYCLAW_NAME" "$_CYCLAW_OP" "$_CYCLAW_VAL"
      continue
    fi
    # Command word or other syntax. Do not keep scanning: the rest can hide
    # an assignment (`true; GH_TOKEN=...`, `eval GH_TOKEN=...`).
    status="partial"
    break
  done
  printf '@\x1f%s\n' "$status"
  _CYCLAW_SRC=""
  _CYCLAW_WORD=""
  _CYCLAW_VAL=""
}

# 0 when the line is only assignments, keywords, separators, and comments.
cyclaw_dotenv_line_is_complete() {
  local start rest
  while IFS=$'\x1f' read -r start rest; do
    if [ "$start" = "@" ]; then
      [ "$rest" = "complete" ]
      return
    fi
  done < <(cyclaw_dotenv_line_spans "$1")
  return 1
}

cyclaw_dotenv_line_assignments() {
  local start end name op val
  while IFS=$'\x1f' read -r start end name op val; do
    [ "$start" = "@" ] && continue
    [ -n "$name" ] || continue
    printf '%s\x1f%s\x1f%s\n' "$name" "$op" "$val"
  done < <(cyclaw_dotenv_line_spans "$1")
}

# First assignment name, or return 1. Callers that enforce policy walk
# cyclaw_dotenv_line_assignments so a later token on the same line is not missed.
cyclaw_dotenv_assignment_name() {
  local name op val
  name=""
  while IFS=$'\x1f' read -r name op val; do
    [ -n "$name" ] || continue
    printf '%s\n' "$name"
    return 0
  done < <(cyclaw_dotenv_line_assignments "$1")
  return 1
}

cyclaw_dotenv_assignment_value() {
  local name op val
  while IFS=$'\x1f' read -r name op val; do
    [ -n "$name" ] || continue
    printf '%s' "$val"
    return 0
  done < <(cyclaw_dotenv_line_assignments "$1")
  return 1
}

# Advance _CYCLAW_AT over ASCII whitespace in _CYCLAW_SRC.
_cyclaw_scan_skip_space() {
  local n c
  n=${#_CYCLAW_SRC}
  while [ "$_CYCLAW_AT" -lt "$n" ]; do
    c="${_CYCLAW_SRC:$_CYCLAW_AT:1}"
    case "$c" in
      [[:space:]]) _CYCLAW_AT=$((_CYCLAW_AT + 1)) ;;
      *) break ;;
    esac
  done
}

# Read one shell word starting at _CYCLAW_AT. Sets _CYCLAW_WORD to the
# unquoted text and leaves _CYCLAW_AT on the following character.
# Unquoted ; | & and whitespace end the word. '\'' is one apostrophe.
_cyclaw_scan_read_word() {
  local n i c out=""
  n=${#_CYCLAW_SRC}
  i="$_CYCLAW_AT"
  out=""
  while [ "$i" -lt "$n" ]; do
    c="${_CYCLAW_SRC:$i:1}"
    case "$c" in
      [[:space:]]|';'|'|'|'&') break ;;
      \\)
        i=$((i + 1))
        if [ "$i" -lt "$n" ]; then
          out="${out}${_CYCLAW_SRC:$i:1}"
          i=$((i + 1))
        fi
        ;;
      \')
        i=$((i + 1))
        while [ "$i" -lt "$n" ]; do
          c="${_CYCLAW_SRC:$i:1}"
          i=$((i + 1))
          if [ "$c" = "'" ]; then
            break
          fi
          out="${out}${c}"
        done
        ;;
      \")
        i=$((i + 1))
        while [ "$i" -lt "$n" ]; do
          c="${_CYCLAW_SRC:$i:1}"
          if [ "$c" = '"' ]; then
            i=$((i + 1))
            break
          fi
          if [ "$c" = "\\" ] && [ $((i + 1)) -lt "$n" ]; then
            i=$((i + 1))
            out="${out}${_CYCLAW_SRC:$i:1}"
            i=$((i + 1))
            continue
          fi
          out="${out}${c}"
          i=$((i + 1))
        done
        ;;
      *)
        out="${out}${c}"
        i=$((i + 1))
        ;;
    esac
  done
  _CYCLAW_WORD="$out"
  _CYCLAW_AT="$i"
}

# If _CYCLAW_SRC at _CYCLAW_AT is NAME= or NAME+=, consume it.
# Sets _CYCLAW_NAME, _CYCLAW_OP, _CYCLAW_VAL. Returns 1 otherwise.
_cyclaw_scan_read_assignment() {
  local n i c name="" op rest start
  n=${#_CYCLAW_SRC}
  i="$_CYCLAW_AT"
  start="$i"
  [ "$i" -lt "$n" ] || return 1
  c="${_CYCLAW_SRC:$i:1}"
  case "$c" in
    [A-Za-z_]) ;;
    *) return 1 ;;
  esac
  name=""
  while [ "$i" -lt "$n" ]; do
    c="${_CYCLAW_SRC:$i:1}"
    case "$c" in
      [A-Za-z0-9_]) name="${name}${c}"; i=$((i + 1)) ;;
      *) break ;;
    esac
  done
  rest="${_CYCLAW_SRC:$i}"
  case "$rest" in
    +=*) op="+="; i=$((i + 2)) ;;
    =*) op="="; i=$((i + 1)) ;;
    *) return 1 ;;
  esac
  _CYCLAW_ASSIGN_START="$start"
  _CYCLAW_AT="$i"
  _cyclaw_scan_read_word
  _CYCLAW_NAME="$name"
  _CYCLAW_OP="$op"
  _CYCLAW_VAL="$_CYCLAW_WORD"
  _CYCLAW_ASSIGN_END="$_CYCLAW_AT"
  return 0
}

cyclaw_file_has_secret_assignment() {
  local file="$1" line name op val
  [ -f "$file" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    while IFS=$'\x1f' read -r name op val; do
      [ -n "$name" ] || continue
      if cyclaw_is_secret_name "$name"; then
        return 0
      fi
    done < <(cyclaw_dotenv_line_assignments "$line")
  done < "$file"
  return 1
}

# 0 when any line is not a plain assignment line. Such a line is not executed.
cyclaw_file_has_unparsed_line() {
  local file="$1" line
  [ -f "$file" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    if ! cyclaw_dotenv_line_is_complete "$line"; then
      return 0
    fi
  done < "$file"
  return 1
}

# Export non-secret assignments only. Does not execute the file as a script.
# NAME+= appends. Secret-classified names, including a later token on the
# same line, are skipped. A line that is not fully parsed is skipped entirely
# so a command word cannot hide a later assignment that this function would
# otherwise miss, and so that command is not run.
cyclaw_export_nonsecret_assignments() {
  local file="$1" line name op val cur
  while IFS= read -r line || [ -n "$line" ]; do
    if ! cyclaw_dotenv_line_is_complete "$line"; then
      continue
    fi
    while IFS=$'\x1f' read -r name op val; do
      [ -n "$name" ] || continue
      if cyclaw_is_secret_name "$name"; then
        continue
      fi
      if [ "$op" = "+=" ]; then
        eval "cur=\${$name-}"
        export "${name}=${cur}${val}"
        cur=""
      else
        export "${name}=${val}"
      fi
    done < <(cyclaw_dotenv_line_assignments "$line")
  done < "$file"
}

# Drop assignments of $key whose unquoted value byte-equals $expect.
# Kept tokens stay as originally written (quotes, export, $VAR, comments).
# Only the matched assignment's span is cut out. A file that would become
# blank keeps the public header. Mode 600.
# Returns 0 when at least one assignment was removed.
cyclaw_dotenv_drop_matching_assignment() {
  local file="$1" key="$2" expect="$3" tmp old_umask line
  local changed=0 drop_line ranges start end name op val
  local stripped new left right bom
  [ -f "$file" ] || return 1
  old_umask="$(umask)"
  umask 077
  tmp="$(mktemp "${TMPDIR:-/tmp}/cyclaw.env.XXXXXX")"
  while IFS= read -r line || [ -n "$line" ]; do
    drop_line=0
    ranges=""
    while IFS=$'\x1f' read -r start end name op val; do
      [ "$start" = "@" ] && continue
      [ -n "$name" ] || continue
      if [ "$name" = "$key" ] && [ "$val" = "$expect" ]; then
        drop_line=1
        ranges="${ranges}${start}:${end}"$'\n'
      fi
    done < <(cyclaw_dotenv_line_spans "$line")
    if [ "$drop_line" -eq 0 ]; then
      printf '%s\n' "$line" >> "$tmp"
      continue
    fi
    changed=1
    # Spans are indexes into the BOM-stripped line. Cut from the right so
    # earlier indexes stay valid. What remains is the original text.
    stripped="$line"
    bom=$'\xef\xbb\xbf'
    case "$stripped" in
      "$bom"*) stripped="${stripped#"$bom"}" ;;
    esac
    bom=$'\ufeff'
    case "$stripped" in
      "$bom"*) stripped="${stripped#"$bom"}" ;;
    esac
    new="$stripped"
    while IFS=: read -r start end; do
      [ -n "${start:-}" ] || continue
      left="${new:0:start}"
      right="${new:end}"
      new="${left}${right}"
    done < <(printf '%s\n' "$ranges" | sort -t: -k1,1nr)
    # A leftover `export` or `declare -x` with no assignment and no comment
    # is not a setting. Drop it. Kept assignments and comments stay verbatim.
    case "$new" in
      *"="*|*"#"*) printf '%s\n' "$new" >> "$tmp" ;;
    esac
  done < "$file"
  if [ "$changed" -eq 0 ]; then
    rm -f "$tmp"
    umask "$old_umask"
    return 1
  fi
  if ! grep -q '[^[:space:]]' "$tmp"; then
    if command -v cyclaw_public_env_header >/dev/null 2>&1; then
      cyclaw_public_env_header > "$tmp"
    else
      printf '%s\n' "# CyClaw non-secret settings. Secrets are not stored here." > "$tmp"
    fi
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file"
  umask "$old_umask"
  return 0
}

# Last unquoted value of $key in $file. Returns 1 when the name is absent.
# An empty value is present and prints nothing.
cyclaw_dotenv_file_value() {
  local file="$1" key="$2" line name op val found=0 result=""
  [ -f "$file" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    while IFS=$'\x1f' read -r name op val; do
      if [ "$name" = "$key" ]; then
        found=1
        result="$val"
      fi
    done < <(cyclaw_dotenv_line_assignments "$line")
  done < "$file"
  [ "$found" -eq 1 ] || return 1
  printf '%s' "$result"
  return 0
}

# Load ordinary settings from a mode 600/400 dotenv into THIS shell.
# Never executes the file. Assignments are exported only through the parser.
# A line that is not a plain assignment (a command word, `eval`, `if`, braces)
# is not executed and contributes no exports. Secret-classified names are
# not exported.
cyclaw_source_public_env() {
  local file="$1" mode=""
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
  if cyclaw_file_has_unparsed_line "$file"; then
    echo "[cyclaw] warn : $file has a line that is not a plain assignment. That line was not executed. Values were not printed." >&2
  fi
  if cyclaw_file_has_secret_assignment "$file"; then
    echo "[cyclaw] warn : $file contains secret-classified names. Those lines were not exported. Re-run macos/setup-cyclaw-keys.sh to move allowlisted keys into the Keychain." >&2
  fi
  cyclaw_export_nonsecret_assignments "$file"
  return 0
}
