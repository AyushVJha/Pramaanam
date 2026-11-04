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

    def allow(self, client: str) -> bool:
        now = self._clock()
        hits = self._hits[client]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True
