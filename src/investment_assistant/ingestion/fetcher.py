"""Safe HTTP fetch orchestration with robots, rate limits, and cache."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.ingestion.encoding import decode_body
from investment_assistant.ingestion.html_extract import extract_text_from_html
from investment_assistant.ingestion.http_cache import HttpCache
from investment_assistant.ingestion.rate_limit import DomainRateLimiter
from investment_assistant.ingestion.robots import RobotsChecker
from investment_assistant.ingestion.transport import (
    HttpResponse,
    HttpTransport,
    UrlLibHttpTransport,
)
from investment_assistant.observability import get_logger

_logger = get_logger("ingestion.fetcher")

DEFAULT_USER_AGENT = "investment-assistant/0.1 (+safe-ingestion; contact: local-user)"
USER_AGENT_ENV_VAR = "INVESTMENT_ASSISTANT_USER_AGENT"
DEFAULT_HTTP_CACHE_PATH = Path(".cache/investment_assistant/http_cache.sqlite")


def _default_user_agent() -> str:
    """Return the configured ingestion User-Agent, overridable via env var."""

    return os.getenv(USER_AGENT_ENV_VAR, "").strip() or DEFAULT_USER_AGENT


@dataclass(frozen=True)
class FetchedDocument:
    """Full-body fetch result used by the crawler for link extraction."""

    url: str
    status_code: int | None
    allowed_by_robots: bool
    html: str
    source: str


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
    saved_path: str | None = None
    extracted_text: bool = False
    metadata_included: bool = False


class SafeFetcher:
    """Fetch URLs through robots checks, cache, and rate limiting."""

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        cache: HttpCache | None = None,
        rate_limiter: DomainRateLimiter | None = None,
        user_agent: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.transport = transport or UrlLibHttpTransport()
        self.cache = cache or HttpCache(DEFAULT_HTTP_CACHE_PATH)
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.user_agent = user_agent or _default_user_agent()
        self.timeout_seconds = timeout_seconds
        self.robots = RobotsChecker(
            self.transport,
            user_agent=self.user_agent,
            timeout_seconds=timeout_seconds,
        )

    def fetch(
        self,
        url: str,
        *,
        dry_run: bool = False,
        preview_chars: int = 500,
        save_text: str | Path | None = None,
        extract_text: bool = False,
        include_metadata: bool = False,
    ) -> FetchResult:
        """Fetch a URL unless dry-run is requested or robots.txt blocks it."""

        decision = self.robots.can_fetch(url)
        if not decision.allowed:
            _logger.info("fetch blocked url_host=%s reason=%s", _host(url), decision.reason)
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
                save_text=save_text,
                extract_text=extract_text,
                include_metadata=include_metadata,
            )

        self.rate_limiter.wait_for_url(url)
        response = self.transport.get(
            url,
            timeout_seconds=self.timeout_seconds,
            user_agent=self.user_agent,
        )
        _logger.info(
            "fetch ok url_host=%s status=%s bytes=%d source=network",
            _host(url),
            response.status_code,
            len(response.body),
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
            save_text=save_text,
            extract_text=extract_text,
            include_metadata=include_metadata,
        )

    def fetch_document(self, url: str) -> FetchedDocument:
        """Fetch a URL and return its full decoded body for crawling.

        Reuses the same robots check, cache, and rate limiting as :meth:`fetch`,
        but returns the complete decoded body (not a truncated preview) so the
        crawler can extract links from it.
        """

        decision = self.robots.can_fetch(url)
        if not decision.allowed:
            return FetchedDocument(
                url=url,
                status_code=None,
                allowed_by_robots=False,
                html="",
                source=decision.reason,
            )

        cached = self.cache.get(url)
        if cached is not None:
            headers = json.loads(cached.headers_json)
            response = HttpResponse(
                url=cached.url,
                status_code=cached.status_code,
                headers={str(key): str(value) for key, value in headers.items()},
                body=cached.body,
            )
            source = "cache"
        else:
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
            source = "network"

        content_type = _header_value(response.headers, "content-type")
        html = decode_body(response.body, content_type)
        return FetchedDocument(
            url=url,
            status_code=response.status_code,
            allowed_by_robots=True,
            html=html,
            source=source,
        )


def _result_from_response(
    *,
    url: str,
    response: HttpResponse,
    source: str,
    robots_url: str,
    preview_chars: int,
    save_text: str | Path | None = None,
    extract_text: bool = False,
    include_metadata: bool = False,
) -> FetchResult:
    content_type = _header_value(response.headers, "content-type")
    raw_text = decode_body(response.body, content_type)
    text = extract_text_from_html(raw_text) if extract_text else raw_text
    preview = text[: max(0, preview_chars)]
    saved_text = (
        _with_metadata(
            text,
            url=url,
            response=response,
            content_type=content_type,
            extracted_text=extract_text,
        )
        if include_metadata
        else text
    )
    saved_path = _save_text(saved_text, save_text) if save_text is not None else None
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
        saved_path=saved_path,
        extracted_text=extract_text,
        metadata_included=include_metadata and save_text is not None,
    )


def _host(url: str) -> str:
    """Return just the host for logging, avoiding path/query leakage."""

    from urllib.parse import urlparse

    return urlparse(url).hostname or "<unknown>"


def _header_value(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _save_text(text: str, save_text: str | Path) -> str:
    path = reject_path_traversal(save_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def reject_path_traversal(path: str | Path) -> Path:
    """Reject ``..`` components that could escape the intended output location.

    Used for user-typed output paths (``--save-text``/``--save-report``): an
    absolute path is the caller's explicit choice, but ``..`` traversal is not.
    """

    candidate = Path(path)
    if any(part == ".." for part in candidate.parts):
        msg = f"Path traversal ('..') is not allowed in output path: {path}"
        raise ValueError(msg)
    return candidate


def _with_metadata(
    text: str,
    *,
    url: str,
    response: HttpResponse,
    content_type: str | None,
    extracted_text: bool,
) -> str:
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    metadata = (
        "---\n"
        f"source_url: {_quote_metadata_value(url)}\n"
        f"fetched_at: {fetched_at}\n"
        f"status_code: {response.status_code}\n"
        f"content_type: {_quote_metadata_value(content_type or '')}\n"
        f"extracted_text: {str(extracted_text).lower()}\n"
        "---\n\n"
    )
    return f"{metadata}{text}"


def _quote_metadata_value(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'
