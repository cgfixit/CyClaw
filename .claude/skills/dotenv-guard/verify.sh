#!/usr/bin/env bash
# dotenv-guard verify: live-tree pass + one planted violation per rule +
# ratchet self-test. Needs only python3 (stdlib), git, and bash. A checker
# that cannot fail proves nothing, so every rule must trip on its own plant,
# and the negative controls in the clean tree must stay silent.
#
# Each mutation runs in a fresh throwaway git tree whose
# macos/setup-cyclaw-keys.sh is a small stub, so K4/K5 are exercised without
# depending on what the real script does on the branch under test. The live
# tree (step 1) is where the real script runs.
#
# A missing python interpreter, a syntax error in a parsed Python file, and
# an unreadable tracked file fail with exit 3. They must not skip.
set -uo pipefail

_src="${BASH_SOURCE[0]}"
case "$_src" in
  /*) here="${_src%/*}" ;;
  *) here="$(pwd)/${_src%/*}" ;;
esac
if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "env error: python interpreter not found" >&2
  exit 3
fi
PY="$(command -v python3 || command -v python)"

echo "== dotenv-guard verify =="

repo_root="$(cd "$here/../../.." && pwd)"
checker="$here/check_dotenv.py"

work="$(mktemp -d "${TMPDIR:-/tmp}/cyclaw-dotenv-guard.XXXXXX")" || exit 1
trap 'rm -rf "$work"' EXIT
empty="$work/empty-baseline.txt"
: >"$empty"

if ! "$PY" "$here/envline.py" --check-vectors >"$work/vectors.txt" 2>&1; then
  echo "envline vectors: FAIL" >&2
  cat "$work/vectors.txt" >&2
  exit 1
fi
echo "envline vectors: PASS"

# 1. The live tree with the shipped baseline must pass.
if "$PY" "$checker" --repo-root "$repo_root" >"$work/live.txt" 2>&1; then
  echo "live tree: PASS (exit 0)"
else
  echo "live tree: FAIL — new finding or stale baseline entry on this branch" >&2
  cat "$work/live.txt" >&2
  exit 1
fi

n=0
# _tree DEST: minimal git tree with the repo's .gitignore, a clean keys-script
# stub (stores one fake Keychain item, writes a settings-only dotenv and a
# filtered rc hook), and negative controls that must NOT be reported.
_tree() {
  local dest="$1"
  mkdir -p "$dest/macos" "$dest/tests" "$dest/scripts" "$dest/docs/audits" "$dest/config"
  cp "$repo_root/.gitignore" "$dest/.gitignore"
  cat >"$dest/macos/setup-cyclaw-keys.sh" <<'STUB'
#!/usr/bin/env bash
printf 'k\n' | security add-generic-password -s com.example.verify -w >/dev/null
mkdir -p "$HOME/.CyClaw"
printf 'CYCLAW_GATE_PORT=8787\n' > "$HOME/.CyClaw/.env"
printf '%s\n' 'cyclaw_source_public_env "$HOME/.CyClaw/.env"' >> "$HOME/.zshrc"
STUB
  # tests/ is out of K1 scope; stream plumbing, $GITHUB_ENV and a non-secret
  # setting are not K6 findings; docs/audits/ is out of K7 scope; a doc that
  # names a secret without assigning it is fine. The tracked settings.env
  # holds a comment, a non-secret multi-assignment, and an echo argument —
  # none of those are shell assignments of a secret.
  printf 'from dotenv import load_dotenv\n' >"$dest/tests/test_fixture.py"
  # shellcheck disable=SC2016  # literal $HOME / $GITHUB_ENV text for the planted script
  printf '%s\n' '#!/usr/bin/env bash' \
    'echo "CYCLAW_GATE_PORT=8787" >> "$HOME/.CyClaw/.env"' \
    'echo "GROK_API_KEY=unset; see the .env docs" >&2' \
    "echo 'GROK_API_KEY=dummy' >> \"\$GITHUB_ENV\"" >"$dest/scripts/ok.sh"
  # shellcheck disable=SC2016  # literal Markdown backticks
  printf '%s\n' 'Old note: `GROK_API_KEY=x` lived in `.env`.' >"$dest/docs/audits/old.md"
  printf '%s\n' 'Store GROK_API_KEY in the Keychain, never in a .env file.' >"$dest/docs/ok.md"
  printf '%s\n' '# GROK_API_KEY=not-an-assignment' \
    'CYCLAW_GATE_PORT=8787 OLLAMA_HOST=127.0.0.1' \
    'echo GROK_API_KEY=x' \
    'declare -x CYCLAW_GATE_PORT=8787' >"$dest/config/settings.env"
  printf '%s\n' 'export PATH="$PATH:$HOME/bin"' >"$dest/.envrc"
  git -C "$dest" init -q
  git -C "$dest" add -A
  git -C "$dest" add -f config/settings.env
}

# _expect NAME WANT_RC RULE PATTERN TREE [BASELINE]
# RULE is the only rule allowed to FAIL ("-" for none). PATTERN must appear.
_expect() {
  local name="$1" want_rc="$2" rule="$3" pattern="$4" tree="$5" base="${6:-$empty}"
  local out rc others
  git -C "$tree" add -A
  out="$("$PY" "$checker" --repo-root "$tree" --baseline "$base" 2>&1)"; rc=$?
  if [ "$rc" -ne "$want_rc" ]; then
    echo "$name: FAIL — expected exit $want_rc, got $rc" >&2; echo "$out" >&2; exit 1
  fi
  if [ -n "$pattern" ] && ! grep -qE -- "$pattern" <<<"$out"; then
    echo "$name: FAIL — output lacks /$pattern/" >&2; echo "$out" >&2; exit 1
  fi
  others="$(grep -E '^  FAIL  \[K[0-9]\]' <<<"$out" | grep -v -F "[$rule]" || true)"
  if [ -n "$others" ]; then
    echo "$name: FAIL — another rule tripped:" >&2; echo "$others" >&2; exit 1
  fi
  n=$((n + 1))
  echo "$name: PASS"
}

# _env NAME TREE REL BODY [SECRET] — tracked dotenv file (*.env is gitignored).
_env() {
  local name="$1" tree="$2" rel="$3" body="$4" secret_name="${5:-GROK_API_KEY}"
  mkdir -p "$tree/$(dirname "$rel")"
  printf '%s\n' "$body" >"$tree/$rel"
  git -C "$tree" add -f -- "$rel"
  _expect "$name" 2 K2 "FAIL  \\[K2\\] tracked ${rel} assigns ${secret_name}" "$tree"
}

# 2. The clean stub tree passes with an empty baseline: every negative control is silent.
t="$work/clean"; _tree "$t"
_expect "clean tree + negative controls" 0 - "0 new, 0 stale" "$t"

# 3. One plant per rule.
t="$work/e1"; _tree "$t"; mkdir -p "$t/pkg"
printf 'from dotenv import load_dotenv\nload_dotenv()\n' >"$t/pkg/boot.py"
_expect "K1 runtime dotenv import" 2 K1 'FAIL  \[K1\] pkg/boot.py:1 from dotenv import' "$t"

t="$work/e1b"; _tree "$t"; mkdir -p "$t/pkg"
printf 'class Settings:\n    env_file = ".env"\n' >"$t/pkg/settings.py"
_expect "K1 pydantic-settings env_file" 2 K1 'FAIL  \[K1\] pkg/settings.py' "$t"

t="$work/e2"; _tree "$t"; mkdir -p "$t/config"
printf 'CYCLAW_GATE_PORT=8787\nGROK_API_KEY=\n' >"$t/config/app.env"
git -C "$t" add -f config/app.env
_expect "K2 tracked env file names a secret (empty value)" 2 K2 'FAIL  \[K2\] tracked config/app.env assigns GROK_API_KEY' "$t"

# Assignment-form bypasses. Each must fail on its own; the clean tree's
# settings.env is the negative control for comments, echo, and non-secrets.
t="$work/e2multi"; _tree "$t"
_env "K2 second assignment on the line" "$t" "config/multi.env" "CYCLAW_GATE_PORT=8788 GROK_API_KEY=x"

t="$work/e2export"; _tree "$t"
_env "K2 export with a later secret" "$t" "config/export.env" "export A=1 GROK_API_KEY=x"

t="$work/e2lower"; _tree "$t"
_env "K2 lowercase secret name" "$t" "config/lower.env" "grok_api_key=x" "grok_api_key"

t="$work/e2mixed"; _tree "$t"
_env "K2 mixed-case secret name" "$t" "config/mixed.env" "Grok_Api_Key=x" "Grok_Api_Key"

t="$work/e2bom"; _tree "$t"
mkdir -p "$t/config"
printf '\xEF\xBB\xBFGROK_API_KEY=x\n' >"$t/config/bom.env"
git -C "$t" add -f config/bom.env
_expect "K2 leading UTF-8 BOM" 2 K2 'FAIL  \[K2\] tracked config/bom.env assigns GROK_API_KEY' "$t"

t="$work/e2decl"; _tree "$t"
_env "K2 declare -x" "$t" "config/declare.env" "declare -x GROK_API_KEY=x"

t="$work/e2typeset"; _tree "$t"
_env "K2 typeset" "$t" "config/typeset.env" "typeset GROK_API_KEY=x"

t="$work/e2ro"; _tree "$t"
_env "K2 readonly" "$t" "config/readonly.env" "readonly GROK_API_KEY=x"

t="$work/e2local"; _tree "$t"
_env "K2 local -x" "$t" "config/local.env" "local -x GROK_API_KEY=x"

t="$work/e2plus"; _tree "$t"
_env "K2 plus-equals" "$t" "config/plus.env" "GROK_API_KEY+=x"

t="$work/e2example"; _tree "$t"
mkdir -p "$t/config"
printf 'GROK_API_KEY=\n' >"$t/config/app.env.example"
_expect "K2 tracked app.env.example" 2 K2 'FAIL  \[K2\] tracked config/app.env.example assigns GROK_API_KEY' "$t"

t="$work/e2envrc"; _tree "$t"
printf 'GROK_API_KEY=x\n' >>"$t/.envrc"
_expect "K2 tracked .envrc" 2 K2 'FAIL  \[K2\] tracked .envrc assigns GROK_API_KEY' "$t"

t="$work/e2envdash"; _tree "$t"
printf 'GROK_API_KEY=x\n' >"$t/.env-local"
_expect "K2 tracked .env-local" 2 K2 'FAIL  \[K2\] tracked .env-local assigns GROK_API_KEY' "$t"

t="$work/e2suffix"; _tree "$t"
mkdir -p "$t/config"
printf '%s\n' 'GH_PAT=' 'SENTRY_DSN=' 'CYCLAW_DB_URL=' 'DB_CREDENTIALS=' 'AWS_ACCESS_KEY=' >"$t/config/suffix.env"
git -C "$t" add -f config/suffix.env
out="$("$PY" "$checker" --repo-root "$t" --baseline "$empty" 2>&1)"; rc=$?
if [ "$rc" -ne 2 ]; then
  echo "K2 widened suffixes: FAIL — expected exit 2, got $rc" >&2; echo "$out" >&2; exit 1
fi
for secret_name in GH_PAT SENTRY_DSN CYCLAW_DB_URL DB_CREDENTIALS AWS_ACCESS_KEY; do
  if ! grep -q "tracked config/suffix.env assigns ${secret_name}" <<<"$out"; then
    echo "K2 widened suffixes: FAIL — missing ${secret_name}" >&2; echo "$out" >&2; exit 1
  fi
done
others="$(grep -E '^  FAIL  \[K[0-9]\]' <<<"$out" | grep -v -F "[K2]" || true)"
if [ -n "$others" ]; then
  echo "K2 widened suffixes: FAIL — another rule tripped:" >&2; echo "$others" >&2; exit 1
fi
n=$((n + 1))
echo "K2 widened suffixes (_PAT _DSN _DB_URL _CREDENTIALS _KEY): PASS"

t="$work/e3"; _tree "$t"
printf '*.pyc\n' >"$t/.gitignore"
_expect "K3 .gitignore lost the dotenv patterns" 2 K3 'FAIL  \[K3\] \.env is not ignored' "$t"

t="$work/e4"; _tree "$t"
# The name reaches the write through a variable, the way _env_upsert gets it on
# main. K6 reads lines and cannot see this; only the K4 run can.
# shellcheck disable=SC2016
printf '%s\n' '#!/usr/bin/env bash' \
  "printf 'k\n' | security add-generic-password -s com.example.verify -w >/dev/null" \
  'name=GROK_API_KEY' \
  'mkdir -p "$HOME/.CyClaw"' \
  'printf "export %s=x\n" "$name" > "$HOME/.CyClaw/.env"' >"$t/macos/setup-cyclaw-keys.sh"
_expect "K4 installer writes a secret via a variable (invisible to K6)" 2 K4 'FAIL  \[K4\] probe wrote GROK_API_KEY into ~/.CyClaw/.env' "$t"

t="$work/e4c"; _tree "$t"
printf '#!/usr/bin/env bash\nexit 0\n' >"$t/macos/setup-cyclaw-keys.sh"
_expect "K4 positive control: a run that stores nothing" 2 K4 'could not run: keys-script probe stored no Keychain item' "$t"

t="$work/e5"; _tree "$t"
# shellcheck disable=SC2016
printf '%s\n' "printf '%s\\n' '. \"\$HOME/.CyClaw/.env\"' >> \"\$HOME/.zshrc\"" >>"$t/macos/setup-cyclaw-keys.sh"
# shellcheck disable=SC2016  # regex matches a literal $HOME
_expect "K5 rc block raw-sources the dotenv" 2 K5 'FAIL  \[K5\] ~/\.zshrc sources \$HOME/\.CyClaw/\.env' "$t"

t="$work/e5and"; _tree "$t"
cat >>"$t/macos/setup-cyclaw-keys.sh" <<'STUB'
printf '%s\n' '[ -f "$HOME/.CyClaw/.env" ] && . "$HOME/.CyClaw/.env"' >> "$HOME/.zshrc"
STUB
# shellcheck disable=SC2016
_expect "K5 rc sources after &&" 2 K5 'FAIL  \[K5\] ~/\.zshrc sources \$HOME/\.CyClaw/\.env' "$t"

t="$work/e5seta"; _tree "$t"
cat >>"$t/macos/setup-cyclaw-keys.sh" <<'STUB'
printf '%s\n' 'set -a; . "$HOME/.CyClaw/.env"' >> "$HOME/.zshrc"
STUB
# shellcheck disable=SC2016
_expect "K5 rc sources after set -a" 2 K5 'FAIL  \[K5\] ~/\.zshrc sources \$HOME/\.CyClaw/\.env' "$t"

t="$work/e5eval"; _tree "$t"
cat >>"$t/macos/setup-cyclaw-keys.sh" <<'STUB'
printf '%s\n' 'eval "$(cat "$HOME/.CyClaw/.env")"' >> "$HOME/.zshrc"
STUB
# shellcheck disable=SC2016
_expect "K5 rc eval cat of the dotenv" 2 K5 'FAIL  \[K5\] ~/\.zshrc eval-loads \$HOME/\.CyClaw/\.env' "$t"

t="$work/e5var"; _tree "$t"
cat >>"$t/macos/setup-cyclaw-keys.sh" <<'STUB'
printf '%s\n' '. "$var"' >> "$HOME/.zshrc"
STUB
# shellcheck disable=SC2016
_expect "K5 rc sources an unexpanded variable" 2 K5 'FAIL  \[K5\] ~/\.zshrc sources \$var' "$t"

t="$work/e5multi"; _tree "$t"
cat >>"$t/macos/setup-cyclaw-keys.sh" <<'STUB'
printf '%s\n' 'export A=1 GROK_API_KEY=x' >> "$HOME/.zshrc"
STUB
_expect "K5 rc multi-assignment" 2 K5 'FAIL  \[K5\] probe wrote GROK_API_KEY into ~/\.zshrc' "$t"

t="$work/e6"; _tree "$t"
# shellcheck disable=SC2016
printf '%s\n' '#!/usr/bin/env bash' 'echo "GROK_API_KEY=$k" >> "$HOME/.CyClaw/.env"' >"$t/scripts/redirect.sh"
_expect "K6 shell redirect" 2 K6 'FAIL  \[K6\] scripts/redirect.sh:2 writes GROK_API_KEY' "$t"

t="$work/e6case"; _tree "$t"
# shellcheck disable=SC2016
printf '%s\n' '#!/usr/bin/env bash' 'echo "grok_api_key=$k" >> "$HOME/.CyClaw/.env"' >"$t/scripts/redirect-lower.sh"
_expect "K6 lowercase secret on a redirect" 2 K6 'FAIL  \[K6\] scripts/redirect-lower.sh:2 writes grok_api_key' "$t"

t="$work/e6plus"; _tree "$t"
# shellcheck disable=SC2016
printf '%s\n' '#!/usr/bin/env bash' 'echo "GROK_API_KEY+=$k" >> "$HOME/.CyClaw/.env"' >"$t/scripts/redirect-plus.sh"
_expect "K6 plus-equals on a redirect" 2 K6 'FAIL  \[K6\] scripts/redirect-plus.sh:2 writes GROK_API_KEY' "$t"

t="$work/e6b"; _tree "$t"
# shellcheck disable=SC2016
printf '%s\n' '#!/usr/bin/env bash' 'cat > "$ENV_FILE" <<EOF' 'CYCLAW_GATE_PORT=8787' 'CYCLAW_API_KEY=$k' 'EOF' >"$t/scripts/heredoc.sh"
_expect "K6 heredoc into \$ENV_FILE" 2 K6 'FAIL  \[K6\] scripts/heredoc.sh:4 writes CYCLAW_API_KEY .*heredoc' "$t"

t="$work/e6c"; _tree "$t"
# shellcheck disable=SC2016
printf '%s\n' 'Add-Content -Path $envFile -Value "TELEGRAM_BOT_TOKEN=$t"' >"$t/scripts/Install.ps1"
_expect "K6 PowerShell Add-Content" 2 K6 'FAIL  \[K6\] scripts/Install.ps1:1 writes TELEGRAM_BOT_TOKEN' "$t"

t="$work/e7"; _tree "$t"
# shellcheck disable=SC2016  # literal Markdown backticks
printf '%s\n' 'Put `GROK_API_KEY=x` in your `.env`.' >"$t/docs/guide.md"
_expect "K7 doc line pairs a secret with .env" 2 K7 'FAIL  \[K7\] docs/guide.md:1 shows GROK_API_KEY' "$t"

t="$work/e7b"; _tree "$t"
printf '%s\n' 'Example:' '' '```dotenv' 'CYCLAW_GATE_PORT=8787' 'ANTHROPIC_API_KEY=x' '```' >"$t/docs/env-block.md"
_expect "K7 dotenv code block assigns a secret" 2 K7 'FAIL  \[K7\] docs/env-block.md:5 shows ANTHROPIC_API_KEY' "$t"

t="$work/e7case"; _tree "$t"
# shellcheck disable=SC2016
printf '%s\n' 'Put `grok_api_key=x` in your `.env`.' >"$t/docs/guide-lower.md"
_expect "K7 lowercase secret next to .env" 2 K7 'FAIL  \[K7\] docs/guide-lower.md:1 shows grok_api_key' "$t"

# 4. Ratchet.
t="$work/r1"; _tree "$t"
printf 'K2\tnope/app.env:GROK_API_KEY\tplanted stale entry\n' >"$work/stale.txt"
_expect "ratchet: stale baseline entry fails" 2 K2 "stale baseline entry 'nope/app.env:GROK_API_KEY'" "$t" "$work/stale.txt"

t="$work/r2"; _tree "$t"
# shellcheck disable=SC2016
printf '%s\n' '#!/usr/bin/env bash' 'echo "GROK_API_KEY=$k" >> "$HOME/.CyClaw/.env"' >"$t/scripts/redirect.sh"
printf 'K6\tscripts/redirect.sh:GROK_API_KEY\tplanted known finding\n' >"$work/known.txt"
_expect "ratchet: baselined finding is KNOWN, exit 0" 0 - 'KNOWN \[K6\] scripts/redirect.sh:2' "$t" "$work/known.txt"

t="$work/r3"; _tree "$t"
printf 'K6\tscripts/redirect.sh:GROK_API_KEY\n' >"$work/malformed.txt"
out="$("$PY" "$checker" --repo-root "$t" --baseline "$work/malformed.txt" 2>&1)"; rc=$?
if [ "$rc" -ne 3 ] || ! grep -q "want RULE<TAB>KEY<TAB>REASON" <<<"$out"; then
  echo "ratchet: malformed baseline: FAIL — expected exit 3, got $rc" >&2; echo "$out" >&2; exit 1
fi
n=$((n + 1)); echo "ratchet: malformed baseline (no reason) is an env error: PASS"

# 5. Inspection failures are exit 3, not a skip.
t="$work/syn"; _tree "$t"; mkdir -p "$t/pkg"
printf 'def (\n' >"$t/pkg/bad.py"
git -C "$t" add -A
out="$("$PY" "$checker" --repo-root "$t" --baseline "$empty" 2>&1)"; rc=$?
if [ "$rc" -ne 3 ] || ! grep -q "syntax error in pkg/bad.py" <<<"$out"; then
  echo "syntax error: FAIL — expected exit 3, got $rc" >&2; echo "$out" >&2; exit 1
fi
n=$((n + 1)); echo "syntax error in a parsed Python file is exit 3: PASS"

t="$work/unreadable"; _tree "$t"; mkdir -p "$t/pkg"
printf 'x = 1\n' >"$t/pkg/hidden.py"
git -C "$t" add -A
chmod 000 "$t/pkg/hidden.py"
out="$("$PY" "$checker" --repo-root "$t" --baseline "$empty" 2>&1)"; rc=$?
if [ "$rc" -ne 3 ] || ! grep -q "unreadable file: pkg/hidden.py" <<<"$out"; then
  echo "unreadable file: FAIL — expected exit 3, got $rc" >&2; echo "$out" >&2; exit 1
fi
n=$((n + 1)); echo "unreadable tracked file is exit 3: PASS"

mkdir -p "$work/nopython"
# Absolute bash: a PATH= prefix would otherwise hide `bash` itself.
bash_bin="$(command -v bash)"
out="$(PATH="$work/nopython" "$bash_bin" "$here/verify.sh" 2>&1)" && rc=0 || rc=$?
if [ "$rc" -ne 3 ] || ! grep -q "python interpreter not found" <<<"$out"; then
  echo "missing python: FAIL — expected exit 3, got $rc" >&2; echo "$out" >&2; exit 1
fi
n=$((n + 1)); echo "missing python interpreter is exit 3: PASS"

echo "== dotenv-guard verify: OK (live tree + $n self-tests) =="
