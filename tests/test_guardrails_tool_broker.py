"""ToolBroker: deny unknown names; NeMo cannot grant."""

from __future__ import annotations

import inspect

import pytest

from guardrails.tool_broker import decide as guardrails_decide
from utils.tool_broker import ToolDenied, assert_allowed, decide


def test_decide_has_no_rails_parameter() -> None:
    assert "rails" not in inspect.signature(decide).parameters
    assert "nemo" not in inspect.signature(decide).parameters


def test_guardrails_reexport_is_utils_decide() -> None:
    assert guardrails_decide is decide


def test_allowlisted_name_is_allowed() -> None:
    v = decide("web_fetch", ("https://example.com/x",), allowlist=frozenset({"web_fetch"}))
    assert v.allowed is True
    assert len(v.argv_digest) == 64
    assert "example.com" not in v.argv_digest


def test_unknown_name_is_denied() -> None:
    v = decide("shell", ("rm", "-rf", "/"), allowlist=frozenset({"web_fetch"}))
    assert v.allowed is False
    assert v.reason == "unknown tool"


def test_empty_allowlist_is_denied() -> None:
    v = decide("web_fetch", ("https://example.com/"), allowlist=frozenset())
    assert v.allowed is False


def test_assert_allowed_raises_on_unknown() -> None:
    with pytest.raises(ToolDenied, match="unknown tool"):
        assert_allowed("shell", ("id",), allowlist=frozenset({"web_fetch"}))


def test_fake_nemo_allow_cannot_be_passed_to_decide() -> None:
    """Signature has no NeMo grant knob; extra kwargs raise TypeError."""
    extra = "".join(("ra", "ils"))
    with pytest.raises(TypeError):
        decide("shell", (), allowlist=frozenset({"web_fetch"}), **{extra: object()})

