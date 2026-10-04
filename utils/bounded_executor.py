"""Bound blocking work until its worker finishes, even after the caller leaves."""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class WorkCapacityExceeded(Exception):
    pass


class BoundedExecutor:
    def __init__(self, workers: int, *, name: str) -> None:
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise ValueError("worker capacity must be a positive integer")
        self._capacity = threading.BoundedSemaphore(workers)
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)

    async def run(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
        if not self._capacity.acquire(blocking=False):
            raise WorkCapacityExceeded("worker capacity is exhausted")
        context = contextvars.copy_context()
        try:
            future: Future[T] = self._executor.submit(context.run, fn, *args, **kwargs)
        except BaseException:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _: self._capacity.release())
        # Cancellation ends the HTTP wait, while the worker still owns capacity.
        return await asyncio.shield(asyncio.wrap_future(future))

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
