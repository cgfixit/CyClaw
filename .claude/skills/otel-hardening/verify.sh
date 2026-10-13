#!/usr/bin/env bash
# otel-hardening verify — clean-tree pass + mutation self-test.
# Pure stdlib (tomllib); safe to run before any pip install. Exit 0 = healthy.
# A checker that cannot fail proves nothing — every rule that can FAIL or WARN
# (T1-T5, T7-T14; T6 is info-only and has nothing to flip) is exercised below
# by a mutation that must flip it, and each mutation asserts it actually
# changed the file first (two prior silent-no-op sed bugs are documented in
# git history at the old T3/T5 scenarios; the assert-changed discipline is
# why). No test here touches the network.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../../.." && pwd)"
checker="$here/check_otel.py"

# The date the shipped contract was last reviewed. Used to make the strict
# clean-tree run deterministic forever; the non-strict run uses today so real
# staleness still surfaces (as WARN, exit 0) without breaking this script.
AS_OF="2026-08-27"

echo "== otel-hardening verify =="

# Unique capture files, never a fixed name under the world-writable /tmp: a
# predictable path can be pre-created as a symlink by another local user and
# the `>` redirection would follow it and truncate the target. CodeQL flagged
# exactly this on the harness port (cgfixit/CG-agent-harness#295); same fix.
live_out="$(mktemp)"
strict_out="$(mktemp)"
trap 'rm -f "$live_out" "$strict_out"' EXIT INT TERM

# 1. Clean tree, default severity, live date: must exit 0.
if python3 "$checker" --repo-root "$repo_root" >"$live_out" 2>&1; then
  echo "clean tree (default): PASS (exit 0)"
else
  echo "clean tree (default): FAIL — the shipped kill-switch contract is broken" >&2
  cat "$live_out" >&2
  exit 1
fi

# 2. Clean tree, --strict, pinned date: zero warnings allowed at the review date.
if python3 "$checker" --repo-root "$repo_root" --strict --as-of "$AS_OF" >"$strict_out" 2>&1; then
  echo "clean tree (--strict @ $AS_OF): PASS (exit 0)"
else
  echo "clean tree (--strict @ $AS_OF): FAIL — a WARN-class regression landed" >&2
  cat "$strict_out" >&2
  exit 1
fi
if grep -q 'conda (environment.yml): onnxruntime pinned 1.30.0' "$strict_out"; then
  echo "T13 conda pip-subsection pin: PASS"
else
  echo "T13 conda pip-subsection pin: FAIL — environment.yml pin was not recognized" >&2
  exit 1
fi

# Fresh temp repo carrying everything the checker reads (a partial tree would
# fail checks for the wrong reason and mask what a mutation actually proved).
_mktree() {
  local d; d="$(mktemp -d)"
  mkdir -p "$d/utils" "$d/retrieval" "$d/guardrails" "$d/docs/security-philosophy" \
           "$d/macos" "$d/powershell" "$d/windows" "$d/agentic/executor" \
           "$d/agentic/fsconnect" "$d/sync" "$d/telegram" "$d/opentweet"
  cp "$repo_root/pyproject.toml" "$repo_root/constraints.txt" "$repo_root/requirements.txt" \
     "$repo_root/environment.yml" "$repo_root/Dockerfile" "$repo_root/docker-compose.yml" "$d/"
  cp "$repo_root/utils/telemetry_kill.py" "$repo_root/utils/onnx_telemetry.py" \
     "$repo_root/utils/external_pre_hook.py" "$d/utils/"
  cp "$repo_root/retrieval/embeddings.py" "$repo_root/retrieval/vector_store.py" "$d/retrieval/"
  cp "$repo_root/guardrails/integration.py" "$d/guardrails/"
  cp "$repo_root/docs/security-philosophy/cyclaw_telemetry_kill.env" "$d/docs/security-philosophy/"
  cp "$repo_root/macos/invoke-cyclaw.sh" "$repo_root/macos/generate_service_plist.py" "$d/macos/"
  cp "$repo_root/powershell/Invoke-CyClaw.ps1" "$repo_root/powershell/Install-CyClaw.ps1" "$d/powershell/"
  cp "$repo_root/windows/generate_service_task.py" "$d/windows/"
  cp "$repo_root/agentic/executor/runner.py" "$d/agentic/executor/"
  cp "$repo_root/agentic/gh_client.py" "$repo_root/agentic/writer.py" "$d/agentic/"
  cp "$repo_root/agentic/fsconnect/cli.py" "$d/agentic/fsconnect/"
  cp "$repo_root/sync/cli.py" "$repo_root/sync/scheduler.py" "$d/sync/"
  cp "$repo_root/telegram/cli.py" "$d/telegram/"
  cp "$repo_root/opentweet/cli.py" "$d/opentweet/"
  # Every FIXED_LAUNCHER_SITES file, read from the checker's own table so the
  # scratch tree and the rule can never drift apart (a site file absent here
  # would surface as a spurious "is missing" WARN in every scenario).
  python3 - "$checker" <<'PY' | while IFS= read -r rel; do
import ast, sys
tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
for node in tree.body:
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") in ("FIXED_LAUNCHER_SITES",
                                                                              "DYNAMIC_LAUNCHER_SITES"):
        for _component, rel, _markers in ast.literal_eval(node.value):
            print(rel)
    # repo-relative evidence sources too: T13 fails a row whose url path is absent
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "INVENTORY":
        for row in ast.literal_eval(node.value):
            url = str(row.get("url", ""))
            if url and not url.startswith(("http://", "https://")):
                print(url)
