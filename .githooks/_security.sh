#!/usr/bin/env bash
# shellcheck shell=bash
# .githooks/_security.sh -- generic security gate for pre-commit and pre-push.
# How it works, overrides, and how to reuse it: docs/GITHOOKS.md
#
# Sourced by the hooks, never executed. Identical in every repo; repo-specific
# values live in .githooks/security.conf. Bash 3.2 compatible (stock macOS).
#
# Scope, on purpose. A hook earns its place only where CI is too late or
# cannot see the action at all:
#   1. Secrets, by content and by filename. Once pushed to a public remote the
#      bytes are burned; CI finding them afterwards is an incident report.
#   2. The three "ask first" actions an agent can take with plain git:
#      changing a control file, pushing to a protected branch, rewriting
#      pushed history.
# Everything slower or broader (tests, SAST, dependency audit) stays in CI.
#
# This is a speed bump, not a boundary: --no-verify skips it, a clone that
# never ran `git config core.hooksPath .githooks` does not have it, and any
# pipeline that pins core.hooksPath elsewhere bypasses it. CI secret scanning
# and the branch ruleset are the controls; this makes the common case fail
# early and tells the agent what to do at the moment it matters.
#
# Operator overrides. An agent setting one without being told to is a rule
# violation, and the variable is visible in its transcript:
#   HOOK_OPERATOR_ACK=1          allow a change to a protected path
#   ALLOW_MAIN_PUSH=1            allow a direct push to a protected branch
#   ALLOW_FORCE_WITH_LEASE=true  allow a non-fast-forward push
# Secret and blocked-file findings have no override variable. For a false
# positive: put `gitleaks:allow` on the line, or extend SEC_ALLOW_REGEX /
# SEC_BLOCKED_EXCEPT in security.conf (itself a protected path).

# ── Defaults (security.conf may replace or append with +=) ──────────────────

# Files that must never be committed, matched against the full path and the
# basename. `git add -f` and a "fixed" .gitignore both get past .gitignore;
# this does not care how the file got staged.
SEC_BLOCKED_GLOBS=(
  '.env' '.env.*' '*.env'
  '*.pem' '*.key' '*.p12' '*.pfx' '*.jks' '*.keystore' '*.kdbx'
  'id_rsa*' 'id_dsa*' 'id_ecdsa*' 'id_ed25519*'
  '.netrc' '.pypirc' '.git-credentials'
  'credentials.json' 'client_secret*.json' 'service-account*.json'
  'rclone.conf'
  '*.db' '*.db-wal' '*.db-shm' '*.sqlite' '*.sqlite3' '*.sqlite3-wal' '*.sqlite3-shm'
  '*.db.*' '*.sqlite3.*'   # renamed copies: soul.db.bak, auth.sqlite3.old
)
# Agent session residue: transcripts, local settings and tool state that
# coding agents write into the working tree. They carry prompts, file contents
# and sometimes tokens; none of it belongs in history.
SEC_BLOCKED_GLOBS+=(
  '.aider*' '.specstory/*' '.cursor/mcp.json' '.claude.json'
  'settings.local.json' 'CLAUDE.local.md' 'AGENTS.local.md' '.codex/auth.json'
  '*.chat.history.md' '.continue/sessions/*' '.gemini/tmp/*'
  '*.har' '*.pcap' '*.pcapng' '*.dmp' 'core.[0-9]*' '.DS_Store'
  '.bash_history' '.zsh_history' '.python_history' '.psql_history'
)
SEC_BLOCKED_EXCEPT=( '.env.example' '*.pub' )

# Where agents take their instructions and tools from. A change here alters
# what every later agent session does (a persistence path for prompt
# injection), so it is always called out. Tool wiring needs the operator.
SEC_AGENT_SURFACE_GLOBS=(
  'AGENTS.md' 'CLAUDE.md' 'GEMINI.md' '.cursorrules' 'copilot-instructions.md'
  'SKILL.md' '.claude/*' '.codex/*' '.cursor/*' '.github/skills/*' '.agent/*'
)
SEC_PROTECTED_AGENT_GLOBS=( '.mcp.json' 'mcp.json' 'mcp_manifest.json' '.claude/settings.json' '.codex/config.toml' )

