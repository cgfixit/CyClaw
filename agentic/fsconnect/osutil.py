"""Minimal, low-risk OS integration seed: ``reveal`` a folder in the file manager.

Out-of-band and operator-run only (``python -m agentic.fsconnect.cli reveal``): opens
a writable root in the platform file manager via an argv-list subprocess -- never a
shell, never the request path. This is the deliberately small seed for the deferred
OS-integration roadmap (a terminal.html "open file share" button would need a
request-path endpoint and gets its own security review; see the roadmap doc).

Never imported by gate.py / graph.py / mcp_hybrid_server.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404 -- argv-list file-manager launch only; never shell=True
import sys
from pathlib import Path

from agentic.fsconnect.pathsafe import _norm_contains
from utils.errors import FsConnectRuntimeError


def _file_manager_argv(path: str) -> list[str]:
    if os.name == "nt":  # pragma: no cover - Windows only
        return ["explorer", path]
    if sys.platform == "darwin":  # pragma: no cover - macOS only
        return ["open", path]
    return ["xdg-open", path]


def _within_roots(target: Path, allowed_roots: list[str]) -> bool:
    """True if ``target`` (canonicalized) is equal-to or under one of ``allowed_roots``.

    Both sides are ``realpath``-canonicalized (resolving symlinks) and
    ``normcase``-normalized, then compared with the same segment-aware containment
    check the read/write paths use (``pathsafe._norm_contains`` — closes the
    sibling-prefix bypass). A symlink under a root that points outside it resolves
    outside and is therefore refused.
    """
    target_norm = os.path.normcase(os.path.realpath(str(target)))
    for root in allowed_roots:
        if not root:
            continue
        root_norm = os.path.normcase(os.path.realpath(root))
        if _norm_contains(root_norm, target_norm):
            return True
    return False


def reveal(path: str, allowed_roots: list[str]) -> dict:
    """Open ``path`` in the OS file manager, confined to ``allowed_roots``.

    ``reveal`` is the one fsconnect op that previously did not route its target
    through any containment check — it only tested ``exists()`` and handed the raw
    path to the file manager, so ``reveal --root /etc`` opened an arbitrary path
    outside every configured root, contradicting the documented "open a writable
    root" guarantee (a confused-deputy footgun). The target is now canonicalized
    and must be equal-to or under one of ``allowed_roots`` (the connector's
    ``writable_roots``), matching the rest of the connector's scope enforcement.
    """
    if not isinstance(path, str) or path.startswith("-"):
        # Defense in depth: a leading '-' would be an argv-flag shape for the
        # file-manager launch; reject it outright (argv is a list, so not RCE).
        raise FsConnectRuntimeError("invalid reveal target", details={"path": path})
    p = Path(path)
    if not p.exists():
        raise FsConnectRuntimeError(f"path does not exist: {path}", details={"path": path})
    if not _within_roots(p, allowed_roots or []):
        raise FsConnectRuntimeError(
            "reveal target is outside the configured roots",
            details={"path": path},
        )
    argv = _file_manager_argv(str(p))
    exe = shutil.which(argv[0])
    if exe is None:
        raise FsConnectRuntimeError(
            f"file manager {argv[0]!r} not found on PATH",
            details={"looked_for": argv[0]},
        )
    try:
        subprocess.run([exe, str(p)], check=False, timeout=10)  # noqa: S603 -- argv list, no shell
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FsConnectRuntimeError("failed to launch file manager",
                                    details={"error": str(exc)}) from exc
    return {"revealed": str(p), "via": argv[0]}


__all__ = ["reveal"]
