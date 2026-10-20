"""Stage 6: roles, last-admin protection, and role-column migration."""

from __future__ import annotations

import sqlite3

import pytest

from utils import authn, authn_store
from utils.authn_manager import AuthManager, BOOTSTRAP_USERNAME
from utils.errors import AuthLastAdmin

_GOOD = "correct horse battery staple"


@pytest.fixture
def manager(tmp_path):
    m = AuthManager({"auth": {"enabled": True, "db_path": str(tmp_path / "auth.db")}})
    yield m
    m.close()


def test_validate_role_rejects_unknown():
    with pytest.raises(authn.PasswordPolicyError):
        authn.validate_role("superuser")
    assert authn.validate_role("Admin") == "admin"


def test_bootstrap_admin_has_admin_role(manager):
    assert manager.bootstrap_if_empty() is True
    user = manager.get_user(BOOTSTRAP_USERNAME)
    assert user is not None
    assert user.role == "admin"


def test_create_user_default_role_is_operator(manager):
    manager.create_user("alice", _GOOD)
    assert manager.get_user("alice").role == "operator"


def test_create_user_role_validated(manager):
    with pytest.raises(authn.PasswordPolicyError):
        manager.create_user("alice", _GOOD, role="root")


def test_last_admin_cannot_be_deleted_disabled_or_demoted(manager):
    manager.bootstrap_if_empty()
    with pytest.raises(AuthLastAdmin):
        manager.delete_user(BOOTSTRAP_USERNAME)
    with pytest.raises(AuthLastAdmin):
        manager.disable_user(BOOTSTRAP_USERNAME)
    with pytest.raises(AuthLastAdmin):
        manager.set_role(BOOTSTRAP_USERNAME, "operator")


def test_second_admin_allows_demoting_the_first(manager):
    manager.bootstrap_if_empty()
    manager.create_user("other", _GOOD, role="admin")
    manager.set_role(BOOTSTRAP_USERNAME, "operator")
    assert manager.get_user(BOOTSTRAP_USERNAME).role == "operator"


@pytest.mark.parametrize("role", ["operator", "audit"])
@pytest.mark.parametrize("recreate", [False, True], ids=["demoted", "recreated"])
def test_reopening_preserves_bootstrap_username_role(manager, role, recreate):
    manager.bootstrap_if_empty()
    manager.create_user("other", _GOOD, role="admin")
    if recreate:
        manager.delete_user(BOOTSTRAP_USERNAME)
        manager.create_user(BOOTSTRAP_USERNAME, _GOOD, role=role)
    else:
        manager.set_role(BOOTSTRAP_USERNAME, role)

    reopened = AuthManager(manager.cfg)
    try:
        assert reopened.get_user(BOOTSTRAP_USERNAME).role == role
        assert manager.get_user(BOOTSTRAP_USERNAME).role == role
        with pytest.raises(AuthLastAdmin):
            reopened.set_role("other", "operator")
    finally:
        reopened.close()


def test_last_admin_guard_lives_in_the_sql(manager):
    """PR #940 review (check-then-act race): the guard must hold even when the
    Python pre-check is bypassed entirely -- raw SQL through the manager's own
    connection cannot demote, disable, or delete the last enabled admin."""
    manager.bootstrap_if_empty()
    cur = manager.conn.execute(
        manager._sql_set_role, ("operator", BOOTSTRAP_USERNAME, "operator")
    )
    assert cur.rowcount == 0
    cur = manager.conn.execute(manager._sql_disable_user, (BOOTSTRAP_USERNAME,))
    assert cur.rowcount == 0
    cur = manager.conn.execute(manager._sql_delete_user, (BOOTSTRAP_USERNAME,))
    assert cur.rowcount == 0
    manager.conn.rollback()
    user = manager.get_user(BOOTSTRAP_USERNAME)
    assert user.role == "admin"
    assert user.disabled is False


def test_last_admin_guard_holds_across_connections(tmp_path):
    """A second AuthManager (the `cyclaw-user` CLI process model: separate
    connection, separate lock) must still be refused."""
    cfg = {"auth": {"enabled": True, "db_path": str(tmp_path / "auth.db")}}
    first = AuthManager(cfg)
    second = AuthManager(cfg)
    try:
        first.bootstrap_if_empty()
        first.create_user("other", _GOOD, role="admin")
        first.set_role(BOOTSTRAP_USERNAME, "operator")
        with pytest.raises(AuthLastAdmin):
            second.set_role("other", "operator")
        with pytest.raises(AuthLastAdmin):
            second.disable_user("other")
        with pytest.raises(AuthLastAdmin):
            second.delete_user("other")
    finally:
        first.close()
        second.close()


def test_delete_user_removes_row(manager):
    manager.create_user("alice", _GOOD)
    manager.delete_user("alice")
    assert manager.get_user("alice") is None


@pytest.mark.parametrize("interrupt", [False, True], ids=["normal", "interrupted"])
def test_migration_adds_role_and_promotes_bootstrap(tmp_path, monkeypatch, interrupt):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            created_ts REAL NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0,
            last_login_ts REAL,
            failed_count INTEGER NOT NULL DEFAULT 0,
            locked_until_ts REAL
        )
        """
    )
    conn.execute(
        "INSERT INTO users (username, password_hash, created_ts, disabled, failed_count) "
        "VALUES ('admin', 'placeholder', 1, 0, 0)"
    )
    conn.execute(
        "INSERT INTO users (username, password_hash, created_ts, disabled, failed_count) "
        "VALUES ('alice', 'placeholder', 1, 0, 0)"
    )
    conn.commit()
    conn.close()

    if interrupt:
        migrate_revision = authn_store.ensure_credential_revision_column

        def fail_after_migrations(conn, backend):
            migrate_revision(conn, backend)
            raise RuntimeError("interrupted before bootstrap promotion")

        with monkeypatch.context() as patch:
            patch.setattr(authn_store, "ensure_credential_revision_column", fail_after_migrations)
            with pytest.raises(RuntimeError, match="interrupted"):
                AuthManager({"auth": {"enabled": True, "db_path": str(db)}})

    manager = AuthManager({"auth": {"enabled": True, "db_path": str(db)}})
    try:
        assert manager.get_user("admin").role == "admin"
        assert manager.get_user("alice").role == "operator"
        names = authn_store.users_column_names(manager.conn, manager.backend)
        assert "role" in {n.lower() for n in names}
        manager.set_role("alice", "admin")
        manager.set_role("admin", "operator")
    finally:
        manager.close()

    reopened = AuthManager({"auth": {"enabled": True, "db_path": str(db)}})
    try:
        assert reopened.get_user("admin").role == "operator"
        assert reopened.get_user("alice").role == "admin"
    finally:
        reopened.close()
