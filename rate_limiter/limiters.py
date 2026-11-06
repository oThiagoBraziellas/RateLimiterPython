"""Rate limiting algorithms.

Both limiters expose ``allow(cost=1)`` returning a :class:`Decision` and share
the same constructor convention: an injectable ``clock`` (seconds, monotonic).
"""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Hashable

Clock = Callable[[], float]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: float
    retry_after: float  # seconds until the same request would succeed; 0 if allowed

    def __bool__(self) -> bool:
        return self.allowed


class TokenBucket:
    """Classic token bucket.

    The bucket holds up to ``capacity`` tokens and refills continuously at
    ``refill_rate`` tokens per second. Tokens are computed lazily from the
    elapsed time on every call, so no background thread is needed. Allows
    bursts up to ``capacity`` while enforcing ``refill_rate`` on average.
    """

    def __init__(self, capacity: float, refill_rate: float, clock: Clock = time.monotonic):
        if capacity <= 0 or refill_rate <= 0:
            raise ValueError("capacity and refill_rate must be positive")
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last = now

    def allow(self, cost: float = 1) -> Decision:
        if cost <= 0:
            raise ValueError("cost must be positive")
        with self._lock:
            self._refill()
            if cost > self.capacity:
                return Decision(False, self._tokens, math.inf)
            if self._tokens >= cost:
                self._tokens -= cost
                return Decision(True, self._tokens, 0.0)
            return Decision(False, self._tokens, (cost - self._tokens) / self.refill_rate)

    @property
    def tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class SlidingWindowLog:
    """Exact sliding window: at most ``limit`` requests in any ``window`` seconds.

    Stores one timestamp per accepted request, so memory is O(limit) per key.
    There is no boundary burst problem of fixed windows, at the price of that
    memory.
    """

    def __init__(self, limit: int, window: float, clock: Clock = time.monotonic):
        if limit <= 0 or window <= 0:
            raise ValueError("limit and window must be positive")
        self.limit = int(limit)
        self.window = float(window)
        self._clock = clock
        self._log: Deque[float] = deque()
        self._lock = threading.Lock()

    def _evict(self, now: float) -> None:
        cutoff = now - self.window
        while self._log and self._log[0] <= cutoff:
            self._log.popleft()

    def allow(self, cost: int = 1) -> Decision:
        if cost <= 0 or int(cost) != cost:
            raise ValueError("cost must be a positive integer")
        with self._lock:
            now = self._clock()
            self._evict(now)
            if cost > self.limit:
                return Decision(False, self.limit - len(self._log), math.inf)
            if len(self._log) + cost <= self.limit:
                self._log.extend([now] * cost)
                return Decision(True, self.limit - len(self._log), 0.0)
            # The request fits once enough old entries leave the window.
            needed = len(self._log) + cost - self.limit
            oldest_to_leave = self._log[needed - 1]
            return Decision(False, self.limit - len(self._log), oldest_to_leave + self.window - now)

    @property
    def count(self) -> int:
        with self._lock:
            self._evict(self._clock())
            return len(self._log)


class KeyedLimiter:
    """One independent limiter per key (user id, IP address, API key...).

    ``factory`` builds a limiter for a new key. Idle keys can be dropped with
    :meth:`prune` to bound memory.
    """

    def __init__(self, factory: Callable[[], object]):
        self._factory = factory
        self._limiters: Dict[Hashable, object] = {}
        self._lock = threading.Lock()

    def allow(self, key: Hashable, cost: int = 1) -> Decision:
        with self._lock:
            limiter = self._limiters.get(key)
            if limiter is None:
                limiter = self._limiters[key] = self._factory()
        return limiter.allow(cost)

    def prune(self, predicate: Callable[[object], bool]) -> int:
        """Remove keys whose limiter satisfies ``predicate``; returns how many."""
        with self._lock:
            dead = [k for k, lim in self._limiters.items() if predicate(lim)]
            for k in dead:
                del self._limiters[k]
            return len(dead)

    def __len__(self) -> int:
        with self._lock:
            return len(self._limiters)