# New files above this size are refused (binary blobs are where scanners
# cannot look). 0 disables.
SEC_MAX_NEW_FILE_KB=2048

# Paths that must stay ignored; probed with `git check-ignore`. A probe that
# is no longer ignored means .gitignore lost a rule.
SEC_IGNORE_PROBES=( '.env' '.env.local' 'probe.pem' 'probe.key' )

# Home-directory user names that are obviously placeholders.
SEC_GENERIC_USERS='REPLACE_USER|USERNAME|username|user|you|me|test|operator|op|x|u|example|runner|ubuntu|root|workdir|\.\.\.|<[^>]*>|\$[A-Za-z_{]+|%[A-Za-z]+%'

# Lines that usually mean a privacy or exposure regression. Reminder only.
SEC_RISKY_REGEX='verify *= *False|danger_accept_invalid_certs|InsecureSkipVerify|rejectUnauthorized: *false'
SEC_RISKY_REGEX+='|0\.0\.0\.0|allow_origins *= *\[? *["'"'"']\*|Access-Control-Allow-Origin: *\*'
SEC_RISKY_REGEX+='|curl [^|]*\| *(sudo +)?(ba|z)?sh|--no-verify|chmod +(-R +)?777'
SEC_RISKY_REGEX+='|(print|println!?|console\.log|log(ger)?\.[a-z]+|dbg!)\(.*(api_?key|token|password|secret|authorization|cookie)'

# Secure-by-design triggers. A hook cannot judge a design, but it can see the
# moment a diff creates a new trust-boundary crossing and put the right
# question in front of whoever (or whatever) wrote it. "regex@@question".
# Reminder only; the answer belongs in the PR body.
SEC_DESIGN_TRIGGERS=(
  '@(app|router|api)\.(get|post|put|patch|delete|websocket)\(|\.route\(|add_api_route|Router::new|\.nest\(@@NEW ENTRY POINT. Default-deny? Which auth dependency, and does it check ownership of the object, not just a valid session? Validated server-side with a schema? Rate-limited? Registered wherever routes are enumerated?'
  'requests\.(get|post|put|request)|httpx\.|aiohttp\.|urllib\.request|reqwest::|fetch\(|websockets?\.connect|smtplib|socket\.(create_)?connect@@NEW EGRESS. Is the destination on an explicit allowlist and behind the same gate as other external calls? What exact fields leave the machine, and are they minimized and redacted first? Timeout set, redirects off, TLS verified, response treated as untrusted input?'
  'subprocess\.|os\.system|Popen|Command::new|child_process|exec\(|eval\(|pickle\.load|yaml\.load\(|marshal\.loads@@NEW CODE-EXECUTION OR DESERIALIZATION PATH. Can any model output, retrieved text, filename or request field reach it? Fixed argv (no shell string)? Sandboxed, least privilege, bounded time and output?'
  'CREATE TABLE|ALTER TABLE|add_column|class [A-Za-z]+\((Base|SQLModel|BaseModel)\)|#\[derive\(.*(Serialize|FromRow)@@NEW PERSISTED OR SERIALIZED DATA. Is every field needed (collect less)? Which fields are personal or secret, and are they kept out of logs, exports, backups, embeddings and API responses by default? Retention and delete path? File mode 600?'
  'open\([^)]*["'"'"'][wa]b?["'"'"']|write_text|write_bytes|fs::write|File::create|shutil\.(copy|move)|os\.(remove|rename)|remove_file@@NEW FILE WRITE/DELETE. Is the path built from untrusted input? Resolve it, then require it to stay under the one allowed root (symlinks and case-insensitive filesystems included). Atomic write? Permissions?'
  'os\.environ|getenv|env::var|process\.env@@NEW CONFIG INPUT. Does the feature ship OFF and fail closed when the value is missing, empty or malformed (quoted "true" is not true)? If it is a secret: never logged, never echoed into errors, never returned by an API.'
  'logging\.|logger\.|log::(info|warn|error|debug)|tracing::|span\.|set_attribute|metrics?\.|counter|histogram@@NEW TELEMETRY. Log identifiers and outcomes, not content: no prompts, document text, tokens, emails, file paths with user names, or query strings. Does it pass through the existing redactor?'
  '(innerHTML|outerHTML|insertAdjacentHTML|document\.write|dangerouslySetInnerHTML|v-html|\|safe|Markup\()@@NEW HTML SINK. Model output and retrieved text are attacker-controlled. Use textContent or a sanitizer; keep the CSP nonce path intact.'
)
# Added lines whose "path:line:" prefix matches are skipped by the two
# reminder scans above (design questions, exposure-prone lines).
SEC_NON_CODE_REGEX='^(tests?/|docs?/|examples?/|\.githooks/|[^:]*\.(md|txt|lock):)'
# Dependency manifests: every new package is new code with your privileges.
SEC_DEP_GLOBS=( 'requirements*.txt' 'constraints.txt' 'pyproject.toml' 'environment.yml' 'Cargo.toml' 'package.json' 'Dockerfile' 'docker-compose.yml' '.github/workflows/*' )