PY
    if [ -d "$repo_root/$rel" ]; then
      mkdir -p "$d/$rel"
    else
      mkdir -p "$d/$(dirname "$rel")"
      cp "$repo_root/$rel" "$d/$rel"
    fi
  done
  echo "$d"
}

fails=0

# run_mutation NAME EXPECT_RC GREP_PATTERN [--strict]
# The temp tree is prepared by the caller in $a; cleans it up afterwards.
_expect() {
  local name="$1" expect_rc="$2" pattern="$3" extra="${4:-}"
  local out rc
  out="$(python3 "$checker" --repo-root "$a" --as-of "$AS_OF" $extra 2>&1)"; rc=$?
  if [ "$rc" -eq "$expect_rc" ] && echo "$out" | grep -q "$pattern"; then
    echo "$name: PASS"
  else
    echo "$name: FAIL — expected rc=$expect_rc + /$pattern/, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
  rm -rf "$a"
}

# _mutate FILE PYTHON_SNIPPET — applies the snippet and asserts it changed the file.
_mutate() {
  local file="$1" snippet="$2"
  python3 - "$file" <<PYEOF
import sys
path = sys.argv[1]
before = open(path, encoding="utf-8").read()
text = before
$snippet
assert text != before, "mutation was a silent no-op -- update this scenario"
open(path, "w", encoding="utf-8").write(text)
PYEOF
}

# 3. T1: empty the TELEMETRY_KILL dict entirely.
a="$(_mktree)"
_mutate "$a/utils/telemetry_kill.py" '
import re
text = re.sub(r"TELEMETRY_KILL: dict\[str, str\] = \{.*?\n\}", "TELEMETRY_KILL: dict[str, str] = {}", text, count=1, flags=re.S)'
_expect "T1 empty-dict mutation" 2 "FAIL  \[T1\]"

# 4. T2: VALUE flip — OTEL_SDK_DISABLED true -> false (key survives; only the
#    independent value oracle can catch this).
a="$(_mktree)"
_mutate "$a/utils/telemetry_kill.py" '
text = text.replace("\"OTEL_SDK_DISABLED\": \"true\"", "\"OTEL_SDK_DISABLED\": \"false\"", 1)'
_expect "T2 value-flip (SDK re-enabled) mutation" 2 "FAIL  \[T2\]"

# 5. T2: VALUE flip — exporter none -> otlp.
a="$(_mktree)"
_mutate "$a/utils/telemetry_kill.py" '
text = text.replace("\"OTEL_TRACES_EXPORTER\": \"none\"", "\"OTEL_TRACES_EXPORTER\": \"otlp\"", 1)'
_expect "T2 exporter none->otlp mutation" 2 "FAIL  \[T2\]"

# 6. T2: dropped key (ANONYMIZED_TELEMETRY).
a="$(_mktree)"
_mutate "$a/utils/telemetry_kill.py" '
text = text.replace("    \"ANONYMIZED_TELEMETRY\": \"False\",\n", "", 1)'
_expect "T2 dropped-key mutation" 2 "FAIL  \[T2\]"

# 7. T2: update-check value flip 1 -> 0.
a="$(_mktree)"
_mutate "$a/utils/telemetry_kill.py" '
text = text.replace("\"PIP_DISABLE_PIP_VERSION_CHECK\": \"1\"", "\"PIP_DISABLE_PIP_VERSION_CHECK\": \"0\"", 1)'
_expect "T2 update-check 1->0 mutation" 2 "FAIL  \[T2\]"

# 8. T3: scrub-name deletion (declarative OTel config pointer survives).
a="$(_mktree)"
_mutate "$a/utils/telemetry_kill.py" '
text = text.replace("    \"OTEL_CONFIG_FILE\",\n", "", 1)'
_expect "T3 dropped-scrub-name mutation" 2 "FAIL  \[T3\]"

# 9. T4 staleness via injected future date: WARN by default, exit 2 under --strict.
a="$(_mktree)"
out="$(python3 "$checker" --repo-root "$a" --as-of 2027-12-31 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && echo "$out" | grep -q "WARN  \[T4\]"; then
  echo "T4 future --as-of (default): PASS (WARN, exit 0)"
