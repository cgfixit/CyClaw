"""Explicit capability environments for trusted helper subprocesses.

Start empty: adding a credential to the gateway never grants it to a child.
This limits inheritance; it is not filesystem or same-user process isolation.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable, Mapping
from contextlib import contextmanager

from utils.telemetry_kill import build_telemetry_safe_env

_BASE = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "SystemRoot", "SYSTEMROOT", "WINDIR", "PATHEXT", "TEMP", "TMP", "TMPDIR")
_DISCOVERY = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME")
_CAPABILITIES = {
    "helper": (),
    "verification": (),
    "sync": (*_DISCOVERY, "RCLONE_CONFIG", "RCLONE_CONFIG_PASS"),
    "github": (*_DISCOVERY, "GH_CONFIG_DIR", "GH_HOST", "GH_TOKEN", "GITHUB_TOKEN"),
    "filesystem": _DISCOVERY,
    "sql": _DISCOVERY,
}


def child_environment(
    capability: str = "helper", *, secret_names: Iterable[str] = (), source: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Copy only the named capability and explicitly selected configuration keys."""
    parent = os.environ if source is None else source
    names = (*_BASE, *_CAPABILITIES[capability], *secret_names)
    return build_telemetry_safe_env({name: parent[name] for name in names if name in parent})


@contextmanager
def isolated_helper_environment():
    """Give stateless helpers a disposable home for their complete lifetime."""
    with tempfile.TemporaryDirectory(prefix="cyclaw-helper-") as home:
        env = child_environment()
        env.update(HOME=home, USERPROFILE=home, XDG_CONFIG_HOME=home, TMPDIR=home, TEMP=home, TMP=home)
        yield env


_PATH_FIELDS = frozenset(
    {
        "allowed_roots",
        "writable_roots",
        "index_root",
        "workspace_root",
        "registry_path",
        "output_dir",
        "memory_dir",
        "local_path",
        "workdir",
        "filter_file",
        "log_dir",
    }
)


def configured_path_names(block: object) -> tuple[str, ...]:
    """Retain named directory variables only where a capability config uses them.

    Names must describe paths and cannot select secrets or runtime loader controls.
    Missing or non-absolute values fail before launching a child with a changed root.
    """
    import re

    values: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            collect(value.get("path"))

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _PATH_FIELDS:
                    collect(item)
                elif isinstance(item, dict):
                    visit(item)

    visit(block)
    names = {
        match[0] or match[1]
        for value in values
        for match in re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", value)
    }
    if not names:
        return ()
    from utils.secret_policy import is_secret_name

    for name in names:
        upper = name.upper()
        if (
            is_secret_name(name)
            or not upper.endswith(("ROOT", "DIR", "HOME", "PATH", "FOLDER"))
            or upper.startswith(("PYTHON", "NODE", "LD_", "DYLD_", "GIT_", "GH_"))
        ):
            raise ValueError(f"configuration path variable {name} is not an allowed directory capability")
        if not os.path.isabs(os.environ.get(name, "")):
            raise ValueError(f"configuration path variable {name} must contain an absolute path")
    return tuple(sorted(names))