# Operator identifiers (own name, emails, phone, employer, client names).
# NEVER set this in the tracked security.conf -- that would publish the list.
# Put it in ~/.config/githooks/private.conf (applies to every repo and every
# agent on this machine) or the untracked .githooks/security.local.conf.
SEC_PII_REGEX=''
# Commits whose author/committer email matches are refused (personal address
# in permanent public metadata). Set it in the same private file.
SEC_AUTHOR_EMAIL_DENY=''

# Control files: a change here needs HOOK_OPERATOR_ACK=1.
SEC_PROTECTED_GLOBS=( '.githooks/*' )

# Paths that only print a reminder.
SEC_NOTICE_GLOBS=()
SEC_NOTICE_TEXT='read the invariants before changing these.'

SEC_PROTECTED_BRANCHES=( main master )

# Extended regex. A finding whose "path:line:content" matches is dropped.
SEC_ALLOW_REGEX=''

# High-precision provider prefixes. Always on, with or without gitleaks.
# gitleaks (when installed) adds entropy-based detection of unprefixed secrets.
SEC__PATTERNS='xai-[A-Za-z0-9]{40,}'
SEC__PATTERNS+='|sk-ant-[A-Za-z0-9_-]{20,}'
SEC__PATTERNS+='|sk-(proj|svcacct|admin)-[A-Za-z0-9_-]{20,}'
SEC__PATTERNS+='|gh[pousr]_[A-Za-z0-9]{36,}'
SEC__PATTERNS+='|github_pat_[A-Za-z0-9_]{50,}'
SEC__PATTERNS+='|(AKIA|ASIA)[0-9A-Z]{16}'
SEC__PATTERNS+='|-----BEGIN [A-Z ]*PRIVATE KEY-----'
SEC__PATTERNS+='|[0-9]{8,10}:AA[A-Za-z0-9_-]{33}'
SEC__PATTERNS+='|xox[baprs]-[A-Za-z0-9-]{10,}'
SEC__PATTERNS+='|hf_[A-Za-z0-9]{34,}'
SEC__PATTERNS+='|AIza[0-9A-Za-z_-]{35}'
SEC__PATTERNS+='|sl\.[A-Za-z0-9_-]{100,}'

SEC_FILES=''
SEC__PUSH_FILES=''
sec__quiet=0   # 1 during pre-push: advisory text was already shown at commit time

