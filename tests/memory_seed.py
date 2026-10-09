"""Test-only fact writers that skip propose/apply.

Production writes facts only through ``memory.store.apply_proposal``, which
requires a reason and runs the enforced injection scan. Tests still need to
seed or mutate rows directly, so these wrap the same ``*_conn`` primitives
apply_proposal uses, one committed transaction per call. Not ``test_*``-named,
so pytest does not collect it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from memory.models import Fact
from memory.store import (
    _deactivate_fact_conn,
    _insert_fact_conn,
    _update_fact_conn,
    _write_lock,
    connect,
)


def _commit(cfg: Mapping[str, Any], write: Callable[..., Fact], *args: Any, **kwargs: Any) -> Fact:
    with _write_lock:
        conn = connect(cfg)
        try:
            fact = write(conn, *args, **kwargs)
            conn.commit()
            return fact
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def insert_fact(cfg: Mapping[str, Any], content: str, **kwargs: Any) -> Fact:
    return _commit(cfg, _insert_fact_conn, cfg, content, **kwargs)


def update_fact(cfg: Mapping[str, Any], fact_id: int, **kwargs: Any) -> Fact:
    return _commit(cfg, _update_fact_conn, cfg, fact_id, **kwargs)


def deactivate_fact(cfg: Mapping[str, Any], fact_id: int, *, reason: str = "") -> Fact:
    return _commit(cfg, _deactivate_fact_conn, fact_id, reason=reason)
