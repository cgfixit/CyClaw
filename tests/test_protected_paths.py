"""Unit tests for agentic.fsconnect.protected_paths.

Direct coverage of protected_component and validate_root. Broader fsconnect
integration still lives in test_fsconnect_*; this file pins the shared policy
module's public contracts without touching app code.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentic.fsconnect.protected_paths import protected_component, validate_root


@pytest.mark.parametrize(
    "name",
    [
        ".git",
        ".ssh",
        ".aws",
        ".gnupg",
        ".config",
        ".docker",
        ".netrc",
        ".env",
        ".env.local",
        ".env.production",
        "secret.pem",
        "id_rsa.key",
        "store.p12",
        "cert.pfx",
        "login.keychain-db",
        "credentials",
        "credentials.json",
        "rclone.conf",
        "keychains",
        "keyrings",
        "CON",
        "con",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "com9",
        "LPT1",
        "lpt9",
    ],
)
def test_protected_component_flags_credential_and_reserved_names(name: str) -> None:
    assert protected_component(name) is True


@pytest.mark.parametrize(
    "name",
    ["hello.txt", "docs", "share", ".editorconfig", "README.md", "envfile", "key"],
)
def test_protected_component_allows_ordinary_names(name: str) -> None:
    assert protected_component(name) is False


def test_validate_root_accepts_purpose_specific_directory(tmp_path: Path) -> None:
    root = tmp_path / "CyClaw-FS"
    root.mkdir()
    validate_root(str(root))  # does not raise


def test_validate_root_refuses_filesystem_root() -> None:
    with pytest.raises(ValueError, match="filesystem root, home, repository"):
        validate_root("/" if os.name != "nt" else "C:\\")


def test_validate_root_refuses_home_directory() -> None:
    with pytest.raises(ValueError, match="filesystem root, home, repository"):
        validate_root(str(Path.home()))


def test_validate_root_refuses_repository_root() -> None:
    repo = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="filesystem root, home, repository"):
        validate_root(str(repo))


def test_validate_root_refuses_home_ancestor() -> None:
    # An ancestor of $HOME must not be a connector root.
    home = Path.home().resolve()
    if len(home.parts) < 2:
        pytest.skip("home has no parent to refuse")
    ancestor = home.parent
    with pytest.raises(ValueError, match="filesystem root, home, repository"):
        validate_root(str(ancestor))


@pytest.mark.skipif(os.name == "nt", reason="POSIX system roots")
@pytest.mark.parametrize("root", ["/etc", "/etc/ssh", "/dev", "/proc", "/sys"])
def test_validate_root_refuses_posix_system_trees(root: str) -> None:
    with pytest.raises(ValueError, match="system configuration/device"):
        validate_root(root)


@pytest.mark.parametrize(
    "suffix",
    [".ssh", ".git", ".aws", ".env", "credentials", "secret.pem"],
)
def test_validate_root_refuses_protected_path_components(
    tmp_path: Path, suffix: str
) -> None:
    # Build under tmp so home/repo/system checks do not fire first.
    root = tmp_path / "share" / suffix
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="protected credential/configuration"):
        validate_root(str(root))


def test_validate_root_expands_user_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "expanded-share"
    root.mkdir()
    monkeypatch.setenv("CYCLAW_TEST_SHARE", str(root))
    validate_root("$CYCLAW_TEST_SHARE")  # does not raise