sec__root="$(git rev-parse --show-toplevel)"
for sec__conf in "$sec__root/.githooks/security.conf" \
                 "${XDG_CONFIG_HOME:-$HOME/.config}/githooks/private.conf" \
                 "$sec__root/.githooks/security.local.conf"; do
  if [[ -f "$sec__conf" ]]; then
    # shellcheck source=/dev/null
    . "$sec__conf"
  fi
done

# ── Helpers ─────────────────────────────────────────────────────────────────

sec__say() { printf '%s\n' "$@" >&2; }

sec__zero() { [[ "$1" =~ ^0+$ ]]; }

# sec__match_any PATH GLOB...   true when PATH or its basename matches a glob.
sec__match_any() {
  local path="$1" base="${1##*/}" glob
  shift
  for glob in "$@"; do
    # shellcheck disable=SC2254
    case "$path" in $glob) return 0 ;; esac
    # shellcheck disable=SC2254
    case "$base" in $glob) return 0 ;; esac
  done
  return 1
}

# stdin: unified diff (git diff / git log -p). stdout: path:line:content for
# every added line.
sec__added_lines() {
  # NUL bytes (a binary file diffed as text) would be dropped by $(...) with a
  # warning; strip them first.
  LC_ALL=C tr -d '\000' | LC_ALL=C awk '
    /^\+\+\+ / { f = $0; sub(/^\+\+\+ (b\/)?/, "", f); next }
    /^@@ /     { n = $0; sub(/^@@ -[0-9,]+ \+/, "", n); sub(/[ ,].*/, "", n); ln = n + 0; next }
    /^\+/      { print f ":" ln ":" substr($0, 2); ln++; next }
    /^ /       { ln++ }
  '
}

# sec__check_files FILES WHERE   (FILES newline-separated)
sec__check_files() {
  local files="$1" where="$2" f rc=0 blocked='' protected='' notice='' surface='' deps=''
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    if sec__match_any "$f" ${SEC_BLOCKED_GLOBS[@]+"${SEC_BLOCKED_GLOBS[@]}"} &&
       ! sec__match_any "$f" ${SEC_BLOCKED_EXCEPT[@]+"${SEC_BLOCKED_EXCEPT[@]}"}; then
      blocked+="    $f"$'\n'
    fi
    if sec__match_any "$f" ${SEC_PROTECTED_GLOBS[@]+"${SEC_PROTECTED_GLOBS[@]}"} ||
       sec__match_any "$f" ${SEC_PROTECTED_AGENT_GLOBS[@]+"${SEC_PROTECTED_AGENT_GLOBS[@]}"}; then
      protected+="    $f"$'\n'
    elif sec__match_any "$f" ${SEC_AGENT_SURFACE_GLOBS[@]+"${SEC_AGENT_SURFACE_GLOBS[@]}"}; then
      surface+="    $f"$'\n'
    fi
    if sec__match_any "$f" ${SEC_DEP_GLOBS[@]+"${SEC_DEP_GLOBS[@]}"}; then
      deps+="    $f"$'\n'
    fi
    if sec__match_any "$f" ${SEC_NOTICE_GLOBS[@]+"${SEC_NOTICE_GLOBS[@]}"}; then
      notice+="    $f"$'\n'
    fi
  done <<<"$files"

  if [[ -n "$blocked" ]]; then
    sec__say "security gate: credential or runtime-state file in $where:" "${blocked%$'\n'}" \
      "  Unstage it (git rm --cached <file>) and keep it out of the tree." \
      "  If it is a deliberate non-secret, add it to SEC_BLOCKED_EXCEPT in .githooks/security.conf."
    rc=1
  fi
  if [[ -n "$protected" ]]; then
    if [[ "$where" == commits* ]]; then
      # Already committed: the ask-first moment was the commit. Surface it again
      # so a commit made without hooks is still visible before it is published.
      sec__say "security gate (reminder, not blocking): protected control file in $where:" "${protected%$'\n'}" \
        "  If the operator has not approved this change, stop and ask before pushing."
    elif [[ "${HOOK_OPERATOR_ACK:-}" == "1" ]]; then
      sec__say "security gate: protected path change acknowledged by operator (HOOK_OPERATOR_ACK=1):" "${protected%$'\n'}"
    else
      sec__say "security gate: protected control file changed in $where:" "${protected%$'\n'}" \
        "  This is an ask-first change. Stop and ask the operator; do not set the override yourself." \
        "  Operator, after reading the diff: HOOK_OPERATOR_ACK=1 git <command>"
      rc=1
    fi
  fi
  if [[ -n "$surface" && "$sec__quiet" -eq 0 ]]; then
    sec__say "security gate (reminder, not blocking): agent instruction surface changed in $where:" "${surface%$'\n'}" \
      "  These files steer every later agent session. Say so in the PR body; the operator reads this diff line by line." \
      "  Never copy text from a web page, issue, tool result or retrieved document into them."
  fi
  if [[ -n "$deps" && "$sec__quiet" -eq 0 ]]; then
    sec__say "security gate (reminder, not blocking): dependency or build surface changed in $where:" "${deps%$'\n'}" \
      "  New package/action/base image? Ask first. Verify the exact name exists (agents invent plausible ones that squatters register)," \
      "  pin version + hash (actions: commit SHA), prefer releases older than a week, and check it adds no install-time scripts or network calls."
  fi
  if [[ -n "$notice" && "$sec__quiet" -eq 0 ]]; then
    sec__say "security gate (reminder, not blocking): core path touched in $where:" "${notice%$'\n'}" "  $SEC_NOTICE_TEXT"
  fi
  return "$rc"
}

