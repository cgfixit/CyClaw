"""utils/ops_runner.py – subprocess shim for the out-of-band ``sync`` / ``agentic.fsconnect`` CLIs.

The FastAPI gateway exposes ``POST /ops/sync`` and ``POST /ops/fsconnect`` so the
browser Soul Console can drive the two out-of-band subsystems. A browser cannot
spawn a subprocess, so the gateway must — but the gateway must NOT *import* those
packages, because architectural isolation of ``sync/`` and ``agentic/`` from
``gate.py`` / ``graph.py`` / ``mcp_hybrid_server.py`` is a hard CyClaw invariant.

This module is that boundary, and nothing more:

* It NEVER imports ``sync`` or ``agentic``. It only builds an argv list and runs
  it with ``subprocess.run([...])`` (list form, no shell) as
  ``python -m sync.cli`` / ``python -m agentic.fsconnect.cli``.
* It accepts only a whitelisted set of actions per subsystem. An unknown action
  raises :class:`OpsError`, which the route maps to HTTP 400 — a caller can never
  smuggle an arbitrary subcommand or flag through.

Exit codes are translated to operator-meaningful labels (see the per-subsystem
maps below) so the UI can render failure states — a tripped ``--max-delete`` /
``--max-transfer`` safety fuse, an env/config error, or a refused write — without
re-deriving the meaning of each code.

Exit-code contract (mirrors the docstrings in ``sync/cli.py`` / ``agentic/fsconnect/cli.py``):

    sync:       0 ok · 10 ok+reindex-needed · 1 safety-abort · 2 failed · 3 env/config
    fsconnect:  0 ok · 2 failed · 3 env/config · 4 write-refused
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - list-form only, no shell, fixed interpreter + whitelisted argv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.child_environment import child_environment, configured_path_names
from utils.logger import _get_config, redact_sensitive
from utils.numbat_emitter import emit_numbat_command, redact_argv_for_numbat

# Repo root = parent of utils/. The CLIs run as ``python -m sync.cli`` /
# ``agentic.fsconnect.cli``; running with cwd=repo-root puts the ``sync`` / ``agentic``
# packages on the import path without mutating PYTHONPATH for the gateway process.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
# Default wall-clock for short ops (status/test/fsconnect).
# The full Dropbox sync path uses config sync.sync_timeout_sec instead — see
# sync_timeout_sec() — so POST /ops/sync does not kill rclone mid-transfer.
_TIMEOUT_SEC = 120

# action whitelists — the ONLY subcommands a caller may reach.
_SYNC_ACTIONS = frozenset({"status", "test", "sync", "schedule", "unschedule"})

# fsconnect read-only CLI subcommands exposed via /ops/fsconnect.
_FSCONNECT_ACTIONS = frozenset({"status", "test", "list", "read", "stat", "grep", "glob"})
_FSCONNECT_JSON_ACTIONS = frozenset({"list", "read", "stat", "grep", "glob"})

# exit code -> (ok, label)
_SYNC_LABELS: dict[int, tuple[bool, str]] = {
    0: (True, "ok"),
    10: (True, "ok_reindex_needed"),
    1: (False, "safety_abort"),
    2: (False, "failed"),
    3: (False, "env_config"),
}
_FSCONNECT_LABELS: dict[int, tuple[bool, str]] = {
    0: (True, "ok"),
    2: (False, "failed"),
    3: (False, "env_config"),
    4: (False, "write_refused"),
}


class OpsError(ValueError):
    """A disallowed action or malformed request. The route maps this to HTTP 400."""


@dataclass
class OpsResult:
    """Normalized result of one CLI invocation, JSON-serializable for the route."""

    subsystem: str
    action: str
    exit_code: int
    ok: bool
    label: str
    stdout: str
    stderr: str
    parsed: Any = None

    def to_dict(self) -> dict[str, Any]:
        cfg = _get_config(str(_CONFIG_PATH))
        return {
            "subsystem": self.subsystem,
            "action": self.action,
            "exit_code": self.exit_code,
            "ok": self.ok,
            "label": self.label,
            "stdout": _redact_ops_value(self.stdout, cfg),
            "stderr": _redact_ops_value(self.stderr, cfg),
            "parsed": _redact_ops_value(self.parsed, cfg),
        }


def _redact_ops_value(value: Any, cfg: dict) -> Any:
    """Redact subprocess output before it reaches the browser ops console."""
    if isinstance(value, str):
        return redact_sensitive(value, cfg)
    if isinstance(value, dict):
        return {k: _redact_ops_value(v, cfg) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_ops_value(v, cfg) for v in value]
    return value


def sync_timeout_sec() -> int:
    """Wall-clock budget for ``sync.cli sync`` launched via the ops shim.

    Aligns with ``sync.sync_timeout_sec`` (default 3600) so console-driven
    ``POST /ops/sync`` does not abort a legitimate long rclone transfer that
    the CLI path would complete. Adds a small overhead for Python startup and
    post-rclone bookkeeping. Config value ``0`` means unbounded in the CLI;
    the ops path still needs a finite ceiling (falls back to 3600).

    When ``post_sync_check`` is enabled the runner can legitimately consume
    one full ``sync_timeout_sec`` for the rclone sync AND a second full
    timeout for the ``rclone check`` — both under the single-instance lock
    (the same lifecycle ``sync.runner._lock_stale_after_sec`` scales to).
    Mirror that doubled budget here or the shim kills a healthy run mid-check.

    Never raises: callers include gate.py's /health, which must answer even
    when config.yaml is unreadable or malformed. The except is deliberately
    broad: a config file that parses to a non-mapping makes ``cfg.get`` itself
    fail (AttributeError), and ``yaml.YAMLError`` derives straight from
    ``Exception``, so an enumerated tuple already proved incomplete once.
    """
    try:
        cfg = _get_config(str(_CONFIG_PATH))
        block = cfg.get("sync") or {}
        sec = int(block.get("sync_timeout_sec", 3600))
        post_sync_check = bool(block.get("post_sync_check", False))
    except Exception:  # noqa: BLE001 - contractually fail-soft; see the docstring
        sec, post_sync_check = 3600, False
    if sec <= 0:
        sec = 3600
    multiplier = 2 if post_sync_check else 1
    return sec * multiplier + 60


def _ops_environment(argv: list[str]) -> dict[str, str]:
    module = argv[2] if len(argv) > 2 and argv[1] == "-m" else ""
    cfg = _get_config(str(_CONFIG_PATH))
    if module == "sync.cli":
        return child_environment("sync", secret_names=configured_path_names(cfg.get("sync")))
    if module == "agentic.fsconnect.cli":
        return child_environment("filesystem", secret_names=configured_path_names(cfg.get("fsconnect")))
    return child_environment()


def _run(argv: list[str], *, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run a fully-formed, whitelisted argv list. No shell, fixed interpreter."""
    return subprocess.run(  # noqa: S603  # nosec B603 - list-form, no shell, fixed interpreter + whitelisted argv
        argv,
        cwd=str(_REPO_ROOT),
        env=_ops_environment(argv),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SEC if timeout_sec is None else timeout_sec,
        check=False,
    )


