#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
uv_bin="${UV_BIN:-uv}"
python_bin="${PYTHON_BIN:-python3.12}"
cache_dir="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/cyclaw-uv-cache}"

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
    --output-file "$repo_root/$output" \
    "$@"
}

compile_lock x86_64-unknown-linux-gnu requirements-lock-linux.txt "$repo_root/constraints.txt" --torch-backend cpu
compile_lock x86_64-pc-windows-msvc requirements-lock-windows.txt "$repo_root/constraints.txt" --torch-backend cpu
if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "macOS lock generation requires the supported arm64 macOS host" >&2
  exit 1
fi
macos_constraints="$(mktemp "${TMPDIR:-/tmp}/cyclaw-constraints.XXXXXX")"
trap 'rm -f "$macos_constraints"' EXIT
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
    --output-file "$repo_root/$output" \
    "$@"
}

compile_torch_lock x86_64-unknown-linux-gnu requirements-torch-lock-linux.txt --torch-backend cpu
compile_torch_lock x86_64-pc-windows-msvc requirements-torch-lock-windows.txt --torch-backend cpu
compile_torch_lock native requirements-torch-lock-macos.txt

for lock in "$repo_root"/requirements-lock-*.txt; do
  if grep -Eq '^(--extra-index-url|--index-url|torch==)' "$lock"; then
    echo "generated lock unexpectedly contains an index directive or Torch: $lock" >&2
    exit 1
  fi
done

for lock in "$repo_root"/requirements-torch-lock-*.txt; do
  if grep -Eq '^(--extra-index-url|--index-url)' "$lock" || ! grep -Eq '^torch==' "$lock"; then
    echo "generated Torch lock has an invalid shape: $lock" >&2
    exit 1
  fi
done