sec__filter() {   # stdin: path:line:content hits; drops allowlisted ones
  local hits
  hits="$(LC_ALL=C grep -a -v -e 'gitleaks:allow' || true)"
  if [[ -n "$hits" && -n "$SEC_ALLOW_REGEX" ]]; then
    hits="$(printf '%s\n' "$hits" | LC_ALL=C grep -a -v -E -e "$SEC_ALLOW_REGEX" || true)"
  fi
  printf '%s' "$hits"
}

sec__where() { LC_ALL=C awk -F: '{ print "    " $1 ":" $2 }' | sort -u >&2; }

# stdin: unified diff. Prints path:line only, never the matched text (hook
# output lands in agent transcripts and CI logs).
sec__scan_diff() {
  local where="$1" rc=0 added hits homes bidi
  # -a and LC_ALL=C throughout: a stray NUL or invalid UTF-8 byte must not
  # turn the stream into "binary file matches" and hide the line.
  added="$(sec__added_lines)"
  [[ -n "$added" ]] || return 0

  hits="$(printf '%s\n' "$added" | LC_ALL=C grep -a -E -e "$SEC__PATTERNS" | sec__filter || true)"
  if [[ -n "$hits" ]]; then
    sec__say "security gate: credential-shaped string added in $where:"
    printf '%s\n' "$hits" | sec__where
    sec__say "  If it is real: remove it AND rotate it now (it is already in local history)." \
      "  If it is a fixture: use an obviously fake value, or mark the line gitleaks:allow."
    rc=1
  fi

  if [[ -n "$SEC_PII_REGEX" ]]; then
    hits="$(printf '%s\n' "$added" | LC_ALL=C grep -a -i -E -e "$SEC_PII_REGEX" | sec__filter || true)"
    if [[ -n "$hits" ]]; then
      sec__say "security gate: operator-private identifier added in $where:"
      printf '%s\n' "$hits" | sec__where
      sec__say "  Replace it with a placeholder (example.com, 555-01xx, <operator>)."
      rc=1
    fi
  fi

  # Absolute home paths leak the local account name and disk layout; agents
  # paste them from tool output into docs, fixtures and logs.
  homes="$(printf '%s\n' "$added" |
    LC_ALL=C sed -E "s#(/Users/|/home/|[A-Za-z]:\\\\+Users\\\\+)(${SEC_GENERIC_USERS})([^A-Za-z0-9._-]|\$)#\\3#g" |
    LC_ALL=C grep -a -E -e '(/Users/|/home/|[A-Za-z]:\\+Users\\+)[A-Za-z0-9._-]+' | sec__filter || true)"
  if [[ -n "$homes" ]]; then
    sec__say "security gate: absolute home-directory path added in $where:"
    printf '%s\n' "$homes" | sec__where
    sec__say "  Use ~, \$HOME, %USERPROFILE% or a placeholder user (/Users/you)."
    rc=1
  fi

  # Bidirectional overrides and Unicode tag characters are invisible in a
  # diff: Trojan-Source edits in code, hidden instructions in agent files.
  bidi="$(printf '%s\n' "$added" |
    LC_ALL=C grep -a -e $'\xe2\x80[\xaa-\xae]' -e $'\xe2\x81[\xa6-\xa9]' -e $'\xf3\xa0[\x80\x81]' | sec__filter || true)"
  if [[ -n "$bidi" ]]; then
    sec__say "security gate: invisible bidi-override or Unicode tag character added in $where:"
    printf '%s\n' "$bidi" | sec__where
    sec__say "  Remove it, or write it as an escape (\\u202e). A deliberate test fixture: mark the line gitleaks:allow."
    rc=1
  fi

  [[ "$sec__quiet" -eq 0 ]] || return "$rc"
  # Reminders below are about product code, not tests, docs or the hooks.
  local code trig rx q shown=0
  code="$(printf '%s\n' "$added" | LC_ALL=C grep -a -v -E -e "$SEC_NON_CODE_REGEX" || true)"
  [[ -n "$code" ]] || return "$rc"
  for trig in ${SEC_DESIGN_TRIGGERS[@]+"${SEC_DESIGN_TRIGGERS[@]}"}; do
    rx="${trig%%@@*}"; q="${trig#*@@}"
    hits="$(printf '%s\n' "$code" | LC_ALL=C grep -a -E -e "$rx" | sec__filter || true)"
    [[ -n "$hits" ]] || continue
    if [[ "$shown" -eq 0 ]]; then
      sec__say "security gate (secure-by-design questions, not blocking) for $where -- answer in the PR body:"
      shown=1
    fi
    sec__say "  * $q"
    printf '%s\n' "$hits" | LC_ALL=C awk -F: '{ print "      " $1 ":" $2 }' | sort -u | LC_ALL=C awk 'NR <= 3' >&2
  done

  hits="$(printf '%s\n' "$code" | LC_ALL=C grep -a -i -E -e "$SEC_RISKY_REGEX" | sec__filter || true)"
  if [[ -n "$hits" ]]; then
    sec__say "security gate (reminder, not blocking): exposure-prone line added in $where:"
    printf '%s\n' "$hits" | sec__where
    sec__say "  Check: TLS verification off, non-loopback bind, wildcard CORS, pipe-to-shell, hook bypass, or a secret/PII value in a log call."
  fi
  return "$rc"
}

