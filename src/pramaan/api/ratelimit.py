"""A tiny per-client rate limiter (sliding window, in memory). (deploy)

Stops one visitor from hogging a small free host. Limits: it is per process (restart resets it)
and keys on X-Forwarded-For when present, which a client can fake if the host does not overwrite
it. It is a speed bump, not security.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self, max_requests: int, window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    MAX_CLIENTS = 10_000  # distinct (possibly faked) client names remembered at once

    def allow(self, client: str) -> bool:
        now = self._clock()
        if len(self._hits) >= self.MAX_CLIENTS and client not in self._hits:
            self._forget_idle(now)  # a flood of fake X-Forwarded-For values must not grow memory
        hits = self._hits[client]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True

    def _forget_idle(self, now: float) -> None:
        for name in [n for n, h in self._hits.items() if not h or now - h[-1] >= self.window]:
            del self._hits[name]
        if len(self._hits) >= self.MAX_CLIENTS:  # all still active: drop the oldest half
            oldest = sorted(self._hits, key=lambda n: self._hits[n][-1])[: self.MAX_CLIENTS // 2]
            for name in oldest:
                del self._hits[name]
