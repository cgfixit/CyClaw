"""Shared root and component policy for filesystem connector capabilities."""

from __future__ import annotations

import os
from pathlib import Path

_PROTECTED = frozenset(
    {
        ".git",
        ".ssh",
        ".aws",
        ".azure",
        ".gnupg",
        ".kube",
        ".codex",
        ".agents",
        ".config",
        ".docker",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".gitconfig",
        ".git-credentials",
        "keychains",
        "keyrings",
        "rclone.conf",
        "hosts.yml",
        "credentials",
        "credentials.json",
    }
)


def protected_component(name: str) -> bool:
    value = name.casefold()
    device = value.split(".", 1)[0]
    reserved = device in {"con", "prn", "aux", "nul"} or (
        len(device) == 4 and device[:3] in {"com", "lpt"} and device[3] in "123456789"
    )
    return (
        reserved
        or value in _PROTECTED
        or value.startswith(".env")
        or value.endswith((".pem", ".key", ".p12", ".pfx", ".keychain-db"))
    )


def validate_root(root: str) -> None:
    """Require a purpose-specific directory, outside secret/config subtrees."""
    path = Path(os.path.expandvars(root)).expanduser().resolve()
    anchors = (Path.home().resolve(), Path(__file__).resolve().parents[2])
    if path == Path(path.anchor) or any(anchor == path or path in anchor.parents for anchor in anchors):
        raise ValueError("filesystem root, home, repository and their ancestors cannot be connector roots")
    system_roots = [Path(value).resolve() for value in ("/etc", "/dev", "/proc", "/sys")]
    if os.name == "nt":
        system_roots = [Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()]
    if any(path == system or system in path.parents for system in system_roots):
        raise ValueError("system configuration/device directories cannot be connector roots")
    if any(protected_component(component) for component in path.parts):
        raise ValueError("protected credential/configuration directories cannot be connector roots")