# Staged-tree checks that need the index, not a diff stream.
sec__check_tree() {
  local rc=0 f size probe lost='' removed ident
  # 1. .gitignore must not lose rules without the operator.
  removed="$(git diff --cached --no-color -U0 -- '.gitignore' '*/.gitignore' | LC_ALL=C grep -a -E '^-[^-]' | LC_ALL=C grep -a -v -E '^-[[:space:]]*(#|$)' || true)"
  if [[ -n "$removed" && "${HOOK_OPERATOR_ACK:-}" != "1" ]]; then
    sec__say "security gate: .gitignore rules removed or rewritten:" "$(printf '%s\n' "$removed" | sed 's/^/    /')" \
      "  Un-ignoring is how runtime state and keys reach history. Ask-first: HOOK_OPERATOR_ACK=1 (operator only)."
    rc=1
  fi
  for probe in ${SEC_IGNORE_PROBES[@]+"${SEC_IGNORE_PROBES[@]}"}; do
    git check-ignore -q --no-index "$probe" 2>/dev/null || lost+=" $probe"
  done
  if [[ -n "$lost" ]]; then
    sec__say "security gate (reminder, not blocking): .gitignore does not cover:$lost" \
      "  Add the rule; the filename block above still catches a staged copy."
  fi
  # 2. New large files and media.
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    size="$(git cat-file -s ":$f" 2>/dev/null || echo 0)"
    if [[ "$SEC_MAX_NEW_FILE_KB" -gt 0 && "$size" -gt $((SEC_MAX_NEW_FILE_KB * 1024)) ]]; then
      sec__say "security gate: new file over ${SEC_MAX_NEW_FILE_KB} KiB: $f ($((size / 1024)) KiB)" \
        "  History keeps it forever and scanners skip it. Host it elsewhere, or raise SEC_MAX_NEW_FILE_KB with the operator."
      rc=1
    fi
    case "$f" in
      *.png|*.jpg|*.jpeg|*.heic|*.gif|*.webp|*.mp4|*.mov|*.pdf|*.docx|*.xlsx|*.pptx|*.PNG|*.JPG|*.JPEG|*.PDF)
        if command -v exiftool >/dev/null 2>&1 &&
           git show ":$f" | exiftool -fast -s -GPS:all -Author -Creator -LastModifiedBy -OwnerName -SerialNumber - 2>/dev/null | grep . >/dev/null; then
          sec__say "security gate: $f carries GPS/author/device metadata. Strip it: exiftool -all= -overwrite_original '$f'"
          rc=1
        else
          sec__say "security gate (reminder, not blocking): media/document added: $f" \
            "  Look at it: names, emails, tokens, tabs, paths, notifications in frame? Metadata stripped (exiftool -all=)?"
        fi ;;
      *.zip|*.tar|*.tgz|*.gz|*.7z|*.rar)
        sec__say "security gate (reminder, not blocking): archive added: $f -- secret scanners do not look inside." ;;
    esac
  done <<<"$(git -c core.quotePath=false diff --cached --name-only --diff-filter=A)"
  # 3. Commit identity is permanent public metadata.
  if [[ -n "$SEC_AUTHOR_EMAIL_DENY" ]]; then
    # Captured first, and no `grep -q` at the end of a pipe: under pipefail an
    # early grep exit can SIGPIPE the writer and turn a match into a failure.
    ident="$(git var GIT_AUTHOR_IDENT 2>/dev/null; git var GIT_COMMITTER_IDENT 2>/dev/null)"
    if printf '%s\n' "$ident" | LC_ALL=C grep -a -i -E -e "$SEC_AUTHOR_EMAIL_DENY" >/dev/null; then
      sec__say "security gate: this commit would carry a private email address in its author/committer field." \
        "  Use the GitHub noreply address: git config user.email <id>+<login>@users.noreply.github.com"
      rc=1
    fi
  fi
  return "$rc"
}

