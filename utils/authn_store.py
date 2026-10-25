"""Database backend for per-user authentication (docs/AUTHENTICATION_DESIGN.md).

Stores ``users``, ``sessions`` and ``device_tokens``. Mirrors
``utils/personality_db.py``'s ``connect()`` pattern deliberately: same SQLite
0600-hardening, same hardened Postgres conninfo (TLS, timeouts, application
name), same "no new storage technology" constraint.

One deliberate deviation from that mirror: Postgres opt-in uses its OWN env
var (``CYCLAW_AUTH_DB_URL``), not the shared ``CYCLAW_DB_URL`` personality
uses. ``gate.py``'s rate limiter already established this precedent
(``RATE_LIMIT_DB_URL`` does not fall back to ``CYCLAW_DB_URL`` either) for
the same reason it applies more sharply here: auth data (password hashes,
session ids, device-token hashes) is higher-sensitivity than personality
data, and a shared env var would silently comingle the two into whatever
database an operator pointed ``CYCLAW_DB_URL`` at for a different subsystem.
Each subsystem's Postgres backend is opted into independently.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# The opener is intentionally reused rather than re-implemented: the Postgres
# hardening rules (TLS default, connect_timeout, statement_timeout,
# application_name, never-log-the-DSN) and the owner-only SQLite file mode
# apply identically to every store this codebase opens, and a second copy
# would let the two drift (they already had, in comments only).
from utils.personality_db import open_db

_AUTH_DB_ENV = "CYCLAW_AUTH_DB_URL"


def connect(db_path: Path, auth_cfg: dict) -> tuple[Any, str, str]:
    """Open a DB connection and return ``(conn, placeholder_char, backend_name)``.

    Postgres: set ``auth.database_url`` in config.yaml or the
    ``CYCLAW_AUTH_DB_URL`` env var to a ``postgresql://`` DSN.
    SQLite: default, uses ``db_path``.

    The opener itself (psycopg hardening, owner-only 0600 SQLite file,
    chmod-failure-is-a-warning) is ``utils.personality_db.open_db`` so the
    auth store and the soul store can never drift apart on it; only the DSN
    precedence (config first, then the env var) is this module's own.
    """
    from utils.config_validation import validate_database_url_no_password
    validate_database_url_no_password(auth_cfg.get("database_url"), "auth.database_url")
    dsn = auth_cfg.get("database_url") or os.environ.get(_AUTH_DB_ENV) or ""
    return open_db(db_path, dsn, "auth")


def ddl_users() -> str:
    return """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            created_ts REAL NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0,
            last_login_ts REAL,
            failed_count INTEGER NOT NULL DEFAULT 0,
            locked_until_ts REAL,
            role TEXT NOT NULL DEFAULT 'operator',
            credential_revision INTEGER NOT NULL DEFAULT 0
        )
    """


def ddl_sessions() -> str:
    return """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            csrf_token TEXT NOT NULL,
            created_ts REAL NOT NULL,
            last_seen_ts REAL NOT NULL,
            expires_ts REAL NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0
        )
    """


def ddl_device_tokens() -> str:
    return """
        CREATE TABLE IF NOT EXISTS device_tokens (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            label TEXT NOT NULL,
            created_ts REAL NOT NULL,
            last_used_ts REAL,
            revoked INTEGER NOT NULL DEFAULT 0
        )
    """


def ddl_indexes() -> list[str]:
    """Index DDL applied after the tables exist. Valid on both backends."""
    return [
        "CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username)",
        "CREATE INDEX IF NOT EXISTS idx_device_tokens_username ON device_tokens(username)",
        # A label is the only handle `cyclaw-user token revoke` has, and it
        # matches on (username, label) -- so two LIVE tokens sharing a label
        # would both die on one revoke, with no way to target either. This
        # makes that unrepresentable at the storage layer, which the
        # application-level check in AuthManager.create_device_token cannot do
        # alone: the server and the CLI are separate processes holding
        # separate connections to the same file, so an in-process lock does
        # not order them. PARTIAL (WHERE revoked = 0) so a label becomes
        # reusable once its token is revoked -- the constraint is on live
        # tokens, not on history. Partial unique indexes are supported by both
        # backends this module targets (SQLite 3.8+, Postgres).
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_tokens_live_label "
        + "ON device_tokens(username, label) WHERE revoked = 0",
    ]


def users_column_names(conn: object, backend: str) -> set[str]:
    """Column names on ``users`` (SQLite PRAGMA or Postgres information_schema)."""
    if backend == "postgres":
        rows = conn.execute(  # type: ignore[union-attr]
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'users'"
        ).fetchall()
        return {str(r["column_name"]) for r in rows}
    rows = conn.execute("PRAGMA table_info(users)").fetchall()  # type: ignore[union-attr]
    return {str(r["name"]) for r in rows}


def ensure_users_role_column(conn: object, backend: str) -> bool:
    """Add ``role`` for a pre-Stage-6 database; return whether it was added."""
    names = {n.lower() for n in users_column_names(conn, backend)}
    if "role" in names:
        return False
    conn.execute(  # type: ignore[union-attr]
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'operator'"
    )
    return True


def ensure_credential_revision_column(conn: object, backend: str) -> None:
    if "credential_revision" not in users_column_names(conn, backend):
        conn.execute(  # type: ignore[union-attr]
            "ALTER TABLE users ADD COLUMN credential_revision INTEGER NOT NULL DEFAULT 0"
        )
