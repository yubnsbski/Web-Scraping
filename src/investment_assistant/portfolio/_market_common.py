"""Shared helpers for the market-data fetchers (prices / OHLCV / intraday).

Keeps the network boundary and CSV rendering in one place so the per-source
modules differ only in their URLs and parsers.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from investment_assistant.ingestion.fetcher import SafeFetcher

__all__ = [
    "DEFAULT_RATE_LIMIT",
    "RateLimitPolicy",
    "Sleeper",
    "default_fetch",
    "fetch_once",
    "pause_after",
    "render_csv",
    "request_with_retry",
    "unique_tickers",
]

Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class RateLimitPolicy:
    """Conservative pacing for batch scrapes to avoid Yahoo 429 (Too Many Requests).

    Mirrors the widely recommended safe-design defaults: space requests by a few
    seconds, back off (and retry) on failure, and optionally rest between batches
    of ``batch_size`` tickers. ``SafeFetcher`` already rate-limits per domain at
    the network layer; this adds an explicit, tunable layer at the batch level.
    """

    sleep_between: float = 2.0
    max_retries: int = 3
    retry_base_wait: float = 10.0
    batch_size: int = 0  # 0 disables batch-level pauses
    sleep_between_batches: float = 30.0


DEFAULT_RATE_LIMIT = RateLimitPolicy()


def default_fetch(url: str) -> str:
    """Fetch a URL's body via the robots-respecting, rate-limited SafeFetcher."""

    return SafeFetcher().fetch_document(url).html


def unique_tickers(tickers: Iterable[str]) -> list[str]:
    """Trim, drop blanks, and de-duplicate while preserving order."""

    seen: set[str] = set()
    out: list[str] = []
    for raw in tickers:
        ticker = str(raw).strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def request_with_retry(
    fetch: Callable[[str], str],
    url: str,
    *,
    policy: RateLimitPolicy,
    sleeper: Sleeper = time.sleep,
    logger: logging.Logger | None = None,
) -> str:
    """Fetch ``url`` with linear backoff, retrying on errors and empty bodies.

    An empty/blank body is treated as a soft rate-limit signal (Yahoo can answer
    429s with an empty payload) and retried. Returns the body on success; raises
    the last exception only if every attempt raised; returns ``""`` if every
    attempt came back empty.
    """

    last_exc: Exception | None = None
    for attempt in range(1, policy.max_retries + 1):
        try:
            body = fetch(url)
        except Exception as exc:  # noqa: BLE001 - retried with backoff below
            last_exc = exc
            if logger is not None:
                logger.warning(
                    "fetch error url=%s attempt=%d/%d error=%s",
                    url, attempt, policy.max_retries, type(exc).__name__,
                )
        else:
            if body and body.strip():
                return body
            last_exc = None
            if logger is not None:
                logger.warning(
                    "empty body (possible rate limit) url=%s attempt=%d/%d",
                    url, attempt, policy.max_retries,
                )
        if attempt < policy.max_retries:
            sleeper(policy.retry_base_wait * attempt)
    if last_exc is not None:
        raise last_exc
    return ""


def fetch_once(
    fetch: Callable[[str], str],
    url: str,
    *,
    policy: RateLimitPolicy | None,
    sleeper: Sleeper = time.sleep,
    logger: logging.Logger | None = None,
) -> str:
    """Fetch ``url`` raw when ``policy`` is None, else via :func:`request_with_retry`."""

    if policy is None:
        return fetch(url)
    return request_with_retry(fetch, url, policy=policy, sleeper=sleeper, logger=logger)


def pause_after(
    index: int,
    total: int,
    *,
    policy: RateLimitPolicy,
    sleeper: Sleeper = time.sleep,
) -> None:
    """Sleep after processing item ``index`` (0-based) of ``total`` per ``policy``.

    Uses the longer batch pause at each ``batch_size`` boundary, the per-request
    spacing otherwise, and nothing after the final item.
    """

    if index >= total - 1:
        return
    if policy.batch_size and (index + 1) % policy.batch_size == 0:
        sleeper(policy.sleep_between_batches)
    elif policy.sleep_between > 0:
        sleeper(policy.sleep_between)


def render_csv(fields: tuple[str, ...], rows: Iterable[dict[str, object]]) -> str:
    """Render row dicts as CSV text with a fixed header; None renders as empty."""

    def cell(value: object) -> str:
        return "" if value is None else str(value)

    lines = [",".join(fields)]
    lines.extend(",".join(cell(row.get(field)) for field in fields) for row in rows)
    return "\n".join(lines) + "\n"
