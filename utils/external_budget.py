"""Durable UTC attempt ceilings shared by both paid model transports."""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from utils.errors import RAGError


class ExternalCallBudget:
    def __init__(self, cfg: dict):
        limits = cfg.get("policy", {}).get("external_call_limits", {})
        if not isinstance(limits, dict):
            raise ValueError("policy.external_call_limits must be a mapping")
        self.daily = limits.get("daily", 100)
        self.monthly = limits.get("monthly", 1000)
        for name, value in (("daily", self.daily), ("monthly", self.monthly)):
            if type(value) is not int or value < 0:
                raise ValueError(f"policy.external_call_limits.{name} must be a nonnegative integer")
        raw_path = limits.get("ledger_path", "data/budget/external-calls.db")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("policy.external_call_limits.ledger_path must name a persistent file")
        path = Path(raw_path).expanduser()
        self.path = path if path.is_absolute() else Path(__file__).resolve().parent.parent / path

    def reserve(self, *, now: datetime | None = None) -> None:
        """Charge before one POST, including retries. Failed attempts are not refunded."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            parent = self.path.parent.lstat()
            if not stat.S_ISDIR(parent.st_mode):
                raise OSError("External budget directory must not be a symlink")
            if os.name != "nt" and (parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077):
                raise OSError("External budget directory must be private and owned by the current user")
            fd = os.open(
                self.path,
                os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                0o600,
            )
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise OSError("External budget ledger must be a regular file")
                if os.name != "nt":
                    os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            with closing(sqlite3.connect(self.path, timeout=2.0)) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS attempts "
                    "(period TEXT PRIMARY KEY, count INTEGER NOT NULL CHECK (count >= 0))"
                )
                instant = datetime.now(UTC) if now is None else now.astimezone(UTC)
                day = f"day:{instant:%Y-%m-%d}"
                month = f"month:{instant:%Y-%m}"
                counts = dict(conn.execute("SELECT period, count FROM attempts WHERE period IN (?, ?)", (day, month)))
                if counts.get(day, 0) >= self.daily or counts.get(month, 0) >= self.monthly:
                    raise RAGError(
                        "External call limit reached; wait for the UTC budget window to reset",
                        code="EXTERNAL_CALL_LIMIT",
                    )
                conn.executemany(
                    "INSERT INTO attempts(period, count) VALUES (?, 1) "
                    "ON CONFLICT(period) DO UPDATE SET count = count + 1",
                    ((day,), (month,)),
                )
        except (OSError, sqlite3.Error) as exc:
            raise RAGError(
                "External call budget is unavailable; no provider request was sent",
                code="EXTERNAL_BUDGET_UNAVAILABLE",
            ) from exc
