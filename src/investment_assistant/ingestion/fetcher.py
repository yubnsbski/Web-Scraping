"""Safe HTTP fetch orchestration with robots, rate limits, and cache."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from investment_assistant.ingestion.http_cache import HttpCache
from investment_assistant.ingestion.rate_limit import DomainRateLimiter
from investment_assistant.ingestion.robots import RobotsChecker
from investment_assistant.ingestion.transport import (
    HttpResponse,
    HttpTransport,
    UrlLibHttpTransport,
)

DEFAULT_USER_AGENT = "investment-assistant/0.1 (+safe-ingestion; contact: local-user)"
DEFAULT_HTTP_CACHE_PATH = Path(".cache/investment_assistant/http_cache.sqlite")


@dataclass(frozen=True)
class FetchResult:
    """CLI-friendly fetch result metadata."""

    url: str
    status_code: int | None
    source: str
    allowed_by_robots: bool
    robots_url: str
    bytes_read: int
    content_type: str | None
    text_preview: str | None
    dry_run: bool


class SafeFetcher:
    """Fetch URLs through robots checks, cache, and rate limiting."""

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        cache: HttpCache | None = None,
        rate_limiter: DomainRateLimiter | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.transport = transport or UrlLibHttpTransport()
        self.cache = cache or HttpCache(DEFAULT_HTTP_CACHE_PATH)
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.robots = RobotsChecker(
            self.transport,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
        )

    def fetch(self, url: str, *, dry_run: bool = False, preview_chars: int = 500) -> FetchResult:
        """Fetch a URL unless dry-run is requested or robots.txt blocks it."""

        decision = self.robots.can_fetch(url)
        if not decision.allowed:
            return FetchResult(
                url=url,
                status_code=None,
                source=decision.reason,
                allowed_by_robots=False,
                robots_url=decision.robots_url,
                bytes_read=0,
                content_type=None,
                text_preview=None,
                dry_run=dry_run,
            )
        if dry_run:
            return FetchResult(
                url=url,
                status_code=None,
                source="dry_run",
                allowed_by_robots=True,
                robots_url=decision.robots_url,
                bytes_read=0,
                content_type=None,
                text_preview=None,
                dry_run=True,
            )

        cached = self.cache.get(url)
        if cached is not None:
            headers = json.loads(cached.headers_json)
            return _result_from_response(
                url=url,
                response=HttpResponse(
                    url=cached.url,
                    status_code=cached.status_code,
                    headers={str(key): str(value) for key, value in headers.items()},
                    body=cached.body,
                ),
                source="cache",
                robots_url=decision.robots_url,
                preview_chars=preview_chars,
            )

        self.rate_limiter.wait_for_url(url)
        response = self.transport.get(
            url,
            timeout_seconds=self.timeout_seconds,
            user_agent=self.user_agent,
        )
        self.cache.set(
            url=url,
            status_code=response.status_code,
            headers_json=json.dumps(response.headers, sort_keys=True),
            body=response.body,
        )
        return _result_from_response(
            url=url,
            response=response,
            source="network",
            robots_url=decision.robots_url,
            preview_chars=preview_chars,
        )


def _result_from_response(
    *,
    url: str,
    response: HttpResponse,
    source: str,
    robots_url: str,
    preview_chars: int,
) -> FetchResult:
    content_type = _header_value(response.headers, "content-type")
    preview = response.body[: max(0, preview_chars)].decode("utf-8", errors="replace")
    return FetchResult(
        url=url,
        status_code=response.status_code,
        source=source,
        allowed_by_robots=True,
        robots_url=robots_url,
        bytes_read=len(response.body),
        content_type=content_type,
        text_preview=preview,
        dry_run=False,
    )


def _header_value(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None
