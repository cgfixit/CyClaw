"""Busy (503) rejections must still leave an audit trail, and that trail must
never carry secrets.

Contract tests for Advisor's FAIL on #1547 (fix-1547):

* GRAPH_BUSY on /query is a query rejection, so INVARIANTS.md Rule 3 / I4
  ("every query ... must emit an audit event") applies exactly as it does to
  prompt_injection_blocked, graph_timeout and graph_error.
* AUTH_BUSY on every password route must be audited, and the audit record must
  never contain a password. On the unauthenticated routes (login, bootstrap) it
  must not contain the caller-supplied username either, matching
  auth_login_failed, which records only the client IP.

Flood note: every route here runs the rate limiter before the busy check, so
per-IP audit volume on these paths is already bounded; no extra throttle is
asserted.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gate_auth import register_auth_routes
from tests.conftest import _mocked_gateway
from utils.authn_manager import AuthManager
from utils.bounded_executor import WorkCapacityExceeded

_PEER = ("127.0.0.47", 51234)  # DevSkim: ignore DS162092,DS137138 - test loopback peer
_PASSWORD = "correct horse battery staple"
_SECRET_MARKER = "pyshield-secret-marker-9f3c"
_USER_MARKER = "pyshield-user-marker-7d1a"


def _busy() -> AsyncMock:
    return AsyncMock(side_effect=WorkCapacityExceeded("worker capacity is exhausted"))


def _assert_busy_response(resp: Any, code: str) -> None:
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == code
    assert resp.headers.get("Retry-After") == "1"


# ---------------------------------------------------------------- GRAPH_BUSY


@pytest.fixture
def gateway(tmp_path: Path) -> Iterator[tuple[TestClient, MagicMock]]:
    with _mocked_gateway(tmp_path, peer=_PEER) as pair:
        yield pair


def test_graph_busy_is_audited_with_the_query(gateway: tuple[TestClient, MagicMock]) -> None:
    import gate

    test_client, mock_graph = gateway
    query = "graph busy contract probe"
    audit = AsyncMock()
    with patch.object(gate._graph_workers, "run", new=_busy()), patch("gate._audit", new=audit):
        resp = test_client.post("/query", json={"query": query})

    _assert_busy_response(resp, "GRAPH_BUSY")
    mock_graph.invoke.assert_not_called()
    events = [call.args[0] for call in audit.await_args_list]
    busy = [e for e in events if e.get("query") == query]
    assert len(busy) == 1, f"GRAPH_BUSY must emit exactly one /query audit event, got {events!r}"
    # The raw query goes only in the "query" field, which audit_log fingerprints.
    # No other field may carry it, and the exception text must not leak in.
    leaked = {k: v for k, v in busy[0].items() if k != "query" and query in str(v)}
    assert not leaked, f"raw query leaked outside the fingerprinted field: {leaked!r}"
    assert "worker capacity" not in str(busy[0])


# ----------------------------------------------------------------- AUTH_BUSY


_ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
_BASE_URL = "http://localhost:8787"
_LOOPBACK_CLIENT = ("127.0.0.1", 50000)  # DevSkim: ignore DS162092,DS137138 - test loopback peer


async def _allow_all(_request: Request) -> None:
    return None


def _auth_app(manager: AuthManager) -> FastAPI:
    events: list[dict[str, Any]] = []

    async def audit(event: dict[str, Any]) -> None:
        events.append(event)

    app = FastAPI()
    register_auth_routes(
        app,
        {"api": {"tls": {"enabled": False}, "port": 8787}, "security": {"allowed_hosts": _ALLOWED_HOSTS}},
        audit=audit,
        enforce_rate_limit=_allow_all,
        auth_manager=manager,
    )
    app.state.audit_events = events
    return app


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[AuthManager]:
    m = AuthManager({"auth": {"enabled": True, "db_path": str(tmp_path / "auth.db")}})
    yield m
    m.close()


def _new_events(app: FastAPI, start: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = app.state.audit_events
    return events[start:]


def _assert_no_secret(events: list[dict[str, Any]]) -> None:
    for event in events:
        assert _SECRET_MARKER not in str(event), f"password material in audit event: {event!r}"


def test_login_auth_busy_is_audited_without_credentials(manager: AuthManager) -> None:
    app = _auth_app(manager)
    client = TestClient(app, base_url=_BASE_URL)
    app.state.auth_workers.run = _busy()

    resp = client.post("/auth/login", json={"username": _USER_MARKER, "password": _SECRET_MARKER})

    _assert_busy_response(resp, "AUTH_BUSY")
    events = _new_events(app, 0)
    busy = [e for e in events if e.get("event") == "auth_busy"]
    assert len(busy) == 1, f"AUTH_BUSY on /auth/login must emit exactly one auth_busy audit event, got {events!r}"
    _assert_no_secret(events)
    for event in events:
        assert _USER_MARKER not in str(event), f"unauthenticated username in audit event: {event!r}"


def test_bootstrap_auth_busy_is_audited_without_credentials(manager: AuthManager) -> None:
    manager.bootstrap_if_empty()
    app = _auth_app(manager)
    client = TestClient(app, base_url=_BASE_URL, client=_LOOPBACK_CLIENT)
    app.state.auth_workers.run = _busy()

    resp = client.post("/auth/bootstrap-password", json={"password": _SECRET_MARKER})

    _assert_busy_response(resp, "AUTH_BUSY")
    events = _new_events(app, 0)
    busy = [e for e in events if e.get("event") == "auth_busy"]
    assert len(busy) == 1, (
        f"AUTH_BUSY on /auth/bootstrap-password must emit exactly one auth_busy audit event, got {events!r}"
    )
    _assert_no_secret(events)
    assert manager.needs_password_setup() is True


def _admin_session(manager: AuthManager, app: FastAPI) -> tuple[TestClient, dict[str, str]]:
    manager.create_user("alice", _PASSWORD, "admin")
    client = TestClient(app, base_url=_BASE_URL)
    login = client.post("/auth/login", json={"username": "alice", "password": _PASSWORD})
    assert login.status_code == 200
    return client, {"X-CyClaw-CSRF": login.json()["csrf_token"]}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/auth/users", {"username": _USER_MARKER, "password": _SECRET_MARKER}),
        ("post", "/auth/users/alice/password", {"password": _SECRET_MARKER}),
        ("post", "/auth/password", {"current_password": _SECRET_MARKER, "password": _SECRET_MARKER + "-new"}),
    ],
    ids=["create_user", "set_password", "change_password"],
)
def test_admin_auth_busy_is_audited_without_passwords(
    manager: AuthManager, method: str, path: str, body: dict[str, str]
) -> None:
    app = _auth_app(manager)
    client, headers = _admin_session(manager, app)
    start = len(app.state.audit_events)
    app.state.auth_workers.run = _busy()

    resp = getattr(client, method)(path, json=body, headers=headers)

    _assert_busy_response(resp, "AUTH_BUSY")
    events = _new_events(app, start)
    busy = [e for e in events if e.get("event") == "auth_busy"]
    assert len(busy) == 1, f"AUTH_BUSY on {path} must emit exactly one auth_busy audit event, got {events!r}"
    _assert_no_secret(events)