else
  echo "T4 future --as-of (default): FAIL — expected WARN/exit 0, got rc=$rc" >&2
  echo "$out" >&2
  fails=$((fails + 1))
fi
out="$(python3 "$checker" --repo-root "$a" --as-of 2027-12-31 --strict 2>&1)"; rc=$?
if [ "$rc" -eq 2 ]; then
  echo "T4 future --as-of (--strict): PASS (escalated to exit 2)"
else
  echo "T4 future --as-of (--strict): FAIL — expected exit 2, got rc=$rc" >&2
  fails=$((fails + 1))
fi
rm -rf "$a"

# 10. T5: vendor pin drift (pattern-matched bump, never a hardcoded literal).
a="$(_mktree)"
_mutate "$a/pyproject.toml" '
import re
text, n = re.subn(r"langgraph==[0-9]+\.[0-9]+\.[0-9]+", "langgraph==1.9.9", text)
assert n >= 1'
_expect "T5 vendor-pin-drift mutation" 0 "WARN  \[T5\]"

# 11. T7: conditional-offline wiring renamed away.
a="$(_mktree)"
_mutate "$a/retrieval/embeddings.py" '
text = text.replace("_model_offline_eligible", "_model_offline_check_removed")'
_expect "T7 missing-conditional-wiring mutation" 2 "FAIL  \[T7\]"

# 12. T8: reference-env VALUE drift (export survives, value lies).
a="$(_mktree)"
_mutate "$a/docs/security-philosophy/cyclaw_telemetry_kill.env" '
text = text.replace("export OTEL_SDK_DISABLED=true", "export OTEL_SDK_DISABLED=false", 1)'
_expect "T8 env value-drift mutation" 2 "FAIL  \[T8\]"

# 13. T8: dropped `export` keyword (a bare KEY=value never reaches a child).
a="$(_mktree)"
_mutate "$a/docs/security-philosophy/cyclaw_telemetry_kill.env" '
text = text.replace("export DO_NOT_TRACK=1", "DO_NOT_TRACK=1", 1)'
_expect "T8 missing-export mutation" 2 "FAIL  \[T8\]"

# 14. T8: duplicate line.
a="$(_mktree)"
_mutate "$a/docs/security-philosophy/cyclaw_telemetry_kill.env" '
text = text + "export DO_NOT_TRACK=1\n"'
_expect "T8 duplicate-line mutation" 2 "FAIL  \[T8\]"

# 15. T10: Dockerfile delivery drift (GH_TELEMETRY flipped to true).
a="$(_mktree)"
_mutate "$a/Dockerfile" '
text = text.replace("GH_TELEMETRY=false", "GH_TELEMETRY=true", 1)'
_expect "T10 Dockerfile value-flip mutation" 2 "FAIL  \[T10\]"

# 16. T11: launcher stops exporting the canonical block.
a="$(_mktree)"
_mutate "$a/macos/invoke-cyclaw.sh" '
text = text.replace("-m utils.telemetry_kill --export shell", "-m utils.telemetry_kill --export-DISABLED", 1)'
_expect "T11 launcher-export-removed mutation" 2 "FAIL  \[T11\]"

# 17. T12: a runtime file grows a programmatic re-enable call.
a="$(_mktree)"
_mutate "$a/retrieval/vector_store.py" '
text = text + "\n\ndef _oops():\n    import onnxruntime\n    onnxruntime.enable_telemetry_events()\n"'
_expect "T12 programmatic-bypass mutation" 2 "FAIL  \[T12\]"

# 18. T12: a child-env builder drops the canonical map.
a="$(_mktree)"
_mutate "$a/agentic/gh_client.py" '
text = text.replace("build_telemetry_safe_env", "plain_environ_passthrough")'
_expect "T12 dropped-builder mutation" 2 "FAIL  \[T12\]"

# 19. T13: unclassified new dependency — WARN default, FAIL under --strict.
a="$(_mktree)"
_mutate "$a/requirements.txt" '
text = text + "\nsome-new-vendor==1.0.0\n"'
out="$(python3 "$checker" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && echo "$out" | grep -q "WARN  \[T13\].*some-new-vendor"; then
  echo "T13 unclassified-dep (default): PASS (WARN, exit 0)"
else
  echo "T13 unclassified-dep (default): FAIL — expected WARN/exit 0, got rc=$rc" >&2
  echo "$out" >&2
  fails=$((fails + 1))
fi
out="$(python3 "$checker" --repo-root "$a" --as-of "$AS_OF" --strict 2>&1)"; rc=$?
if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\].*some-new-vendor"; then
  echo "T13 unclassified-dep (--strict): PASS (FAIL, exit 2)"
else
  echo "T13 unclassified-dep (--strict): FAIL — expected exit 2, got rc=$rc" >&2
  echo "$out" >&2
  fails=$((fails + 1))
fi
rm -rf "$a"

