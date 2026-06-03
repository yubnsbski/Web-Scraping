"""Domain-scoped rate limiting for data ingestion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic, sleep
from urllib.parse import urlparse

Clock = Callable[[], float]
Sleeper = Callable[[float], None]


@dataclass
class DomainRateLimiter:
    """Enforce a minimum interval between requests to the same host."""

    min_interval_seconds: float = 1.0
    clock: Clock = monotonic
    sleeper: Sleeper = sleep
    _last_request_at: dict[str, float] = field(default_factory=dict)

    def wait_for_url(self, url: str) -> float:
        """Wait if needed and return the requested wait duration."""

        host = urlparse(url).netloc.lower()
        if not host or self.min_interval_seconds <= 0:
            return 0.0

        now = self.clock()
        previous = self._last_request_at.get(host)
        wait_seconds = 0.0
        if previous is not None:
            elapsed = now - previous
            wait_seconds = max(0.0, self.min_interval_seconds - elapsed)
            if wait_seconds > 0:
                self.sleeper(wait_seconds)
                now = self.clock()
        self._last_request_at[host] = now
        return wait_seconds
