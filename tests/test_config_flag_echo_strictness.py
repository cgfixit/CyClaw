"""The memory-flag echo must agree with the gate it reports on.

PR #1199 renamed `memory.facts.enabled` to `facts.retrieval_enabled` and put the
resolution behind `memory/flags.facts_retrieval_enabled`, whose module docstring
states the reason: *"Three readers of one flag drift; one function does not."*

This pins the whole set because the sibling gaps were the larger problem:
`memory/mirror.py.status_dict` is the body of `GET /memory/status`. It used the
shared helper for `facts` and `is True` for the master key, then hand-rolled
loose `bool()` for the other five -- including `propose_apply` and
`export_html`, the write and export gates.

Why a quoted value is the realistic trigger rather than a contrived one: the
`memory:` block has **no validator**. There is no `validate_memory_config`, and
gate.py's validators do not cover it, so `enabled: "false"` boots silently. Under
`bool()` every non-empty string is truthy, so the echo reported a capability
ON while the gate refused it -- and `"true"`, the value an operator writes when
they mean to switch something on, fails the same way.

These tests assert AGREEMENT with the gate rather than a fixed expected value.
The contract is the mirror, so the mirror is what must hold.
"""

from __future__ import annotations

import pytest

from memory.mirror import status_dict

# Ten shapes spanning the ways a config value arrives: YAML-quoted booleans (the
# real-world trigger), truthy/falsy non-booleans, and the two real booleans.
# Only the literal True may read as enabled.
_SHAPES = ["false", "true", "no", "yes", "", 0, 1, None, False, True]

# key in the memory: block -> key in the echo's output dict
_MIRROR_KEYS = {
    "episodes": "episodes_enabled",
    "retrieval_fusion": "retrieval_fusion_enabled",
    "propose_apply": "propose_apply_enabled",
    "export_html": "export_html_enabled",
    "consolidation": "consolidation_enabled",
}


def _cfg(block: dict) -> dict:
    return {"memory": block}


def _block(tmp_path, **extra: object) -> dict:
    # A real path under tmp_path, never the sqlite ":memory:" sentinel:
    # memory.store.connect treats db_path as a filesystem path and CREATES it,
    # so ":memory:" produces a file literally named ":memory:" in the CWD --
    # a path Windows cannot check out (`error: invalid path`). Learned the hard
    # way; tests/test_repo_hygiene.py now guards the repo against it.
    return {"enabled": True, "db_path": str(tmp_path / "flags.db"), **extra}


@pytest.mark.parametrize("value", _SHAPES)
@pytest.mark.parametrize("section", sorted(_MIRROR_KEYS))
def test_mirror_status_echo_agrees_with_the_gate(section: str, value: object, tmp_path):
    """GET /memory/status must not claim a capability its gate refuses."""
    out = status_dict(_cfg(_block(tmp_path, **{section: {"enabled": value}})))
    assert out[_MIRROR_KEYS[section]] is (value is True), (
        f"/memory/status reported {section}={out[_MIRROR_KEYS[section]]!r} "
        f"for a configured value of {value!r}; every gate on this key accepts "
        f"only the literal True"
    )


@pytest.mark.parametrize("value", _SHAPES)
def test_mirror_master_enabled_echo_agrees_with_the_gate(value: object, tmp_path):
    out = status_dict(_cfg({"enabled": value, "db_path": str(tmp_path / "flags.db")}))
    assert out["enabled"] is (value is True)

