"""BoundedExecutor: the real capacity bound behind /query and the auth workers.

The gate tests replace it with an AsyncMock, so these exercise the semaphore
itself. Threads are coordinated with Events, never sleeps.
"""

from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from utils.bounded_executor import BoundedExecutor, WorkCapacityExceeded


@pytest.mark.parametrize("workers", [0, -1, True, 2.0, "2"])
def test_capacity_must_be_a_positive_int(workers):
    """Zero, negatives, bools and non-ints are refused at construction."""
    with pytest.raises(ValueError, match="positive integer"):
        BoundedExecutor(workers, name="bad")


def test_full_capacity_rejects_then_frees_after_completion():
    """A call beyond capacity is refused immediately; capacity returns once the worker finishes."""
    ex = BoundedExecutor(1, name="bound")
    started, release = threading.Event(), threading.Event()

    def blocking() -> str:
        started.set()
        release.wait()
        return "first"

    async def scenario() -> list[str]:
        first = asyncio.create_task(ex.run(blocking))
        await asyncio.to_thread(started.wait)
        with pytest.raises(WorkCapacityExceeded):
            await ex.run(lambda: "refused")
        release.set()
        return [await first, await ex.run(lambda: "second")]

    try:
        assert asyncio.run(scenario()) == ["first", "second"]
    finally:
        release.set()
        ex.close()


def test_cancelled_caller_keeps_capacity_until_worker_finishes():
    """Cancelling the awaiting request does not free the slot while its worker still runs."""
    ex = BoundedExecutor(1, name="cancel")
    started, release = threading.Event(), threading.Event()

    def blocking() -> None:
        started.set()
        release.wait()

    async def scenario() -> None:
        task = asyncio.create_task(ex.run(blocking))
        await asyncio.to_thread(started.wait)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(WorkCapacityExceeded):
            await ex.run(lambda: None)

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        ex.close()


def test_failed_submit_releases_its_slot():
    """A submit that raises (executor closed) gives the slot back instead of leaking it."""
    ex = BoundedExecutor(1, name="closed")
    ex.close()

    async def scenario() -> None:
        for _ in range(2):
            # A leaked slot would turn the second attempt into WorkCapacityExceeded.
            with pytest.raises(RuntimeError):
                await ex.run(lambda: None)

    asyncio.run(scenario())


def test_worker_sees_the_callers_context():
    """Context variables set by the caller are visible inside the worker thread."""
    request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="unset")
    ex = BoundedExecutor(1, name="ctx")

    async def scenario() -> str:
        request_id.set("req-42")
        return await ex.run(request_id.get)

    try:
        assert asyncio.run(scenario()) == "req-42"
    finally:
        ex.close()
