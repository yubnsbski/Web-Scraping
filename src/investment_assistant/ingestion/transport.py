"""HTTP transport abstractions for safe, testable ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpResponse:
    """Small immutable response object returned by transports."""

    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes


class HttpTransport(Protocol):
    """Transport protocol so tests can avoid real network calls."""

    def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
        """Fetch a URL and return the response."""


class UrlLibHttpTransport:
    """stdlib urllib-backed transport for production CLI usage."""

    def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
        request = Request(url, headers={"User-Agent": user_agent})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                body = response.read()
                headers = {key: value for key, value in response.headers.items()}
                return HttpResponse(
                    url=response.geturl(),
                    status_code=int(response.status),
                    headers=headers,
                    body=body,
                )
        except HTTPError as exc:
            body = exc.read()
            headers = {key: value for key, value in exc.headers.items()}
            return HttpResponse(
                url=exc.geturl(),
                status_code=int(exc.code),
                headers=headers,
                body=body,
            )
        except URLError as exc:
            message = f"Could not fetch {url}: {exc.reason}"
            raise OSError(message) from exc
