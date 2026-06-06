"""HTTP transport abstractions for safe, testable ingestion.

The production transport adds two defensive controls that matter when fetching
arbitrary user-supplied URLs:

* SSRF protection: the target host is resolved and rejected when it points at
  private, loopback, link-local, or other non-public address ranges (including
  the cloud metadata endpoint ``169.254.169.254``). Redirects are validated the
  same way on every hop so a public URL cannot bounce into an internal host.
* Response size limits: the body is read with an upper bound so a hostile or
  accidental large response cannot exhaust memory.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class HttpResponse:
    """Small immutable response object returned by transports."""

    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes


class UnsafeUrlError(OSError):
    """Raised when a URL targets a non-public address or a blocked scheme.

    Subclassing :class:`OSError` keeps the existing fail-safe behavior: the
    robots checker already treats ``OSError`` as "do not fetch", so an unsafe
    host is blocked before any body is requested.
    """


class ResponseTooLargeError(OSError):
    """Raised when a response body exceeds the configured size limit."""


class HttpTransport(Protocol):
    """Transport protocol so tests can avoid real network calls."""

    def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
        """Fetch a URL and return the response."""


def validate_public_http_url(url: str) -> None:
    """Raise :class:`UnsafeUrlError` if ``url`` is not a public http(s) target."""

    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        msg = f"Only http(s) URLs are allowed: {url}"
        raise UnsafeUrlError(msg)
    host = parsed.hostname
    if not host:
        msg = f"URL is missing a host: {url}"
        raise UnsafeUrlError(msg)

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addr_infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        msg = f"Could not resolve host for {url}: {exc}"
        raise UnsafeUrlError(msg) from exc

    for info in addr_infos:
        ip_text = info[4][0]
        ip = ipaddress.ip_address(ip_text)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            msg = f"Refusing to fetch non-public address {ip_text} for {url}"
            raise UnsafeUrlError(msg)


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    """Re-validate every redirect target so SSRF cannot hide behind a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def] # noqa: ANN001, ANN201
        validate_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrlLibHttpTransport:
    """stdlib urllib-backed transport for production CLI usage."""

    def __init__(self, *, max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES) -> None:
        self.max_bytes = max_bytes
        self._opener = build_opener(_ValidatingRedirectHandler())

    def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
        validate_public_http_url(url)
        request = Request(url, headers={"User-Agent": user_agent})
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310
                body = self._read_limited(response)
                headers = {key: value for key, value in response.headers.items()}
                return HttpResponse(
                    url=response.geturl(),
                    status_code=int(response.status),
                    headers=headers,
                    body=body,
                )
        except HTTPError as exc:
            body = self._read_limited(exc)
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

    def _read_limited(self, response: object) -> bytes:
        body: bytes = response.read(self.max_bytes + 1)  # type: ignore[attr-defined]
        if len(body) > self.max_bytes:
            msg = f"Response body exceeds {self.max_bytes} byte limit"
            raise ResponseTooLargeError(msg)
        return body