sec__gitleaks() {   # sec__gitleaks WHERE ARGS...
  local where="$1"
  shift
  if ! command -v gitleaks >/dev/null 2>&1; then
    sec__say "security gate: gitleaks not installed -- prefix patterns only for $where (brew install gitleaks)."
    return 0
  fi
  if ! (cd "$sec__root" && gitleaks git --redact --no-banner --log-level error --no-color --verbose "$@" . >&2); then
    sec__say "security gate: gitleaks reported a finding in $where (output above, redacted)."
    return 1
  fi
}

# ── Entry points ────────────────────────────────────────────────────────────

sec_pre_commit() {
  local rc=0 files
  files="$(git -c core.quotePath=false diff --cached --name-only --diff-filter=ACMR)"
  [[ -n "$files" ]] || return 0
  SEC_FILES="$files"

  sec__check_files "$files" "staged changes" || rc=1
  git diff --cached --no-color --no-ext-diff -U0 --diff-filter=ACMR |
    sec__scan_diff "staged changes" || rc=1
  sec__gitleaks "staged changes" --pre-commit --staged || rc=1
  sec__check_tree || rc=1

  if declare -F sec_repo_pre_commit >/dev/null; then
    sec_repo_pre_commit || rc=1
  fi
  if [[ "$rc" -ne 0 ]]; then
    sec__say "" "pre-commit: refused by the security gate (.githooks/_security.sh)."
  fi
  return "$rc"
}

