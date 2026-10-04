"""Static scope contract for deploy/apparmor/cyclaw-bwrap.

The profile exists so stock Ubuntu 24.04+ hosts can run CyClaw's bwrap sandbox
without the global ``kernel.apparmor_restrict_unprivileged_userns=0`` sysctl.
It must stay a one-rule exemption for exactly ``/usr/bin/bwrap``:

* attaches to that exact path, with no AppArmor glob or alternation characters;
* declares exactly one profile, with ``userns,`` as its only rule;
* no ``include if exists <local/...>`` hook that could widen it on a host;
* ``flags=(unconfined)`` is disclosed in a comment, along with the reasoning
  for not using Ubuntu's ``bwrap-userns-restrict``.

CI (ubuntu-latest) proves the runtime side: stock policy refuses bwrap, this
profile loads, and scripts/verify_agentic_sandbox.py passes.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "deploy" / "apparmor" / "cyclaw-bwrap"
README = REPO_ROOT / "deploy" / "apparmor" / "README.md"

ATTACH_PATH = "/usr/bin/bwrap"
EXPECTED_RULES = [
    "abi <abi/4.0>,",
    "include <tunables/global>",
    f"profile cyclaw-bwrap {ATTACH_PATH} flags=(unconfined) {{",
    "userns,",
    "}",
]
_AA_GLOB_CHARS = set("*?[]{}^@")


def _text() -> str:
    return PROFILE.read_text(encoding="utf-8")


def _rules() -> list[str]:
    lines = (line.split("#", 1)[0].strip() for line in _text().splitlines())
    return [line for line in lines if line]


def _comments() -> str:
    return "\n".join(line for line in _text().splitlines() if line.lstrip().startswith("#"))


def test_profile_is_exactly_one_userns_rule_for_bwrap() -> None:
    assert _rules() == EXPECTED_RULES


def test_attach_path_is_exact_and_glob_free() -> None:
    headers = [r for r in _rules() if re.match(r"^(profile|hat)\b|^\^|^/", r)]
    assert len(headers) == 1, headers
    tokens = headers[0].split()
    assert tokens[:3] == ["profile", "cyclaw-bwrap", ATTACH_PATH]
    assert not (_AA_GLOB_CHARS & set(tokens[2]))


def test_no_widening_hooks_or_extra_permissions() -> None:
    body = "\n".join(_rules())
    assert "include if exists" not in body
    assert "<local/" not in body
    for widening in (
        "capability",
        "mount",
        "ptrace",
        "network",
        "file",
        "dbus",
        "change_profile",
        "pivot_root",
        "ix",
        "px",
        "ux",
    ):
        assert not re.search(rf"(?<![\w/]){widening}\b", body), widening


def test_unconfined_and_choice_are_disclosed() -> None:
    comments = _comments().lower()
    assert "unconfined" in comments
    assert "bwrap itself runs without apparmor confinement" in comments
    assert "bwrap-userns-restrict" in comments
    readme = README.read_text(encoding="utf-8")
    assert "deploy/apparmor/cyclaw-bwrap" in readme
    assert "bwrap-userns-restrict" in readme
    assert "unconfined" in readme.lower()


def test_profile_never_recommends_global_sysctl_as_fix() -> None:
    for line in _text().splitlines():
        if "apparmor_restrict_unprivileged_userns=0" in line:
            assert "never" in line.lower(), line