# 20. T13: a category-3 row inventing a control must fail schema validation.
a="$(_mktree)"
cp "$checker" "$a/check_otel_mutated.py"
_mutate "$a/check_otel_mutated.py" '
old = "\"name\": \"telegram channel\", \"category\": 3, \"controls\": {},"
assert old in text
text = text.replace(old, "\"name\": \"telegram channel\", \"category\": 3, \"controls\": {\"OTEL_SDK_DISABLED\": \"true\"},", 1)'
out="$(python3 "$a/check_otel_mutated.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\].*must not invent controls"; then
  echo "T13 invented-control mutation: PASS"
else
  echo "T13 invented-control mutation: FAIL — expected exit 2, got rc=$rc" >&2
  echo "$out" >&2
  fails=$((fails + 1))
fi
rm -rf "$a"

# 21. T14: an ONNX load seam drops the API call. The replacement must NOT
#     contain the original as a substring, or the checker's needle still
#     matches and the mutation proves nothing (found the hard way).
a="$(_mktree)"
_mutate "$a/guardrails/integration.py" '
text = text.replace("suppress_onnx_telemetry", "zz_onnx_call_removed_zz")'
_expect "T14 dropped-seam mutation" 2 "FAIL  \[T14\]"

# 22. T13: the ONNX floor pin is lowered below the release where
#     ORT_DISABLE_TELEMETRY starts governing the non-Windows 1DS path. Both
#     required surfaces must go red, not just report an info line.
#     The mutation rewrites WHATEVER version is pinned rather than a literal
#     current one: hardcoding "1.29.0" here made this scenario silently no-op
#     the moment the pin moved off the floor (caught on the 1.29.0 -> 1.30.0
#     bump, 2026-09-11 -- the sed matched nothing, so nothing was mutated and
#     the clean tree's exit 0 read as a pass). The floor in the EXPECTED
#     message stays literal: that number is the ORT release the control landed
#     in, not a pin, and it does not move.
a="$(_mktree)"
_mutate "$a/constraints.txt" '
import re
text = re.sub(r"(?m)^onnxruntime==[^\n]*$", "onnxruntime==1.28.0", text)'
_mutate "$a/pyproject.toml" '
import re
text = re.sub(r"\"onnxruntime==[^\"]*\"", "\"onnxruntime==1.28.0\"", text)'
_expect "T13 ONNX floor lowered mutation" 2 "FAIL  \[T13\].*below the 1.29.0 floor"

# 23. T13: the pins are deleted outright, as a future dependency edit might do.
#     A missing floor on a REQUIRED surface must fail -- reporting it with
#     info() left the checker silent while both shipped surfaces could resolve
#     below the floor.
a="$(_mktree)"
_mutate "$a/constraints.txt" '
import re
text = re.sub(r"(?m)^onnxruntime==[^\n]*\n", "", text)'
_mutate "$a/pyproject.toml" '
import re
text = re.sub(r"(?m)^\s*\"onnxruntime==[^\n]*\n", "", text)'
_expect "T13 ONNX pins deleted mutation" 2 "FAIL  \[T13\].*no onnxruntime floor"

# 24. T13: the floor check itself is neutered. Without this scenario a
#     regression could delete the enforcement while this verifier stayed green
#     -- the mutations above only prove the check works when it is called.
#     The replacement must not contain the original body as a substring.
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace(
    "    for surface, pinned in _pins_by_surface(root, \"onnxruntime\").items():\n"
    "        _ort_floor_verdict(surface, pinned)",
    "    return  # zz_ort_floor_check_removed_zz")'; then
  # The mutation not applying means the body it targets is already gone or
  # renamed. Reporting PASS there would be passing for the wrong reason -- the
  # scenario would be silently guarding nothing.
  echo "T13 ONNX floor-check removed mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"
  if echo "$out" | grep -q "onnxruntime pinned"; then
    echo "T13 ONNX floor-check removed mutation: FAIL — neutered check still reported a verdict" >&2
    fails=$((fails + 1))
  else
    echo "T13 ONNX floor-check removed mutation: PASS"
  fi
fi
rm -rf "$a"

# 25. T13: removing the pip-subsection pin from environment.yml must restore
# the informational Conda gap without changing the independently pinned pip
# and wheel surfaces.
a="$(_mktree)"
_mutate "$a/environment.yml" '
text = text.replace("      - onnxruntime==1.30.0\n", "", 1)'
_expect "T13 conda pip-subsection pin deleted mutation" 0 "info  \[T13\] conda (environment.yml): no onnxruntime floor"

# 26. A marker-scoped pip entry does not bind every Conda install platform.
a="$(_mktree)"
_mutate "$a/environment.yml" '
text = text.replace("      - onnxruntime==1.30.0\n", "      - onnxruntime==1.30.0; sys_platform == '\''darwin'\''\n", 1)'
_expect "T13 conda marker-scoped pin mutation" 0 "info  \[T13\] conda (environment.yml): no onnxruntime floor"