# sec_pre_push_ref REMOTE LOCAL_REF LOCAL_SHA REMOTE_REF REMOTE_SHA
sec_pre_push_ref() {
  local remote="$1" local_sha="$3" remote_ref="$4" remote_sha="$5"
  sec__quiet=1
  local rc=0 branch='' b is_protected=0 known_remote=0 files not_arg
  local -a range

  if [[ "$remote_ref" == refs/heads/* ]]; then
    branch="${remote_ref#refs/heads/}"
    for b in ${SEC_PROTECTED_BRANCHES[@]+"${SEC_PROTECTED_BRANCHES[@]}"}; do
      [[ "$branch" == "$b" ]] && is_protected=1
    done
  fi

  if sec__zero "$local_sha"; then   # branch or tag delete
    if [[ "$is_protected" -eq 1 ]]; then
      sec__say "security gate: refused deleting protected branch '$branch'."
      return 1
    fi
    return 0
  fi

  if [[ "$is_protected" -eq 1 && "${ALLOW_MAIN_PUSH:-}" != "1" ]]; then
    sec__say "security gate: refused direct push to protected branch '$branch'." \
      "  Open a draft PR from a feature branch. Operator override: ALLOW_MAIN_PUSH=1 git push"
    rc=1
  fi

  if ! sec__zero "$remote_sha" && git cat-file -e "${remote_sha}^{commit}" 2>/dev/null; then
    known_remote=1
  fi
  if ! sec__zero "$remote_sha"; then
    if [[ "$known_remote" -eq 0 ]] || ! git merge-base --is-ancestor "$remote_sha" "$local_sha"; then
      if [[ "${ALLOW_FORCE_WITH_LEASE:-}" != "true" ]]; then
        sec__say "security gate: refused non-fast-forward push to '${branch:-$remote_ref}' (it rewrites pushed history)." \
          "  This is an ask-first action. Operator override: ALLOW_FORCE_WITH_LEASE=true git push --force-with-lease"
        rc=1
      fi
    fi
  fi

  # The commits this push would publish for the first time.
  if [[ "$known_remote" -eq 1 ]]; then
    range=( "${remote_sha}..${local_sha}" )
  else
    not_arg='--remotes'
    if git remote | grep -x -e "$remote" >/dev/null; then not_arg="--remotes=$remote"; fi
    range=( "$local_sha" --not "$not_arg" )
  fi

  # Per commit, not tip-vs-base: a secret added in one commit and deleted in
  # the next is still published.
  files="$(git -c core.quotePath=false log --no-color --format= --name-only --diff-filter=ACMR "${range[@]}" | sed '/^$/d' | sort -u)"
  if [[ -n "$files" ]]; then
    SEC__PUSH_FILES+="$files"$'\n'
    sec__check_files "$files" "commits being pushed to '${branch:-$remote_ref}'" || rc=1
    git log --no-color --no-ext-diff -p -U0 --format='commit %H' "${range[@]}" |
      sec__scan_diff "commits being pushed to '${branch:-$remote_ref}'" || rc=1
    sec__gitleaks "commits being pushed" "--log-opts=${range[*]}" || rc=1
  fi
  return "$rc"
}

sec_pre_push_finish() {
  local rc=0
  SEC_FILES="$(printf '%s' "$SEC__PUSH_FILES" | sed '/^$/d' | sort -u)"
  if [[ -n "$SEC_FILES" ]] && declare -F sec_repo_pre_push >/dev/null; then
    sec_repo_pre_push || rc=1
  fi
  return "$rc"
}
