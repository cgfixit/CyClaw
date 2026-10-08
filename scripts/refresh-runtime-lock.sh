#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
uv_bin="${UV_BIN:-uv}"
python_bin="${PYTHON_BIN:-python3.12}"
cache_dir="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/cyclaw-uv-cache}"
lock_dir="$repo_root/locks"
mkdir -p "$lock_dir"

# uv records the --constraints path in comments. The macOS compile uses a
# temp copy so the +cpu pin is absent. Rewrite those comments to the stable
# name constraints.txt, and fail if a temp path remains.
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
        line = file_pat.sub("constraints.txt", line)
        line = dir_pat.sub("constraints.txt", line)
    out.append(line)
path.write_text("".join(out), encoding="utf-8")
PY
  if grep -Eq '/var/folders/|cyclaw-constraints\.' "$lock"; then
    echo "generated lock still records a temp constraints path: $lock" >&2
    exit 1
  fi
}

compile_lock() {
  local platform="$1"
  local output="$2"
  local constraints_source="$3"
  shift 3
  local platform_args=()
  if [ "$platform" != "native" ]; then
    platform_args=(--python-platform "$platform")
  fi
  "$uv_bin" pip compile \
    --quiet \
    "$repo_root/requirements.txt" \
    --constraints "$constraints_source" \
    --python "$python_bin" \
    --python-version 3.12 \
    ${platform_args[@]+"${platform_args[@]}"} \
    --no-emit-package torch \
    --generate-hashes \
    --no-sources \
    --cache-dir "$cache_dir" \
    --custom-compile-command "scripts/refresh-runtime-lock.sh" \
    --output-file "$lock_dir/$output" \
    "$@"
  normalize_lock_comments "$lock_dir/$output"
}

compile_lock x86_64-unknown-linux-gnu requirements-lock-linux.txt "$repo_root/constraints.txt" --torch-backend cpu
compile_lock x86_64-pc-windows-msvc requirements-lock-windows.txt "$repo_root/constraints.txt" --torch-backend cpu
if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "macOS lock generation requires the supported arm64 macOS host" >&2
  exit 1
fi
macos_constraints_dir="$(mktemp -d "${TMPDIR:-/tmp}/cyclaw-constraints.XXXXXX")"
trap 'rm -rf "$macos_constraints_dir"' EXIT
macos_constraints="$macos_constraints_dir/constraints.txt"
sed 's/^\(torch==[0-9][0-9.]*\)+cpu$/\1/' "$repo_root/constraints.txt" > "$macos_constraints"
compile_lock native requirements-lock-macos.txt "$macos_constraints"

compile_torch_lock() {
  local platform="$1"
  local output="$2"
  shift 2
  local platform_args=()
  if [ "$platform" != "native" ]; then
    platform_args=(--python-platform "$platform")
  fi
  "$uv_bin" pip compile \
    --quiet \
    "$repo_root/requirements-torch.txt" \
    --python "$python_bin" \
    --python-version 3.12 \
    ${platform_args[@]+"${platform_args[@]}"} \
    --no-deps \
    --generate-hashes \
    --no-sources \
    --cache-dir "$cache_dir" \
    --custom-compile-command "scripts/refresh-runtime-lock.sh" \
    --output-file "$lock_dir/$output" \
    "$@"
  normalize_lock_comments "$lock_dir/$output"
}

compile_torch_lock x86_64-unknown-linux-gnu requirements-torch-lock-linux.txt --torch-backend cpu
compile_torch_lock x86_64-pc-windows-msvc requirements-torch-lock-windows.txt --torch-backend cpu
compile_torch_lock native requirements-torch-lock-macos.txt

for lock in "$lock_dir"/requirements-lock-*.txt; do
  if grep -Eq '^(--extra-index-url|--index-url|torch==)' "$lock"; then # DevSkim: ignore DS205001 - rejects index directives; does not install from an extra index
    echo "generated lock unexpectedly contains an index directive or Torch: $lock" >&2
    exit 1
  fi
  if grep -Eq '/var/folders/|cyclaw-constraints\.' "$lock"; then
    echo "generated lock still records a temp constraints path: $lock" >&2
    exit 1
  fi
done

for lock in "$lock_dir"/requirements-torch-lock-*.txt; do
  if grep -Eq '^(--extra-index-url|--index-url)' "$lock" || ! grep -Eq '^torch==' "$lock"; then # DevSkim: ignore DS205001 - rejects index directives in the dedicated Torch lock
    echo "generated Torch lock has an invalid shape: $lock" >&2
    exit 1
  fi
  if grep -Eq '/var/folders/|cyclaw-constraints\.' "$lock"; then
    echo "generated lock still records a temp constraints path: $lock" >&2
    exit 1
  fi
done