# 27. T9: the parent-process path stops routing through the shared _enforce
#     core. The rewritten body still sets every telemetry pair (so T2's value
#     oracle stays green and nothing else can catch it), but it no longer
#     applies the update-check pairs or pops the scrubbed names -- exactly the
#     parent/child drift T9 exists to forbid. Until this scenario landed
#     (2026-09-28, Codex P2 on PR #1496) T9 was the one failing rule with no
#     mutation, so check_helper_wiring() could have been neutered unnoticed.
a="$(_mktree)"
_mutate "$a/utils/telemetry_kill.py" '
old = "    _enforce(os.environ)\n    return dict(TELEMETRY_KILL)\n"
assert old in text
text = text.replace(old, "    for key, value in TELEMETRY_KILL.items():\n        os.environ[key] = value\n    return dict(TELEMETRY_KILL)\n", 1)'
_expect "T9 parent-path drift mutation" 2 "FAIL  \[T9\].*apply_telemetry_kill"

# 28. T13: the build backend is swapped for an unclassified one. Until
#     2026-09-28 the sweep never read [build-system].requires, so this exact
#     edit left strict mode green (Codex P2 on PR #1502). WARN by default,
#     FAIL under --strict, same as any other unclassified dependency.
a="$(_mktree)"
_mutate "$a/pyproject.toml" '
import re
text, n = re.subn(r"\"hatchling==[0-9][^\"]*\"", "\"some-build-backend==1.0.0\"", text)
assert n == 1'
_expect "T13 unclassified build backend (default)" 0 "WARN  \[T13\].*some-build-backend"
a="$(_mktree)"
_mutate "$a/pyproject.toml" '
import re
text, n = re.subn(r"\"hatchling==[0-9][^\"]*\"", "\"some-build-backend==1.0.0\"", text)
assert n == 1'
_expect "T13 unclassified build backend (--strict)" 2 "FAIL  \[T13\].*some-build-backend" "--strict"

# 29. T13: a dynamic-launcher site stops spawning. The row for the pre-action
#     hook's command engine is only true while _run_command still hands the
#     operator's argv to subprocess; removing that call must be reported so
#     the row is retired rather than left describing a surface that is gone.
#     The replacement must not contain the original marker as a substring.
a="$(_mktree)"
_mutate "$a/utils/external_pre_hook.py" '
text = text.replace("subprocess.run(", "zz_spawn_removed_zz(")
assert "subprocess.run(" not in text'
_expect "T13 dynamic-launcher site gone mutation" 0 "WARN  \[T13\] dynamic launcher .pre-action-hook-command.*no longer carries"

# 30. T13: a FIXED launcher site stops spawning its binary. The security(1)
#     row is only true while sync/scheduled.py still execs /usr/bin/security;
#     removing that argv must be reported so the row (and, when it is the last
#     site, the alias and KNOWN_EXTERNAL_COMPONENTS entry) is retired rather
#     than left classifying a binary nobody runs (Codex P2 on PR #1637).
a="$(_mktree)"
_mutate "$a/sync/scheduled.py" '
text = text.replace("[\"/usr/bin/security\", \"find-generic-password\"", "[\"zz_removed_zz\", \"find-generic-password\"")
assert "/usr/bin/security" not in text'
_expect "T13 fixed-launcher site gone mutation" 0 "WARN  \[T13\] fixed launcher .security.*no longer carries"

# 31. T13: a known external binary loses its spawn-site rows entirely. Until
#     PR #1637 a name in KNOWN_EXTERNAL_COMPONENTS was never checked against
#     the tree, which is how the uv row went stale; now a name with no
#     FIXED/DYNAMIC/FRONTED row is a hard failure.
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
lines = text.splitlines(keepends=True)
kept = [l for l in lines if not l.lstrip().startswith("(\"uv\", ")]
assert len(kept) == len(lines) - 3, "expected exactly three uv site rows"
text = "".join(kept)'; then
  echo "T13 known binary without a spawn-site row mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\] known external component.*no spawn-site row.*uv"; then
    echo "T13 known binary without a spawn-site row mutation: PASS"
  else
    echo "T13 known binary without a spawn-site row mutation: FAIL — expected rc=2 + the no-spawn-site-row FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

# 32. T13: a DYNAMIC launcher row added without a KNOWN_EXTERNAL_COMPONENTS
#     entry. Its marker verifies fine, but the surface never enters the
#     classification sweep, so the reverse-consistency check must fail it
#     (Codex P2 on PR #1637, second round).
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace(
    "\"& $exe @exeArgs\")),\n)",
    "\"& $exe @exeArgs\")),\n"
    "    (\"zz-new-surface\", \"utils/external_pre_hook.py\", (\"def _run_command\",)),\n)")'; then
  echo "T13 unlisted dynamic surface mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\] spawn-site row.*does not name.*zz-new-surface"; then
    echo "T13 unlisted dynamic surface mutation: PASS"
  else
    echo "T13 unlisted dynamic surface mutation: FAIL — expected rc=2 + the does-not-name FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

