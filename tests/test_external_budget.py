"""Behavioral coverage for the durable external-provider attempt ceiling."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from utils.errors import RAGError
from utils.external_budget import ExternalCallBudget


def _budget(path, *, daily=1, monthly=10):
    return ExternalCallBudget({
        "policy": {
            "external_call_limits": {
                "daily": daily,
                "monthly": monthly,
                "ledger_path": str(path),
            }
        }
    })


def test_reservation_persists_across_instances(tmp_path):
    ledger = tmp_path / "private" / "external-calls.db"
    now = datetime(2026, 10, 3, tzinfo=UTC)
    _budget(ledger).reserve(now=now)

    with pytest.raises(RAGError, match="limit reached") as denied:
        _budget(ledger).reserve(now=now)
    assert denied.value.code == "EXTERNAL_CALL_LIMIT"


def test_concurrent_instances_cannot_overrun_one_remaining_slot(tmp_path):
    ledger = tmp_path / "private" / "external-calls.db"
    now = datetime(2026, 10, 3, tzinfo=UTC)

    def reserve_once():
        try:
            _budget(ledger).reserve(now=now)
            return "reserved"
        except RAGError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _item: reserve_once(), range(2)))

    assert sorted(outcomes) == ["EXTERNAL_CALL_LIMIT", "reserved"]


def test_corrupt_ledger_fails_closed(tmp_path):
    ledger = tmp_path / "private" / "external-calls.db"
    ledger.parent.mkdir(mode=0o700)
    ledger.write_bytes(b"not sqlite")

    with pytest.raises(RAGError, match="unavailable") as denied:
        _budget(ledger).reserve(now=datetime(2026, 10, 3, tzinfo=UTC))
    assert denied.value.code == "EXTERNAL_BUDGET_UNAVAILABLE"
