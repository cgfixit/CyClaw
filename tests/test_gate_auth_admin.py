"""Stage 6 HTTP admin surface: roles, CSRF, 503-when-disabled."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gate_auth import register_auth_routes
from utils.authn_manager import AuthManager

_GOOD = "correct horse battery staple"
_PORT = 8787
_SAME_ORIGIN = f"http://localhost:{_PORT}"


def _cfg():
    return {
        "api": {"tls": {"enabled": False}, "port": _PORT},
        "security": {"allowed_hosts": ["127.0.0.1", "localhost"]},
        "logging": {"audit_file": "logs/audit.jsonl"},
    }


async def _allow(_request: Request) -> None:
    return None


def _client(manager, events=None):
    app = FastAPI()

    async def audit(event):
        if events is not None:
            events.append(event)

    register_auth_routes(
        app, _cfg(), audit=audit, enforce_rate_limit=_allow, auth_manager=manager,
    )
    return TestClient(app, base_url=_SAME_ORIGIN)  # DevSkim: ignore DS162092,DS137138


@pytest.fixture
def manager(tmp_path):
    m = AuthManager({"auth": {"enabled": True, "db_path": str(tmp_path / "auth.db")}})
    yield m
    m.close()


def _login(client, username, password):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["csrf_token"]


class TestAdminDisabled:
    def test_users_503(self):
        r = _client(None).get("/auth/users")
        assert r.status_code == 503


class TestAdminMatrix:
    def test_whoami_includes_role(self, manager):
        manager.create_user("alice", _GOOD, role="operator")
        client = _client(manager)
        _login(client, "alice", _GOOD)
        r = client.get("/auth/whoami")
        assert r.json()["role"] == "operator"

    def test_operator_cannot_delete_or_set_role(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        manager.create_user("alice", _GOOD, role="operator")
        manager.create_user("bob", _GOOD, role="operator")
        client = _client(manager)
        csrf = _login(client, "alice", _GOOD)
        r = client.delete("/auth/users/bob", headers={"x-cyclaw-csrf": csrf})
        assert r.status_code == 403
        r = client.post(
            "/auth/users/bob/role",
            json={"role": "admin"},
            headers={"x-cyclaw-csrf": csrf},
        )
        assert r.status_code == 403

    def test_operator_cannot_touch_admin(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        manager.create_user("alice", _GOOD, role="operator")
        client = _client(manager)
        csrf = _login(client, "alice", _GOOD)
        r = client.post(
            "/auth/users/root/password",
            json={"password": "another good password!!"},
            headers={"x-cyclaw-csrf": csrf},
        )
        assert r.status_code == 403

    def test_audit_cannot_write_or_list_users(self, manager):
        manager.create_user("eve", _GOOD, role="audit")
        client = _client(manager)
        csrf = _login(client, "eve", _GOOD)
        assert client.get("/auth/users").status_code == 403
        r = client.post(
            "/auth/users",
            json={"username": "newone", "password": _GOOD, "role": "operator"},
            headers={"x-cyclaw-csrf": csrf},
        )
        assert r.status_code == 403

    def test_admin_can_create_and_list(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        client = _client(manager)
        csrf = _login(client, "root", _GOOD)
        r = client.post(
            "/auth/users",
            json={"username": "bob", "password": _GOOD, "role": "operator"},
            headers={"x-cyclaw-csrf": csrf},
        )
        assert r.status_code == 200
        listed = client.get("/auth/users")
        assert listed.status_code == 200
        names = {u["username"] for u in listed.json()}
        assert {"root", "bob"} <= names

    def test_duplicate_create_is_409_with_a_typed_code(self, manager):
        # Characterization: gate_auth already mapped AuthUserExists to 409, but
        # nothing asserted it -- grep AUTH_USER_EXISTS across tests/ was empty
        # before this, so the harness copy could (and did) diverge unnoticed.
        manager.create_user("root", _GOOD, role="admin")
        client = _client(manager)
        csrf = _login(client, "root", _GOOD)
        body = {"username": "bob", "password": _GOOD, "role": "operator"}
        assert client.post("/auth/users", json=body, headers={"x-cyclaw-csrf": csrf}).status_code == 200
        again = client.post("/auth/users", json=body, headers={"x-cyclaw-csrf": csrf})
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "AUTH_USER_EXISTS"

    def test_raced_duplicate_create_is_409_not_an_unhandled_500(self, manager):
        # Blinding the pre-check to "bob" only -- and not to "root" -- is what a
        # racing writer produces, and leaves the DB constraint as the only
        # defence. Scoped to one username on purpose: the same statement
        # resolves the session's own user, so blinding it wholesale 401s the
        # request before it ever reaches create_user. The raw backend error
        # matches no branch of _raise_auth_error's ladder and gate.py registers
        # no RAGError handler, so before the fix this escaped as an unhandled
        # 500.
        manager.create_user("root", _GOOD, role="admin")
        client = _client(manager)
        csrf = _login(client, "root", _GOOD)
        body = {"username": "bob", "password": _GOOD, "role": "operator"}
        assert client.post("/auth/users", json=body, headers={"x-cyclaw-csrf": csrf}).status_code == 200
        manager._sql_get_user += " AND username <> 'bob'"
        again = client.post("/auth/users", json=body, headers={"x-cyclaw-csrf": csrf})
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "AUTH_USER_EXISTS"

    def test_csrf_missing_on_create_is_403(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        client = _client(manager)
        _login(client, "root", _GOOD)
        r = client.post(
            "/auth/users",
            json={"username": "bob", "password": _GOOD, "role": "operator"},
        )
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "CSRF_TOKEN_INVALID"

    def test_audit_can_open_summary(self, manager):
        manager.create_user("eve", _GOOD, role="audit")
        client = _client(manager)
        _login(client, "eve", _GOOD)
        r = client.get("/auth/audit/summary")
        assert r.status_code == 200

    def test_operator_cannot_open_audit_summary(self, manager):
        manager.create_user("alice", _GOOD, role="operator")
        client = _client(manager)
        _login(client, "alice", _GOOD)
        assert client.get("/auth/audit/summary").status_code == 403


class TestAdminLifecycle:
    """Success and refusal paths of role/disable/enable/delete, per the CLAUDE.md route table."""

    def test_last_admin_cannot_be_demoted_disabled_or_deleted(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        client = _client(manager)
        h = {"x-cyclaw-csrf": _login(client, "root", _GOOD)}
        attempts = {
            "set_role": client.post("/auth/users/root/role", json={"role": "operator"}, headers=h),
            "disable_user": client.post("/auth/users/root/disable", headers=h),
            "delete_user": client.delete("/auth/users/root", headers=h),
        }
        for action, r in attempts.items():
            assert r.status_code == 403, action
            assert r.json()["detail"]["code"] == "AUTH_LAST_ADMIN"
            assert r.json()["detail"]["details"]["action"] == action
        assert manager.get_user("root").role == "admin"

    def test_admin_sets_role_and_it_is_audited(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        manager.create_user("bob", _GOOD, role="operator")
        events: list[dict] = []
        client = _client(manager, events)
        h = {"x-cyclaw-csrf": _login(client, "root", _GOOD)}
        bad = client.post("/auth/users/bob/role", json={"role": "god"}, headers=h)
        assert bad.status_code == 422
        assert bad.json()["detail"]["code"] == "AUTH_POLICY"
        r = client.post("/auth/users/bob/role", json={"role": "admin"}, headers=h)
        assert r.status_code == 200
        assert manager.get_user("bob").role == "admin"
        assert {"event": "auth_role_set", "username": "root", "target": "bob", "role": "admin"} in events

    def test_disable_blocks_login_until_enable(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        manager.create_user("bob", _GOOD, role="operator")
        events: list[dict] = []
        client = _client(manager, events)
        h = {"x-cyclaw-csrf": _login(client, "root", _GOOD)}
        other = _client(manager)
        r = client.post("/auth/users/bob/disable", headers=h)
        assert r.status_code == 200
        r = other.post("/auth/login", json={"username": "bob", "password": _GOOD})
        assert r.status_code == 401
        r = client.post("/auth/users/bob/enable", headers=h)
        assert r.status_code == 200
        r = other.post("/auth/login", json={"username": "bob", "password": _GOOD})
        assert r.status_code == 200
        kinds = [e["event"] for e in events if e.get("target") == "bob"]
        assert kinds == ["auth_user_disabled", "auth_user_enabled"]

    def test_operator_toggles_operators_but_not_admins(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        manager.create_user("alice", _GOOD, role="operator")
        manager.create_user("carol", _GOOD, role="operator")
        client = _client(manager)
        h = {"x-cyclaw-csrf": _login(client, "alice", _GOOD)}
        r = client.post("/auth/users/carol/disable", headers=h)
        assert r.status_code == 200
        r = client.post("/auth/users/carol/enable", headers=h)
        assert r.status_code == 200
        r = client.post("/auth/users/root/disable", headers=h)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "AUTH_PERMISSION_DENIED"
        assert not manager.get_user("root").disabled

    def test_admin_hard_deletes_and_unknown_users_are_404(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        manager.create_user("carol", _GOOD, role="operator")
        events: list[dict] = []
        client = _client(manager, events)
        h = {"x-cyclaw-csrf": _login(client, "root", _GOOD)}
        r = client.delete("/auth/users/carol", headers=h)
        assert r.status_code == 200
        assert manager.get_user("carol") is None
        assert {"event": "auth_user_deleted", "username": "root", "target": "carol"} in events
        for r in (
            client.delete("/auth/users/ghost", headers=h),
            client.post("/auth/users/ghost/disable", headers=h),
            client.post("/auth/users/ghost/enable", headers=h),
        ):
            assert r.status_code == 404
            assert r.json()["detail"]["code"] == "AUTH_USER_NOT_FOUND"

    def test_lifecycle_writes_need_csrf(self, manager):
        manager.create_user("root", _GOOD, role="admin")
        manager.create_user("bob", _GOOD, role="operator")
        client = _client(manager)
        _login(client, "root", _GOOD)
        for r in (
            client.post("/auth/users/bob/disable"),
            client.post("/auth/users/bob/role", json={"role": "audit"}),
            client.delete("/auth/users/bob"),
        ):
            assert r.status_code == 403
            assert r.json()["detail"]["code"] == "CSRF_TOKEN_INVALID"
        assert not manager.get_user("bob").disabled


class TestUserLookupsLeaveTheEventLoop:
    def test_no_async_handler_runs_get_user_on_the_event_loop(self, manager):
        """get_user takes the manager's connection lock, which a worker can hold
        through a BEGIN IMMEDIATE busy wait. Called from an async handler it
        stalled every route on the server for that long, so each lookup must
        run in a worker thread (no running event loop there)."""
        manager.create_user("root", _GOOD, role="admin")
        manager.create_user("bob", _GOOD, role="operator")
        on_loop: list[str] = []
        real_get_user = manager.get_user

        def spy(username):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                on_loop.append(username)
            return real_get_user(username)

        manager.get_user = spy
        client = _client(manager)
        _login(client, "root", _GOOD)
        whoami = client.get("/auth/whoami")
        assert whoami.status_code == 200
        h = {"x-cyclaw-csrf": whoami.json()["csrf_token"]}
        for r in (
            client.get("/auth/users"),
            client.post("/auth/users", json={"username": "carol", "password": _GOOD, "role": "operator"}, headers=h),
            client.post("/auth/users/bob/password", json={"password": _GOOD + "!"}, headers=h),
            client.post("/auth/users/bob/disable", headers=h),
            client.post("/auth/users/bob/enable", headers=h),
            client.get("/auth/audit/summary"),
        ):
            assert r.status_code == 200, r.text
        assert on_loop == []