def _maybe_json(text: str) -> Any:
    """Parse JSON if the text is JSON, else return None (status/text output)."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _emit_ops_numbat(argv: list[str], result: OpsResult) -> None:
    """Project one ops subprocess into the Numbat NDJSON stream. Never raises."""
    emit_numbat_command(
        redact_argv_for_numbat(argv),
        exit_code=result.exit_code,
        tool_name=result.subsystem,
        actor="system",
        tags=["ops", result.subsystem, result.action],
        artifact_type="ops_runner",
    )


def run_sync_op(action: str, *, dry_run: bool = False) -> OpsResult:
    """Invoke ``python -m sync.cli <action>`` and normalize the result.

    Only ``dry_run`` is honored, and only for the ``sync`` action (it maps to
    ``--dry-run``). Every other action takes no caller-controlled arguments, so
    there is no surface for argument injection.
    """
    if action not in _SYNC_ACTIONS:
        raise OpsError(f"Unknown sync action: {action!r}")

    argv = [sys.executable, "-m", "sync.cli", "--config", str(_CONFIG_PATH), action]
    if action == "sync" and dry_run:
        argv.append("--dry-run")

    # status/test/schedule stay on the short default; only the full transfer
    # needs the config-aligned ceiling (rclone can run for up to an hour).
    timeout = sync_timeout_sec() if action == "sync" else _TIMEOUT_SEC
    proc = _run(argv, timeout_sec=timeout)
    ok, label = _SYNC_LABELS.get(proc.returncode, (False, "unknown"))
    result = OpsResult("sync", action, proc.returncode, ok, label, proc.stdout, proc.stderr)
    _emit_ops_numbat(argv, result)
    return result


def run_fsconnect_op(
    action: str,
    *,
    root: str | None = None,
    path: str | None = None,
    pattern: str | None = None,
    regex: bool = False,
    recursive: bool = True,
) -> OpsResult:
    """Invoke ``python -m agentic.fsconnect.cli <action>`` and normalize the result.

    Read-only operations: status, test, list, read, stat, grep, glob. File-path
    arguments are passed as ``--root``/``--path``; pattern as ``--pattern``.
    Browser/API grep is literal-only; local CLI users can still run ``--regex``.
    No write operations are exposed via this route.
    """
    if action not in _FSCONNECT_ACTIONS:
        raise OpsError(f"Unknown fsconnect action: {action!r}")
    if regex:
        raise OpsError("fsconnect regex grep is CLI-only; /ops/fsconnect accepts literal grep only")

    argv = [sys.executable, "-m", "agentic.fsconnect.cli", "--config", str(_CONFIG_PATH), action]

    if action in {"list", "read", "stat", "grep", "glob"}:
        # Use the --opt=value form (not two argv elements) for every free-text
        # value: a value that begins with '-'
        # (a grep for the literal string "--dry-run" or "-v", a path/glob with a
        # leading dash) binds to its option instead of being reparsed by the
        # child argparse as a separate flag — which otherwise fails the op with
        # "expected one argument".
        if root:
            argv.append(f"--root={root}")
        if path:
            argv.append(f"--path={path}")
        if pattern and action in {"grep", "glob"}:
            argv.append(f"--pattern={pattern}")
        if not recursive and action == "glob":
            argv.append("--no-recursive")

    proc = _run(argv)
    ok, label = _FSCONNECT_LABELS.get(proc.returncode, (False, "unknown"))
    parsed = _maybe_json(proc.stdout) if (ok and action in _FSCONNECT_JSON_ACTIONS) else None
    result = OpsResult("fsconnect", action, proc.returncode, ok, label, proc.stdout, proc.stderr, parsed)
    _emit_ops_numbat(argv, result)
    return result

