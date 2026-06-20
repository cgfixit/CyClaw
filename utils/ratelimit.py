"""Thread-safe in-memory per-IP rate limiter.

Extracted from ``gate.py`` so the limiter is a single importable unit shared
by the FastAPI gateway and its tests (no duplicated logic that can silently
drift apart).

The gateway calls ``allow()`` from FastAPI's threadpool (via
``asyncio.to_thread``), so concurrent requests for the same IP execute on
different threads. The per-IP timestamp map is therefore mutated under a single
``threading.Lock``: every read-modify-write — including the idle-IP sweep — is
guarded, so two requests cannot interleave and overcount past the limit.

Behavior preserved from the original ``gate.py`` implementation:
  * 60 requests / 60-second sliding window per client IP (configurable here).
  * Idle-IP eviction so the map cannot grow without bound (an entry whose
    timestamps are all older than the window can never block a future request,
    so it is safe to drop). The sweep runs at most once per window to keep the
    common path cheap.

The clock is injectable (``clock`` parameter) so tests can drive window expiry
and eviction deterministically without ``time.sleep``.
"""

import threading
import time
from collections import defaultdict
from typing import Callable, Dict, List


class RateLimiter:
    """Fixed-window-ish sliding rate limiter, safe under concurrent threads."""

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: float = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: Dict[str, List[float]] = defaultdict(list)
        self._last_sweep = 0.0
        self._lock = threading.Lock()

    def _sweep(self, now: float) -> None:
        """Evict clients whose timestamps are all outside the window.

        Caller must hold ``self._lock``. Runs at most once per window so the
        hot path stays cheap.
        """
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now
        stale = [
            ip for ip, hits in self._hits.items()
            if all(now - t >= self.window_seconds for t in hits)
        ]
        for ip in stale:
            del self._hits[ip]

    def allow(self, client_ip: str) -> bool:
        """Return True if the request is within the limit, else False.

        The entire read-modify-write is performed under the lock so concurrent
        requests for one IP cannot both observe ``len(recent) < max`` and both
        append (the interleave that would overcount past the limit).
        """
        now = self._clock()
        with self._lock:
            self._sweep(now)
            recent = [t for t in self._hits[client_ip] if now - t < self.window_seconds]
            if len(recent) >= self.max_requests:
                self._hits[client_ip] = recent
                return False
            recent.append(now)
            self._hits[client_ip] = recent
            return True

    def tracked_ips(self) -> int:
        """Number of IPs currently held in the map (for eviction tests/metrics)."""
        with self._lock:
            return len(self._hits)
