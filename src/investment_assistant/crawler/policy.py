"""Crawl guardrails (Phase 1): domain/prefix locks, visited set, and limits.

This module performs no network I/O. It decides, for a given URL and crawl
depth, whether the crawler is allowed to fetch it, and tracks global stop
conditions (max pages / max elapsed time).

Fetching, robots.txt checks, and rate limiting are handled by the existing
ingestion layer (:mod:`investment_assistant.ingestion`). This policy is the
*structural* boundary that makes domain/prefix escapes impossible regardless of
what links a page happens to contain: a link to ``/recruit/`` or an external
host is rejected here before it can ever reach the fetcher.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlparse, urlunparse

Clock = Callable[[], float]

DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_PAGES = 20

# Per-URL decision reasons.
REASON_ALLOWED = "allowed"
REASON_BLOCKED_SCHEME = "blocked_scheme"
REASON_OUTSIDE_DOMAINS = "outside_allowed_domains"
REASON_OUTSIDE_PREFIX = "outside_url_prefix"
REASON_ALREADY_VISITED = "already_visited"
REASON_DEPTH_EXCEEDED = "max_depth_exceeded"

# Global stop reasons.
STOP_MAX_PAGES = "max_pages_reached"
STOP_MAX_ELAPSED = "max_elapsed_seconds_reached"


@dataclass(frozen=True)
class CrawlLimits:
    """Hard ceilings that physically stop a crawl from running away."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_pages: int = DEFAULT_MAX_PAGES
    max_elapsed_seconds: float | None = None


@dataclass(frozen=True)
class UrlDecision:
    """Result of evaluating a single URL against the guardrails."""

    url: str
    allowed: bool
    reason: str


class CrawlPolicy:
    """Structural guardrails for a single crawl run.

    The policy locks a crawl to an explicit set of hostnames and a URL prefix,
    de-duplicates visited URLs, and enforces depth/page/time ceilings. It never
    touches the network; callers fetch through the ingestion layer only after a
    URL is ``allowed`` here.
    """

    def __init__(
        self,
        *,
        allowed_domains: Iterable[str],
        url_prefix: str = "",
        limits: CrawlLimits | None = None,
        clock: Clock = monotonic,
    ) -> None:
        self.allowed_domains: frozenset[str] = frozenset(
            domain.strip().lower() for domain in allowed_domains if domain and domain.strip()
        )
        if not self.allowed_domains:
            raise ValueError("allowed_domains must not be empty")
        self.url_prefix = self.normalize_url(url_prefix) if url_prefix.strip() else ""
        self.limits = limits or CrawlLimits()
        self._clock = clock
        self._visited: set[str] = set()
        self._pages_fetched = 0
        self._started_at: float | None = None

    @classmethod
    def from_registry_source(
        cls,
        source: Mapping[str, object],
        *,
        clock: Clock = monotonic,
    ) -> CrawlPolicy:
        """Build a policy from a crawl-enabled source registry entry.

        Honors the registry fields described in the design note: ``url`` (start),
        ``url_prefix`` (prefix lock, defaults to ``url``), ``allowed_domains``
        (defaults to the start URL host), and the ``max_depth`` / ``max_pages`` /
        ``max_elapsed_seconds`` ceilings.
        """

        start_url = str(source.get("url") or "").strip()
        prefix = str(source.get("url_prefix") or "").strip() or start_url

        raw_domains = source.get("allowed_domains")
        if isinstance(raw_domains, str):
            domains: list[str] = [raw_domains]
        elif isinstance(raw_domains, Iterable):
            domains = [str(item) for item in raw_domains]
        else:
            domains = []
        if not domains:
            host = urlparse(prefix or start_url).hostname
            domains = [host] if host else []

        limits = CrawlLimits(
            max_depth=_int_or_default(source.get("max_depth"), DEFAULT_MAX_DEPTH),
            max_pages=_int_or_default(source.get("max_pages"), DEFAULT_MAX_PAGES),
            max_elapsed_seconds=_optional_float(source.get("max_elapsed_seconds")),
        )
        return cls(allowed_domains=domains, url_prefix=prefix, limits=limits, clock=clock)

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize a URL for comparison: lowercase scheme/host, drop fragment."""

        parsed = urlparse(url.strip())
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                parsed.params,
                parsed.query,
                "",
            )
        )

    def evaluate_url(self, url: str, *, depth: int) -> UrlDecision:
        """Decide whether ``url`` at ``depth`` may be fetched.

        Checks run cheapest-and-most-structural first: scheme, depth, domain
        lock, prefix lock, then the visited set.
        """

        normalized = self.normalize_url(url)
        parsed = urlparse(normalized)

        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return UrlDecision(normalized, False, REASON_BLOCKED_SCHEME)
        if depth > self.limits.max_depth:
            return UrlDecision(normalized, False, REASON_DEPTH_EXCEEDED)
        if parsed.hostname not in self.allowed_domains:
            return UrlDecision(normalized, False, REASON_OUTSIDE_DOMAINS)
        if self.url_prefix and not normalized.startswith(self.url_prefix):
            return UrlDecision(normalized, False, REASON_OUTSIDE_PREFIX)
        if normalized in self._visited:
            return UrlDecision(normalized, False, REASON_ALREADY_VISITED)
        return UrlDecision(normalized, True, REASON_ALLOWED)

    def mark_visited(self, url: str) -> None:
        """Record a URL as seen so it is not enqueued or fetched again."""

        self._visited.add(self.normalize_url(url))

    def register_fetch(self, url: str) -> None:
        """Account for a fetched page: start the clock, mark visited, count it."""

        if self._started_at is None:
            self._started_at = self._clock()
        self.mark_visited(url)
        self._pages_fetched += 1

    @property
    def pages_fetched(self) -> int:
        return self._pages_fetched

    def is_visited(self, url: str) -> bool:
        return self.normalize_url(url) in self._visited

    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return self._clock() - self._started_at

    def stop_reason(self) -> str | None:
        """Return the global stop reason if a ceiling is reached, else ``None``."""

        if self._pages_fetched >= self.limits.max_pages:
            return STOP_MAX_PAGES
        max_elapsed = self.limits.max_elapsed_seconds
        if (
            max_elapsed is not None
            and self._started_at is not None
            and self.elapsed_seconds() >= max_elapsed
        ):
            return STOP_MAX_ELAPSED
        return None

    def can_fetch_more(self) -> bool:
        """Whether the crawl may still fetch another page under the ceilings."""

        return self.stop_reason() is None


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
