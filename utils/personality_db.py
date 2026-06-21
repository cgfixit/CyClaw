"""Database backend shim for PersonalityManager.

Returns (conn, placeholder) where placeholder is '?' for SQLite or '%s' for Postgres.
Switch to Postgres by setting CYCLAW_DB_URL or personality.database_url in config.yaml
to a postgresql:// DSN. Default is SQLite (zero-config, local-first).
"""

import os
from pathlib import Path


def connect(db_path: Path, pers_cfg: dict):
    """Open a DB connection and return (conn, placeholder_char).

    Postgres: set CYCLAW_DB_URL=postgresql://user:pass@host/dbname
    SQLite:   default, uses db_path resolved from config.
    """
    dsn = os.environ.get("CYCLAW_DB_URL") or pers_cfg.get("database_url") or ""
    if dsn.startswith("postgresql") or dsn.startswith("postgres"):
        try:
            import psycopg  # type: ignore[import]
            from psycopg.rows import dict_row  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "psycopg is required for PostgreSQL support. "
                "Install it with: pip install 'psycopg[binary]'"
            ) from exc
        conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
        return conn, "%s", "postgres"
    # Default: SQLite (offline-first, zero-config)
    import sqlite3
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn, "?", "sqlite"


def ddl_soul_versions(backend: str) -> str:
    if backend == "postgres":
        return """
            CREATE TABLE IF NOT EXISTS soul_versions (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                sha256 TEXT NOT NULL,
                content TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL
            )
        """
    return """
        CREATE TABLE IF NOT EXISTS soul_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sha256 TEXT NOT NULL,
            content TEXT NOT NULL,
            reason TEXT,
            timestamp TEXT NOT NULL
        )
    """


def ddl_interactions(backend: str) -> str:
    if backend == "postgres":
        return """
            CREATE TABLE IF NOT EXISTS interactions (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                query_hash TEXT NOT NULL,
                outcome TEXT,
                timestamp TEXT NOT NULL
            )
        """
    return """
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_hash TEXT NOT NULL,
            outcome TEXT,
            timestamp TEXT NOT NULL
        )
    """