# 33. T13: a fixed launcher keeps its override plumbing but stops invoking
#     the binary. The uv rows pin the `"$uv_bin" pip compile` call, not only
#     the `uv_bin=` assignment, so deleting the call alone must be reported.
a="$(_mktree)"
_mutate "$a/scripts/refresh-ci-locks.sh" '
text = text.replace("\"$uv_bin\" pip compile", "\"$uv_bin\" zz_no_longer_compiles_zz")
assert "\"$uv_bin\" pip compile" not in text and "uv_bin=\"${UV_BIN:-uv}\"" in text'
_expect "T13 fixed-launcher invocation gone mutation" 0 "WARN  \[T13\] fixed launcher .uv.: scripts/refresh-ci-locks.sh no longer carries"

# 34. T13: the setup script's canonical-export eval is removed while its gh
#     calls stay. The gh row's claim that the shell site carries the block is
#     only true while that eval exists, so it is pinned as a marker.
a="$(_mktree)"
_mutate "$a/macos/setup-from-clone.sh" '
text = text.replace("-m utils.telemetry_kill --export shell", "-m zz_no_export_zz")
assert "gh auth login --with-token" in text'
_expect "T13 setup-script export eval gone mutation" 0 "WARN  \[T13\] fixed launcher .gh.: macos/setup-from-clone.sh no longer carries"

# 35. T13: an inventory row's repo-relative url points at a file that does
#     not exist (the docs/setup-guide.md slip Codex caught in round four).
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace("\"url\": \"setup-guide.md\",", "\"url\": \"docs/zz-missing-guide.md\",", 1)'; then
  echo "T13 missing evidence path mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\].*docs/zz-missing-guide.md.*does not exist"; then
    echo "T13 missing evidence path mutation: PASS"
  else
    echo "T13 missing evidence path mutation: FAIL — expected rc=2 + the does-not-exist FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

# 36. T13: the Keychain helper keeps its resolver but stops invoking
#     security(1). The row pins the find-generic-password call, not only the
#     SECURITY_BIN assignment.
a="$(_mktree)"
_mutate "$a/macos/cyclaw-keychain-env.sh" '
text = text.replace("\"$SECURITY_BIN\" find-generic-password", "\"$SECURITY_BIN\" zz_no_lookup_zz")
assert "SECURITY_BIN=\"/usr/bin/security\"" in text and "\"$SECURITY_BIN\" find-generic-password" not in text'
_expect "T13 keychain invocation gone mutation" 0 "WARN  \[T13\] fixed launcher .security.: macos/cyclaw-keychain-env.sh no longer carries"

# 37. T13: a site row for agent tooling under .claude/ outside the swept
#     sandbox surfaces. Agent tooling is out of the inventory by owner
#     decision (PR #1637); the row itself must fail so the boundary is only
#     ever widened by editing SWEPT_AGENT_SURFACES on purpose.
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace(
    "    (\"curl\", \".claude/skills/CyClaw-Sandbox/smoke.sh\", (\x27curl -sf \"$BASE/health\"\x27,)),\n",
    "    (\"curl\", \".claude/skills/CyClaw-Sandbox/smoke.sh\", (\x27curl -sf \"$BASE/health\"\x27,)),\n"
    "    (\"git\", \".claude/hooks/session-start-sync-check.sh\", (\"git \",)),\n", 1)'; then
  echo "T13 agent-tooling boundary mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\] site row.*outside the agent-tooling boundary.*session-start-sync-check"; then
    echo "T13 agent-tooling boundary mutation: PASS"
  else
    echo "T13 agent-tooling boundary mutation: FAIL — expected rc=2 + the boundary FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

# 38. T13: an alias whose target names no inventory row. Before PR #1637's
#     seventh round the mere presence of the alias key counted as
#     "classified", so a typo silently dropped a component's classification.
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace("    \"curl\": \"curl (setup + sandbox probes)\",", "    \"curl\": \"zz nonexistent inventory row\",", 1)'; then
  echo "T13 dangling alias target mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\] alias target.*zz nonexistent inventory row"; then
    echo "T13 dangling alias target mutation: PASS"
  else
    echo "T13 dangling alias target mutation: FAIL — expected rc=2 + the alias FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

# 39. T13: the agent-tooling boundary covers DYNAMIC rows too, and the
#     single-file exception is matched exactly ("driver.sh.backup" is not
#     "driver.sh"). One mutation adds both offending rows; both must be
#     named in the FAIL.
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace(
    "\"& $exe @exeArgs\")),\n)",
    "\"& $exe @exeArgs\")),\n"
    "    (\"executor-check\", \".claude/hooks/session-start-sync-check.sh\", (\"git \",)),\n)", 1)
