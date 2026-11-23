"""Shared stand-in for macOS's ``security`` CLI, for the keychain-script tests.

Three test files used to embed their own diverged copy of this bash stub
(#1828, #1853): a fix to its argument parsing had to land three times, and a
missed copy gave a wrong verdict. Each test now installs this one script and
names the subcommands its scripts may call. Any other subcommand still exits 1
("unsupported command"), so a script that unexpectedly writes or deletes a
keychain item fails its test exactly as before.

Environment knobs (all optional; unset means the behaviour is off):

* ``FAKE_SECURITY_ITEMS`` -- ``"service=secret|service2=secret2"`` present items.
* ``FAKE_SECURITY_STORE`` -- file of ``service<TAB>secret`` lines; ``add`` appends
  to it and ``find`` reads it before ``FAKE_SECURITY_ITEMS``.
* ``FAKE_SECURITY_LOG`` -- ``add``/``delete`` argv (never the ``-w`` value) appended.
* ``FAKE_SECURITY_STDIN_LOG`` -- ``service<TAB>secret`` line appended for each
  bare ``-w`` on ``add``, read from the stub's own stdin the way the real CLI's
  readpassphrase(3) prompt reads it, never from argv.
* ``FAKE_SECURITY_FIND_LOG`` -- ``probe``/``read<TAB>service`` per ``find``.
* ``FAKE_SECURITY_PROBE_RC`` / ``_READ_RC`` / ``_WRITE_RC`` / ``_DELETE_RC`` --
  forced exit codes.
* ``FAKE_SECURITY_MISSING`` -- ``"svc|svc2"`` services ``delete`` reports as absent (44).
"""

from __future__ import annotations

import stat
from collections.abc import Iterable
from pathlib import Path

_HEAD = """#!/usr/bin/env bash
set -euo pipefail
cmd="$1"; shift
case "$cmd" in
"""

_ARMS = {
    "find-generic-password": """  find-generic-password)
    service=""
    read_value=0
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -s) service="$2"; shift 2 ;;
        -w) read_value=1; shift 1 ;;
        *) shift 1 ;;
      esac
    done
    if [ -n "${FAKE_SECURITY_FIND_LOG:-}" ]; then
      if [ "$read_value" -eq 1 ]; then
        printf 'read\t%s\n' "$service" >> "${FAKE_SECURITY_FIND_LOG}"
      else
        printf 'probe\t%s\n' "$service" >> "${FAKE_SECURITY_FIND_LOG}"
      fi
    fi
    if [ "$read_value" -eq 0 ] && [ -n "${FAKE_SECURITY_PROBE_RC:-}" ]; then
      exit "${FAKE_SECURITY_PROBE_RC}"
    fi
    if [ -n "${FAKE_SECURITY_STORE:-}" ] && [ -f "${FAKE_SECURITY_STORE}" ]; then
      stored=""
      while IFS=$'\\t' read -r key val; do
        if [ "$key" = "$service" ]; then stored="$val"; fi
      done < "${FAKE_SECURITY_STORE}"
      if [ -n "$stored" ]; then
        if [ "$read_value" -eq 1 ] && [ -n "${FAKE_SECURITY_READ_RC:-}" ]; then
          exit "${FAKE_SECURITY_READ_RC}"
        fi
        if [ "$read_value" -eq 1 ]; then
          printf '%s' "$stored"
        fi
        exit 0
      fi
    fi
    items_raw="${FAKE_SECURITY_ITEMS:-}"
    [ -n "$items_raw" ] || exit 44
    IFS='|' read -ra items <<< "$items_raw"
    for item in "${items[@]}"; do
      key="${item%%=*}"
      val="${item#*=}"
      if [ "$key" = "$service" ]; then
        if [ "$read_value" -eq 1 ] && [ -n "${FAKE_SECURITY_READ_RC:-}" ]; then
          exit "${FAKE_SECURITY_READ_RC}"
        fi
        if [ "$read_value" -eq 1 ]; then
          printf '%s' "$val"
        fi
        exit 0
      fi
    done
    exit 44
    ;;
""",
    "add-generic-password": """  add-generic-password)
    args_log=""
    service=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -s)
          service="$2"
          args_log="$args_log $1 $2"
          shift 2
          ;;
        -w)
          IFS= read -r secret_from_stdin || true
          saw_secret=1
          if [ -n "${FAKE_SECURITY_STDIN_LOG:-}" ]; then
            # One line per write, keyed by service, so --grok-dummy cannot
            # clobber the generated API key assertion.
            printf '%s\\t%s\\n' "$service" "$secret_from_stdin" >> "${FAKE_SECURITY_STDIN_LOG}"
          fi
          shift 1
          ;;
        *)
          args_log="$args_log $1"
          shift 1
          ;;
      esac
    done
    if [ -n "${FAKE_SECURITY_LOG:-}" ]; then
      echo "add-generic-password$args_log" >> "$FAKE_SECURITY_LOG"
    fi
    if [ -n "${FAKE_SECURITY_WRITE_RC:-}" ]; then
      exit "${FAKE_SECURITY_WRITE_RC}"
    fi
    if [ "${saw_secret:-0}" -eq 1 ] && [ -n "${FAKE_SECURITY_STORE:-}" ]; then
      printf '%s\\t%s\\n' "$service" "$secret_from_stdin" >> "${FAKE_SECURITY_STORE}"
    fi
    exit 0
    ;;
""",
    "delete-generic-password": """  delete-generic-password)
    account=""
    service=""
    args_log=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -a)
          account="$2"
          args_log="$args_log $1 $2"
          shift 2
          ;;
        -s)
          service="$2"
          args_log="$args_log $1 $2"
          shift 2
          ;;
        -w)
          echo "fake security: refuse -w on delete (secret must not be argv)" >&2
          exit 2
          ;;
        *)
          args_log="$args_log $1"
          shift 1
          ;;
      esac
    done
    if [ -n "${FAKE_SECURITY_LOG:-}" ]; then
      echo "delete-generic-password$args_log" >> "$FAKE_SECURITY_LOG"
    fi
    missing="${FAKE_SECURITY_MISSING:-}"
    case "|$missing|" in
      *"|$service|"*) exit 44 ;;
    esac
    if [ -n "${FAKE_SECURITY_DELETE_RC:-}" ]; then
      exit "${FAKE_SECURITY_DELETE_RC}"
    fi
    exit 0
    ;;
""",
}

_FOOT = """  *)
    echo "fake security: unsupported command $cmd" >&2
    exit 1
    ;;
esac
"""


def fake_security_script(commands: Iterable[str]) -> str:
    """Return the stub's bash source with only the named subcommand arms."""
    wanted = list(commands)
    unknown = sorted(set(wanted) - set(_ARMS))
    if unknown:
        raise ValueError(f"no fake arm for: {unknown}")
    return _HEAD + "".join(_ARMS[name] for name in wanted) + _FOOT


def install_fake_security(tmp_path: Path, commands: Iterable[str]) -> Path:
    """Write an executable ``security`` stub into ``tmp_path/bin`` and return that dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "security"
    stub.write_text(fake_security_script(commands), encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir
