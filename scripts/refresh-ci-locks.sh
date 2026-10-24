#!/usr/bin/env bash
# Closed hashed locks for installs that used `pip install -c constraints.txt`.
# Does not rewrite locks/requirements-lock-*.txt or locks/requirements-torch-lock-*.txt.
# Those stay on scripts/refresh-runtime-lock.sh. A constraints file caps
# versions and still accepts a replaced wheel. --require-hashes needs a
# requirements file, so each install set is compiled here.
set -euo pipefail

upgrade_args=()
while [ "$#" -gt 0 ]; do
  if [ "$1" != "--upgrade-package" ] || [ "$#" -lt 2 ] ||
      ! [[ "$2" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "usage: $0 [--upgrade-package NAME]... (versions belong in constraints.txt)" >&2
    exit 2
  fi
  upgrade_args+=(--upgrade-package "$2")
  shift 2
done

repo_root="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
uv_bin="${UV_BIN:-uv}"
python_bin="${PYTHON_BIN:-python3.12}"
cache_dir="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/cyclaw-uv-cache}"
inputs="$repo_root/scripts/ci-lock-inputs"
if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "lock generation requires the supported arm64 macOS host" >&2
  exit 1
fi
stage_dir="$(mktemp -d "$repo_root/.lock-refresh.XXXXXX")"
lock_dir="$stage_dir/locks"
mkdir -p "$lock_dir"
# Seed the stage with the tracked locks: uv pip compile keeps an existing
# --output-file's pins as preferences, so an empty stage would silently
# upgrade every transitive pin on each refresh (#1631 review).
cp "$repo_root"/locks/requirements-*.txt "$lock_dir"/
macos_constraints_dir=""
trap 'rm -rf "$stage_dir"; if [ -n "$macos_constraints_dir" ]; then rm -rf "$macos_constraints_dir"; fi' EXIT

# uv records the --constraints path in comments. Rewrite temp paths back to
# the stable name constraints.txt, and fail if one remains.
normalize_lock_comments() {
  local lock="$1"
  "$python_bin" - "$lock" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
file_pat = re.compile(r"/var/folders/\S*?cyclaw-constraints\.[A-Za-z0-9]+")
dir_pat = re.compile(r"/\S*?cyclaw-constraints\.[A-Za-z0-9]+/constraints\.txt")
out = []
for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
    if line.lstrip().startswith("#"):
        # The directory form is a superset of the file form: run it first or
        # file_pat leaves "constraints.txt/constraints.txt" behind.
        line = dir_pat.sub("constraints.txt", line)
        line = file_pat.sub("constraints.txt", line)
    out.append(line)
path.write_text("".join(out), encoding="utf-8")
PY
  if grep -Eq '/var/folders/|cyclaw-constraints\.' "$lock"; then
    echo "generated lock still records a temp constraints path: $lock" >&2
    exit 1
  fi
}


macos_constraints_dir="$(mktemp -d "${TMPDIR:-/tmp}/cyclaw-constraints.XXXXXX")"

macos_constraints="$macos_constraints_dir/constraints.txt"
sed 's/^\(torch==[0-9][0-9.]*\)+cpu$/\1/' "$repo_root/constraints.txt" > "$macos_constraints"

compile_lock() {
  local platform="$1"
  local output="$2"
  local input="$3"
  local constraints_source="$repo_root/constraints.txt"
  local platform_args=()
  if [ "$platform" = "native" ]; then
    constraints_source="$macos_constraints"
  else
    platform_args=(--python-platform "$platform")
  fi
  echo "compiling $output"
  "$uv_bin" pip compile \
    "$input" \
    --constraints "$constraints_source" \
    --python "$python_bin" \
    --python-version 3.12 \
    ${platform_args[@]+"${platform_args[@]}"} \
    --generate-hashes \
    --no-sources \
    --cache-dir "$cache_dir" \
    --custom-compile-command "scripts/refresh-ci-locks.sh" \
    --output-file "$lock_dir/$output" \
    ${upgrade_args[@]+"${upgrade_args[@]}"}
  normalize_lock_comments "$lock_dir/$output"
  if grep -Eq '^(--extra-index-url|--index-url|torch==)' "$lock_dir/$output"; then # DevSkim: ignore DS205001 - rejects index directives; does not install from an extra index
    echo "generated lock unexpectedly contains an index directive or Torch: $output" >&2
    exit 1
  fi
  "$python_bin" - "$lock_dir/$output" <<'PY'
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
missing = []
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("--"):
        i += 1
        continue
    if "==" not in stripped:
        i += 1
        continue
    window = [stripped]
    j = i + 1
    while j < len(lines) and (lines[j].startswith(" ") or lines[j].strip().startswith("#")):
        window.append(lines[j])
        j += 1
    if not any("--hash=sha256:" in part for part in window):
        missing.append(stripped.split("\\", 1)[0].strip())
    i = j
if missing:
    sys.exit("lock is missing hashes for: " + ", ".join(missing))
PY
}

linux=x86_64-unknown-linux-gnu
windows=x86_64-pc-windows-msvc

compile_lock "$linux" requirements-test-lock-linux.txt "$repo_root/requirements-test.txt"
compile_lock "$windows" requirements-test-lock-windows.txt "$repo_root/requirements-test.txt"
compile_lock native requirements-test-lock-macos.txt "$repo_root/requirements-test.txt"

compile_lock "$linux" requirements-ci-smoke-lock-linux.txt "$inputs/smoke.txt"
compile_lock "$linux" requirements-ci-yaml-lock-linux.txt "$inputs/yaml.txt"
compile_lock "$linux" requirements-ci-ruff-lock-linux.txt "$inputs/ruff.txt"
compile_lock "$linux" requirements-ci-cel-lock-linux.txt "$inputs/cel.txt"
compile_lock "$linux" requirements-ci-numbat-lock-linux.txt "$inputs/numbat.txt"
compile_lock "$linux" requirements-ci-numbat-contract-lock-linux.txt "$inputs/numbat-contract.txt"
compile_lock "$linux" requirements-ci-postgres-lock-linux.txt "$inputs/postgres-job.txt"
compile_lock "$linux" requirements-ci-bandit-lock-linux.txt "$inputs/bandit.txt"

compile_lock "$linux" requirements-extra-lock-postgres-linux.txt "$inputs/extra-postgres.txt"
compile_lock "$linux" requirements-extra-lock-pgvector-linux.txt "$inputs/extra-pgvector.txt"
compile_lock "$linux" requirements-extra-lock-dev-linux.txt "$inputs/extra-dev.txt"

"$python_bin" "$repo_root/scripts/check_lock_contract.py" --publish ci --staged "$lock_dir"
echo "ci locks written"