text = text.replace(
    "    (\"curl\", \".claude/skills/CyClaw-Sandbox/smoke.sh\", (\x27curl -sf \"$BASE/health\"\x27,)),\n",
    "    (\"curl\", \".claude/skills/CyClaw-Sandbox/smoke.sh\", (\x27curl -sf \"$BASE/health\"\x27,)),\n"
    "    (\"curl\", \".claude/skills/cyclaw-gotchas/driver.sh.backup\", (\"curl \",)),\n", 1)'; then
  echo "T13 boundary dynamic+exact mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep "FAIL  \[T13\] site row.*outside the agent-tooling boundary" | grep -q "session-start-sync-check" && echo "$out" | grep "outside the agent-tooling boundary" | grep -q "driver.sh.backup"; then
    echo "T13 boundary dynamic+exact mutation: PASS"
  else
    echo "T13 boundary dynamic+exact mutation: FAIL — expected rc=2 + both paths in the boundary FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

# 40. T13: a newly sited invocation (the scheduled-sync rclone listremotes
#     check) is removed while the resolver stays. Proves the eighth-round
#     rows are live markers, not decoration.
a="$(_mktree)"
_mutate "$a/sync/scheduled.py" '
text = text.replace("[binary, \"listremotes\"]", "[binary, \"zz_no_remotes_zz\"]")
assert "shutil.which(\"rclone\")" in text and "[binary, \"listremotes\"]" not in text'
_expect "T13 scheduled rclone invocation gone mutation" 0 "WARN  \[T13\] fixed launcher .rclone.: sync/scheduled.py no longer carries"

# 41. T13: the Homebrew analytics export is removed while the brew commands
#     stay. The export is the pre-execution protection the Homebrew row
#     claims (it covers a later `brew install` even if `brew analytics off`
#     failed), so it is a marker in its own right.
a="$(_mktree)"
_mutate "$a/macos/setup-from-clone.sh" '
text = text.replace("export HOMEBREW_NO_ANALYTICS=1", "export ZZ_HOMEBREW_UNSET=1")
assert "brew analytics off >/dev/null" in text and "HOMEBREW_NO_ANALYTICS=1" not in text'
_expect "T13 homebrew export gone mutation" 0 "WARN  \[T13\] fixed launcher .brew.: macos/setup-from-clone.sh no longer carries"

# 42. T13: an inventory row's url is an absolute path. `root / "/etc/passwd"`
#     discards root, so the existence check alone would pass; the schema must
#     refuse anything that is not repository-relative (Codex P2 on PR #1637,
#     tenth round). 43 is the '..' traversal form of the same rule.
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace("\"url\": \"setup-guide.md\",", "\"url\": \"/etc/passwd\",", 1)'; then
  echo "T13 absolute evidence path mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\].*/etc/passwd.*must be a repository-relative path"; then
    echo "T13 absolute evidence path mutation: PASS"
  else
    echo "T13 absolute evidence path mutation: FAIL — expected rc=2 + the repository-relative FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace("\"url\": \"setup-guide.md\",", "\"url\": \"docs/../../etc/passwd\",", 1)'; then
  echo "T13 traversal evidence path mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep -q "FAIL  \[T13\].*etc/passwd.*must be a repository-relative path"; then
    echo "T13 traversal evidence path mutation: PASS"
  else
    echo "T13 traversal evidence path mutation: FAIL — expected rc=2 + the repository-relative FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

# 44. T13: a secret-injecting exec wrapper stops exec'ing the caller's
#     command. The wrapper is a DYNAMIC surface (the binary is whatever
#     follows `--`), so losing its `exec "$@"` must trip the dynamic-site
#     WARN like any other launcher (Codex P2 on PR #1637, eleventh round).
a="$(_mktree)"
_mutate "$a/macos/cyclaw-keychain-env.sh" '
text = text.replace("exec \"$@\"\n", "\"$@\"\n", 1)'
_expect "T13 secret-env wrapper exec gone mutation" 0 "WARN  \[T13\] dynamic launcher .secret-env-wrapper.: macos/cyclaw-keychain-env.sh no longer carries"
rm -rf "$a"

# 45. T13: a site row whose path hops out of the swept sandbox surface with
#     '..' (it starts with the allowed prefix, so a raw startswith test would
#     pass it) and one with an absolute path. Both must be refused before the
#     boundary or marker checks read them (Codex P2 on PR #1637, eleventh round).
a="$(_mktree)"
mkdir -p "$a/.claude/skills/otel-hardening"
cp "$checker" "$a/.claude/skills/otel-hardening/check_otel.py"
if ! _mutate "$a/.claude/skills/otel-hardening/check_otel.py" '
text = text.replace(
    "    (\"curl\", \".claude/skills/CyClaw-Sandbox/smoke.sh\", (\x27curl -sf \"$BASE/health\"\x27,)),\n",
    "    (\"curl\", \".claude/skills/CyClaw-Sandbox/smoke.sh\", (\x27curl -sf \"$BASE/health\"\x27,)),\n"
    "    (\"git\", \".claude/skills/CyClaw-Sandbox/../../hooks/session-start-sync-check.sh\", (\"git \",)),\n"
    "    (\"git\", \"/etc/passwd\", (\"root\",)),\n", 1)'; then
  echo "T13 site path traversal mutation: FAIL — mutation did not apply; update this scenario" >&2
  fails=$((fails + 1))
