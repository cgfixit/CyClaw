"""Console operator session: utils/console_session.py and its gate.py wiring.

The browser console no longer needs CYCLAW_API_KEY in the page. It trades
the key (or a launcher's one-time pairing code) for an HttpOnly cookie, or,
with auth.enabled, an enabled admin's login session satisfies the API-key
routes directly. These tests pin both halves, plus the controls around them:
CSRF on state-changing requests, the cross-site refusal, role checks, and
the fail-closed behavior when CYCLAW_API_KEY is unset.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.conftest import _mocked_gateway
from utils import console_session
from utils.config_validation import validate_console_session_config
from utils.errors import ConfigError

KEY = "k" * 40
OTHER_KEY = "o" * 40
PAIR = "p" * 32
_BEARER = {"Authorization": f"Bearer {KEY}"}
_CROSS_SITE = {"Sec-Fetch-Site": "cross-site"}


# ---------------------------------------------------------------- module


def test_mint_then_verify_round_trips():
    minted = console_session.mint(KEY, 600, now=1000.0, audience="https://localhost:8787")
    got = console_session.verify(KEY, minted.token, now=1001.0, audience="https://localhost:8787")
    assert got is not None
    assert got.expires_at == 1600
    assert got.csrf == minted.csrf
    assert console_session.verify(KEY, minted.token, now=1001.0, audience="https://localhost:8788") is None


def test_verify_refuses_other_key_expiry_tampering_and_garbage():
    minted = console_session.mint(KEY, 600, now=1000.0)
    assert console_session.verify(OTHER_KEY, minted.token, now=1001.0) is None
    assert console_session.verify("", minted.token, now=1001.0) is None
    assert console_session.verify(KEY, minted.token, now=1600.0) is None
    version, expiry, nonce, mac = minted.token.split(".")
    stretched = ".".join([version, str(int(expiry) + 10_000), nonce, mac])
    assert console_session.verify(KEY, stretched, now=1001.0) is None
    for junk in (None, "", "v1.1.2", "v2.1600.n.m", "x" * 300, "v1.notanint.n.m"):
        assert console_session.verify(KEY, junk, now=1001.0) is None


def test_mint_refuses_without_a_key():
    with pytest.raises(ValueError):
        console_session.mint("", 600)


def test_csrf_matches_only_its_own_token():
    minted = console_session.mint(KEY, 600)
    assert console_session.csrf_matches(minted, minted.csrf)
    assert not console_session.csrf_matches(minted, "")
    assert not console_session.csrf_matches(minted, None)
    assert not console_session.csrf_matches(minted, console_session.mint(KEY, 600).csrf)


def test_pairing_code_is_single_use_and_expires():
    code = console_session.PairingCode(PAIR, 300, now=1000.0)
    assert not code.redeem("q" * 32, now=1001.0)
    assert code.redeem(PAIR, now=1001.0)
    assert not code.redeem(PAIR, now=1002.0)
    late = console_session.PairingCode(PAIR, 300, now=1000.0)
    assert not late.redeem(PAIR, now=1300.0)


def test_pairing_window_opens_at_start_not_construction():
    """The TTL counts from start() (gate.py's lifespan, once serving), so a
    slow import-time boot cannot spend the window; start() never extends it."""
    code = console_session.PairingCode(PAIR, 300)
    code.start(now=5000.0)
    code.start(now=5200.0)
    assert not code.redeem(PAIR, now=5300.0)
    fresh = console_session.PairingCode(PAIR, 300)
    fresh.start(now=5000.0)
    assert fresh.redeem(PAIR, now=5299.0)


def test_pairing_code_refuses_short_or_missing_codes():
    assert not console_session.PairingCode("short", 300).redeem("short")
    assert not console_session.PairingCode(None, 300).redeem(PAIR)
    assert not console_session.PairingCode(PAIR, 300).redeem(None)


def test_pairing_code_leaves_the_environment():
    env = {console_session.PAIRING_ENV: PAIR, "OTHER": "1"}
    code = console_session.PairingCode.from_env(300, environ=env)
    assert console_session.PAIRING_ENV not in env
    assert code.available
    assert code.redeem(PAIR)
    assert not code.available


def test_config_defaults_and_bounds():
    assert validate_console_session_config({}) == (3600, 300)
    assert validate_console_session_config(
        {"security": {"console_session_ttl_sec": 3600, "console_pairing_ttl_sec": 60}}
    ) == (3600, 60)
    for bad in (0, 59, 604801, True, "3600", 1.5, None):
        with pytest.raises(ConfigError):
            validate_console_session_config({"security": {"console_session_ttl_sec": bad}})
    with pytest.raises(ConfigError):
        validate_console_session_config({"security": {"console_pairing_ttl_sec": 7200}})


# ---------------------------------------------------------------- gate wiring


@pytest.fixture
def gw(tmp_path, monkeypatch):
    """Mocked gateway on this file's own loopback peer, with a stub soul."""
    monkeypatch.setenv("CYCLAW_API_KEY", KEY)
    with _mocked_gateway(tmp_path, peer=("127.0.0.21", 51234)) as (test_client, _):  # DevSkim: ignore DS162092,DS137138 - test loopback peer
        import gate

        soul = MagicMock()
        soul.get_version.return_value = 3
        soul.get_system_prompt_additive.return_value = "# Soul"
        soul.soul_path = "soul.md"
        monkeypatch.setattr(gate, "personality", soul)
        monkeypatch.setattr(gate, "auth_manager", None)
        yield test_client, gate


def _unlock(test_client) -> str:
    resp = test_client.post("/console/session", headers=_BEARER, json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf"]


def test_no_credential_is_still_refused(gw):
    test_client, _ = gw
    assert test_client.get("/soul").status_code == 401
    assert test_client.get("/console/session").json()["active"] is False


def test_key_trade_unlocks_reads_and_csrf_guards_writes(gw):
    test_client, _ = gw
    csrf = _unlock(test_client)
    assert test_client.get("/soul").status_code == 200
    status = test_client.get("/console/session").json()
    assert status["active"] is True and status["via"] == "console_key"
    assert status["csrf"] == csrf
    denied = test_client.post("/soul/reload")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "CSRF_TOKEN_INVALID"
    ok = test_client.post("/soul/reload", headers={console_session.CSRF_HEADER: csrf})
    assert ok.status_code == 200


def test_cookie_is_httponly_and_strict(gw):
    test_client, gate = gw
    resp = test_client.post("/console/session", headers=_BEARER, json={})
    cookie = resp.headers["set-cookie"].lower()
    assert cookie.startswith(f"{console_session.COOKIE_NAME}=")
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert f"max-age={gate._CONSOLE_SESSION_TTL}" in cookie
    assert "expires=" not in cookie


def test_wrong_key_is_refused_and_audited(gw, tmp_path):
    test_client, _ = gw
    resp = test_client.post("/console/session", headers={"Authorization": "Bearer nope"}, json={})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "CONSOLE_SESSION_DENIED"
    assert "console_session_rejected" in (tmp_path / "audit.jsonl").read_text()


def test_unset_key_fails_closed(gw, monkeypatch):
    test_client, _ = gw
    _unlock(test_client)
    monkeypatch.delenv("CYCLAW_API_KEY")
    assert test_client.get("/soul").status_code == 401
    assert test_client.post("/console/session", headers=_BEARER, json={}).status_code == 401


def test_rotating_the_key_invalidates_the_cookie(gw, monkeypatch):
    test_client, _ = gw
    _unlock(test_client)
    monkeypatch.setenv("CYCLAW_API_KEY", OTHER_KEY)
    assert test_client.get("/soul").status_code == 401


def test_pairing_code_unlocks_once(gw, monkeypatch, tmp_path):
    test_client, gate = gw
    monkeypatch.setattr(gate, "_console_pairing", console_session.PairingCode(PAIR, 300))
    first = test_client.post("/console/session", json={"pairing_code": PAIR})
    assert first.status_code == 200
    assert test_client.get("/soul").status_code == 200
    test_client.cookies.clear()
    assert test_client.post("/console/session", json={"pairing_code": PAIR}).status_code == 401
    assert '"via": "pairing_code"' in (tmp_path / "audit.jsonl").read_text()


def test_lifespan_starts_the_pairing_clock(gw, monkeypatch):
    test_client, gate = gw
    from utils.bounded_executor import BoundedExecutor

    monkeypatch.setattr(gate, "_graph_workers", BoundedExecutor(1, name="pairing-graph"))
    monkeypatch.setattr(gate.app.state, "auth_workers", BoundedExecutor(1, name="pairing-auth"))
    code = console_session.PairingCode(PAIR, 300)
    monkeypatch.setattr(gate, "_console_pairing", code)
    with test_client:
        assert code._deadline is not None
        assert test_client.post("/console/session", json={"pairing_code": PAIR}).status_code == 200


def test_ending_the_session_locks_again(gw):
    test_client, _ = gw
    _unlock(test_client)
    assert test_client.post("/console/session/end").status_code == 200
    assert test_client.get("/soul").status_code == 401


def test_cross_site_requests_get_nothing(gw):
    test_client, _ = gw
    _unlock(test_client)
    assert test_client.get("/soul", headers=_CROSS_SITE).status_code == 403
    assert test_client.get("/console/session", headers=_CROSS_SITE).status_code == 403
    assert test_client.post("/console/session", headers={**_BEARER, **_CROSS_SITE}, json={}).status_code == 403


def test_bearer_key_still_works_without_any_cookie(gw):
    test_client, _ = gw
    assert test_client.get("/soul", headers=_BEARER).status_code == 200
    assert test_client.post("/soul/reload", headers=_BEARER).status_code == 200


# ---------------------------------------------------------------- admin login


@pytest.fixture
def with_auth(gw, tmp_path, monkeypatch):
    from utils.authn_manager import AuthManager

    test_client, gate = gw
    manager = AuthManager({"auth": {"enabled": True, "db_path": str(tmp_path / "auth.db")}})
    password = "correct horse battery staple 9"
    for name, role in (("ada", "admin"), ("otto", "operator"), ("aud", "audit")):
        manager.create_user(name, password, role=role)
    monkeypatch.setattr(gate, "auth_manager", manager)
    yield test_client, manager, password
    manager.close()


def _login(test_client, manager, username, password) -> str:
    result = manager.login(username, password)
    test_client.cookies.set("cyclaw_session", result.session_id)
    return result.csrf_token


def test_admin_session_unlocks_operator_routes_with_csrf(with_auth):
    test_client, manager, password = with_auth
    csrf = _login(test_client, manager, "ada", password)
    assert test_client.get("/soul").status_code == 200
    status = test_client.get("/console/session").json()
    assert status["via"] == "admin_session" and status["auth_enabled"] is True
    assert status["csrf"] is None
    assert test_client.post("/soul/reload").status_code == 403
    assert test_client.post("/soul/reload", headers={"X-CyClaw-CSRF": csrf}).status_code == 200


@pytest.mark.parametrize("username", ["otto", "aud"])
def test_non_admin_sessions_are_refused(with_auth, username):
    test_client, manager, password = with_auth
    csrf = _login(test_client, manager, username, password)
    assert test_client.get("/soul").status_code == 401
    assert test_client.post("/soul/reload", headers={"X-CyClaw-CSRF": csrf}).status_code == 401
    assert test_client.get("/console/session").json()["active"] is False


def test_disabled_admin_is_refused(with_auth):
    test_client, manager, password = with_auth
    manager.create_user("bea", password, role="admin")
    _login(test_client, manager, "bea", password)
    manager.disable_user("bea")
    assert test_client.get("/soul").status_code == 401


def test_admin_session_works_without_the_key(with_auth, monkeypatch):
    """A login is a credential of its own, so it does not need CYCLAW_API_KEY;
    key-based access (Bearer, console cookie) still fails closed without it."""
    test_client, manager, password = with_auth
    _login(test_client, manager, "ada", password)
    monkeypatch.delenv("CYCLAW_API_KEY")
    assert test_client.get("/soul").status_code == 200
