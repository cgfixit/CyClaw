#!/usr/bin/env bash
# config-guard verify — clean-tree pass + mutation self-test.
# Needs PyYAML (nested config parsing); SKIPs cleanly (exit 0) without it so a
# fresh pre-install container does not fail CI. A checker that cannot fail proves
# nothing — the mutation test keeps it honest.
# Mutations copy config.yaml AND macos/ollama-mlx.env because C12 reads the env
# file. Omitting it would FAIL C12 and poison the C7 WARN=exit-0 case.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../../.." && pwd)"
checker="$here/check_config.py"

echo "== config-guard verify =="

if python3 -c "import yaml" 2>/dev/null; then
  PY=python3
elif python -c "import yaml" 2>/dev/null; then
  PY=python
else
  echo "SKIP: PyYAML not importable; install project deps first." >&2
  exit 0
fi

work="$(mktemp -d "${TMPDIR:-/tmp}/cyclaw-config-guard.XXXXXX")" || exit 1
trap 'rm -rf "$work"' EXIT
live_out="$work/live.txt"
warn_out="$work/warn.txt"
posture_out="$work/posture.txt"

# 1. Clean tree must pass (exit 0).
if "$PY" "$checker" --repo-root "$repo_root" >"$live_out" 2>&1; then
  echo "clean tree: PASS (exit 0)"
else
  echo "clean tree: FAIL — the shipped config.yaml violates the contract" >&2
  cat "$live_out" >&2
  exit 1
fi

_copy_guard_inputs() {
  local dest="$1"
  mkdir -p "$dest/macos"
  cp "$repo_root/config.yaml" "$dest/config.yaml"
  cp "$repo_root/macos/ollama-mlx.env" "$dest/macos/ollama-mlx.env"
}

# 2a. FAIL-path mutation: break the graph/LLM timeout relation (C2).
tmp="$work/c2"
_copy_guard_inputs "$tmp"
# Value-agnostic on purpose: anchoring this on a literal (it was "330") makes the
# mutation silently match nothing the moment the shipped timeout is retuned, so the
# "mutated" config equals the clean one, check_config.py exits 0, and this self-test
# fails for a reason that has nothing to do with C2. 1 is below any sane llm timeout.
sed -i.bak 's/^\( *graph_timeout_sec:\) *[0-9][0-9]*/\1 1/' "$tmp/config.yaml"
grep -qE "graph_timeout_sec: 1([^0-9]|$)" "$tmp/config.yaml" || {
  echo "mutation A: setup FAILED — graph_timeout_sec was not rewritten; check the sed pattern" >&2
  exit 1
}

out="$("$PY" "$checker" --repo-root "$tmp" 2>&1)"; rc=$?
if [ "$rc" -ne 2 ]; then
  echo "mutation A (C2): FAIL — expected exit 2 on graph_timeout < llm_timeout, got $rc" >&2
  echo "$out" >&2
  exit 1
fi
echo "$out" | grep -q "FAIL  \[C2\]" || { echo "mutation A: C2 violation not reported" >&2; exit 1; }
echo "mutation A (C2 timeout relation): PASS (exit 2, C2 reported)"

# 2b. WARN semantics: a cosine-scale min_score is a WARN (exit 0) by default and
#     a failure only under --strict (C7 — the RRF-scale trap).
tmp2="$work/c7"
_copy_guard_inputs "$tmp2"
sed -i.bak 's/min_score: 0.028/min_score: 0.5/' "$tmp2/config.yaml"

if ! "$PY" "$checker" --repo-root "$tmp2" >"$warn_out" 2>&1; then
  echo "mutation B (C7): FAIL — a WARN alone must not fail (expected exit 0)" >&2
  cat "$warn_out" >&2
  exit 1
fi
grep -q "WARN  \[C7\]" "$warn_out" || { echo "mutation B: C7 warning not reported" >&2; exit 1; }
out="$("$PY" "$checker" --repo-root "$tmp2" --strict 2>&1)"; rc=$?
if [ "$rc" -ne 2 ]; then
  echo "mutation B (C7 --strict): FAIL — expected exit 2 under --strict, got $rc" >&2
  echo "$out" >&2
  exit 1
fi
echo "mutation B (C7 RRF-scale trap): PASS (WARN=exit 0, --strict=exit 2)"

# 2c. FAIL-path mutation: Ollama context below the RAG floor (C12).
tmp3="$work/c12"
_copy_guard_inputs "$tmp3"
sed -i.bak 's/^OLLAMA_CONTEXT_LENGTH=[0-9][0-9]*/OLLAMA_CONTEXT_LENGTH=1/' "$tmp3/macos/ollama-mlx.env"
grep -qE "^OLLAMA_CONTEXT_LENGTH=1([^0-9]|$)" "$tmp3/macos/ollama-mlx.env" || {
  echo "mutation C: setup FAILED — OLLAMA_CONTEXT_LENGTH was not rewritten; check the sed pattern" >&2
  exit 1
}
out="$("$PY" "$checker" --repo-root "$tmp3" 2>&1)"; rc=$?
if [ "$rc" -ne 2 ]; then
  echo "mutation C (C12): FAIL — expected exit 2 on OLLAMA_CONTEXT_LENGTH < RAG floor, got $rc" >&2
  echo "$out" >&2
  exit 1
fi
echo "$out" | grep -q "FAIL  \[C12\]" || { echo "mutation C: C12 violation not reported" >&2; exit 1; }
echo "mutation C (C12 Ollama context floor): PASS (exit 2, C12 reported)"

# 2d. WARN semantics: drift from the documented shipped provider posture is
#     visible by default and blocking under --strict (C9).
tmp4="$work/c9"
_copy_guard_inputs "$tmp4"
sed -i.bak 's/^\( *mode:\) *"hybrid"/\1 "offline"/' "$tmp4/config.yaml"
if ! "$PY" "$checker" --repo-root "$tmp4" >"$posture_out" 2>&1; then
  echo "mutation D (C9): FAIL — a WARN alone must not fail (expected exit 0)" >&2
  cat "$posture_out" >&2
  exit 1
fi
grep -q "WARN  \[C9\]" "$posture_out" || { echo "mutation D: C9 warning not reported" >&2; exit 1; }
out="$("$PY" "$checker" --repo-root "$tmp4" --strict 2>&1)"; rc=$?
if [ "$rc" -ne 2 ]; then
  echo "mutation D (C9 --strict): FAIL — expected exit 2 under --strict, got $rc" >&2
  echo "$out" >&2
  exit 1
fi
echo "mutation D (C9 shipped provider posture): PASS (WARN=exit 0, --strict=exit 2)"

echo "== config-guard verify: OK =="