else
  out="$(python3 "$a/.claude/skills/otel-hardening/check_otel.py" --repo-root "$a" --as-of "$AS_OF" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ] && echo "$out" | grep "FAIL  \[T13\] site row path.*not clean repository-relative" | grep -q "session-start-sync-check" && echo "$out" | grep "not clean repository-relative" | grep -q "/etc/passwd"; then
    echo "T13 site path traversal mutation: PASS"
  else
    echo "T13 site path traversal mutation: FAIL — expected rc=2 + both paths in the site-path FAIL, got rc=$rc" >&2
    echo "$out" >&2
    fails=$((fails + 1))
  fi
fi
rm -rf "$a"

# 46. T13: the sandbox audit's hashed pip install disappears from
#     CyClaw-Sandbox/verify.sh (a swept surface), and 47 its git clone from
#     run_full_verification.py. Both were unsited until the eleventh round;
#     each must now trip the fixed-launcher WARN on its own.
a="$(_mktree)"
_mutate "$a/.claude/skills/CyClaw-Sandbox/verify.sh" '
text = text.replace("\"$VPY\" -m pip install --quiet --require-hashes -r locks/requirements-lock-linux.txt", "true", 1)'
_expect "T13 sandbox pip install gone mutation" 0 "WARN  \[T13\] fixed launcher .pip-install.: .claude/skills/CyClaw-Sandbox/verify.sh no longer carries"
rm -rf "$a"

a="$(_mktree)"
_mutate "$a/.claude/skills/CyClaw-Sandbox/run_full_verification.py" '
text = text.replace("[git, \"clone\", \"--depth\", \"1\", \"--branch\", BRANCH, REPO_URL, \".\"]", "[git, \"status\"]", 1)'
_expect "T13 sandbox git clone gone mutation" 0 "WARN  \[T13\] fixed launcher .git-remote.: .claude/skills/CyClaw-Sandbox/run_full_verification.py no longer carries"
rm -rf "$a"

# 48. T13: the setup script's `gh auth login` disappears. It is a gh-api
#     (category-3) site as well as a gh telemetry site, so the functional
#     row must notice on its own (Codex P2 on PR #1637, eleventh round).
a="$(_mktree)"
_mutate "$a/macos/setup-from-clone.sh" '
text = text.replace("gh auth login --with-token", "gh auth setup-git")  # both token branches'
_expect "T13 gh auth invocation gone mutation" 0 "WARN  \[T13\] fixed launcher .gh-api.: macos/setup-from-clone.sh no longer carries"
rm -rf "$a"

# 49. T13: the generated Task Scheduler job's command construction changes
#     (COMSPEC lookup replaced). The cmd.exe row used to pin only the .cmd
#     filename, which survives this (Codex P2 on PR #1637, eleventh round).
a="$(_mktree)"
_mutate "$a/utils/win_schtasks.py" '
text = text.replace("command=os.environ.get(\"COMSPEC\", \"cmd.exe\")", "command=\"wscript.exe\"", 1)'
_expect "T13 schtasks command construction gone mutation" 0 "WARN  \[T13\] fixed launcher .cmd.exe.: utils/win_schtasks.py no longer carries"
rm -rf "$a"

# 50. T13: the Keychain store helper stops driving security(1) through expect.
a="$(_mktree)"
_mutate "$a/macos/setup-cyclaw-keys.sh" '
text = text.replace("/usr/bin/expect <<EXPECT_EOF", "/usr/bin/true <<EXPECT_EOF", 1)'
_expect "T13 expect invocation gone mutation" 0 "WARN  \[T13\] fixed launcher .expect.: macos/setup-cyclaw-keys.sh no longer carries"
rm -rf "$a"

# 51. T13: the Linux keyring lookup disappears from cyclaw-linux-key.sh.
a="$(_mktree)"
_mutate "$a/macos/cyclaw-linux-key.sh" '
text = text.replace("\"$1\" lookup service \"$_CYCLAW_LINUX_KEY_SERVICE\"", "cat /dev/null", 1)'
_expect "T13 secret-tool lookup gone mutation" 0 "WARN  \[T13\] fixed launcher .secret-tool.: macos/cyclaw-linux-key.sh no longer carries"
rm -rf "$a"

echo
if [ "$fails" -eq 0 ]; then
  echo "otel-hardening verify: ALL PASS"
  exit 0
else
  echo "otel-hardening verify: $fails mutation test(s) FAILED" >&2
  exit 1
fi
