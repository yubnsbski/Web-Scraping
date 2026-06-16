"""Shared helpers for the market-data fetchers (prices / OHLCV / intraday).

Keeps the network boundary, CSV rendering, and Yahoo/yfinance rate-limit
discipline in one place so the per-source modules differ only in their URLs and
parsers.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import sleep

from investment_assistant.ingestion.fetcher import SafeFetcher
from investment_assistant.observability import get_logger

__all__ = [
    "DEFAULT_YAHOO_RATE_LIMIT_POLICY",
    "MARKET_ROBOTS_BYPASS_ENV",
    "MarketFetchPolicy",
    "MarketFetchRunner",
    "MarketRateLimitError",
    "default_fetch",
    "fetch_once",
    "normalize_tickers",
    "render_csv",
    "robots_bypass_enabled",
]

Fetch = Callable[[str], str]
Sleeper = Callable[[float], None]
_logger = get_logger("portfolio.market_common")
MARKET_ROBOTS_BYPASS_ENV = "MARKET_ALLOW_ROBOTS_BYPASS"


class MarketRateLimitError(RuntimeError):
    """Raised when a market-data response looks like throttling."""


@dataclass(frozen=True)
class MarketFetchPolicy:
    """Conservative request policy for personal-use Yahoo/yfinance pulls."""

    min_interval_seconds: float = 2.0
    retry_attempts: int = 3
    retry_base_wait_seconds: float = 10.0
    exponential_backoff: bool = False
    batch_size: int = 10
    sleep_between_batches_seconds: float = 30.0
    empty_response_is_rate_limit: bool = True
    log_path: Path | None = Path("local_docs/logs/market_fetch.log")
    max_log_bytes: int = 1_000_000
    backup_count: int = 3
    sleeper: Sleeper = sleep

    def with_sleeper(self, sleeper: Sleeper) -> MarketFetchPolicy:
        """Return a copy with an injected sleeper, useful for fast tests."""

        return replace(self, sleeper=sleeper)

    def to_dict(self) -> dict[str, object]:
        return {
            "min_interval_seconds": self.min_interval_seconds,
            "retry_attempts": self.retry_attempts,
            "retry_base_wait_seconds": self.retry_base_wait_seconds,
            "exponential_backoff": self.exponential_backoff,
            "batch_size": self.batch_size,
            "sleep_between_batches_seconds": self.sleep_between_batches_seconds,
            "empty_response_is_rate_limit": self.empty_response_is_rate_limit,
            "log_path": str(self.log_path) if self.log_path else None,
        }


DEFAULT_YAHOO_RATE_LIMIT_POLICY = MarketFetchPolicy()


class MarketFetchRunner:
    """Apply request spacing, retry/backoff, batch pauses, and safe logging."""

    def __init__(
        self,
        fetch: Fetch,
        *,
        policy: MarketFetchPolicy | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.fetch: Fetch = fetch
        self.policy: MarketFetchPolicy | None = policy
        self.logger: logging.Logger = logger or _logger
        self.request_count: int = 0
        self.retry_count: int = 0
        self.rate_limit_count: int = 0
        self.batch_pause_count: int = 0
        self.failed_urls: list[str] = []
        if self.policy is not None:
            _ensure_file_logging(self.logger, self.policy)

    def batches(self, tickers: Sequence[str]) -> Iterator[list[str]]:
        if self.policy is None:
            yield list(tickers)
            return
        size = max(int(self.policy.batch_size), 1)
        for start in range(0, len(tickers), size):
            if start > 0 and self.policy.sleep_between_batches_seconds > 0:
                self.batch_pause_count += 1
                self.logger.info(
                    "market fetch batch pause batch_index=%s seconds=%s",
                    start // size,
                    self.policy.sleep_between_batches_seconds,
                )
                self.policy.sleeper(self.policy.sleep_between_batches_seconds)
            yield list(tickers[start : start + size])

    def fetch_once(self, url: str, *, ticker: str = "") -> str:
        if self.policy is None:
            return self.fetch(url)

        last_error: Exception | None = None
        attempts = max(int(self.policy.retry_attempts), 0) + 1
        for attempt_index in range(attempts):
            if self.request_count > 0 and self.policy.min_interval_seconds > 0:
                self.policy.sleeper(self.policy.min_interval_seconds)
            self.request_count += 1
            try:
                text = self.fetch(url)
                if self.policy.empty_response_is_rate_limit and not str(text or "").strip():
                    raise MarketRateLimitError("empty response treated as rate limit")
                if attempt_index:
                    self.logger.info(
                        "market fetch recovered ticker=%s attempt=%s",
                        ticker,
                        attempt_index + 1,
                    )
                return text
            except Exception as exc:  # noqa: BLE001 - fetch boundary normalizes failures
                last_error = exc
                if _looks_rate_limited(exc):
                    self.rate_limit_count += 1
                if attempt_index >= attempts - 1:
                    self.failed_urls.append(url)
                    self.logger.warning(
                        "market fetch failed ticker=%s attempts=%s error=%s",
                        ticker,
                        attempts,
                        type(exc).__name__,
                    )
                    raise
                self.retry_count += 1
                wait_seconds = self._retry_wait(attempt_index + 1)
                self.logger.warning(
                    "market fetch retry ticker=%s attempt=%s wait_seconds=%s error=%s",
                    ticker,
                    attempt_index + 1,
                    wait_seconds,
                    type(exc).__name__,
                )
                self.policy.sleeper(wait_seconds)
        assert last_error is not None
        raise last_error

    def summary(self) -> dict[str, object]:
        if self.policy is None:
            return {"enabled": False}
        return {
            "enabled": True,
            **self.policy.to_dict(),
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "rate_limit_count": self.rate_limit_count,
            "batch_pause_count": self.batch_pause_count,
            "failed_count": len(self.failed_urls),
        }

    def _retry_wait(self, attempt: int) -> float:
        assert self.policy is not None
        base = float(self.policy.retry_base_wait_seconds)
        if self.policy.exponential_backoff:
            return float(base * (2 ** (attempt - 1)))
        return float(base * attempt)


def default_fetch(url: str) -> str:
    """Fetch a URL's body via the robots-respecting, rate-limited SafeFetcher."""

    return SafeFetcher().fetch_document(url, respect_robots=not robots_bypass_enabled()).html


def robots_bypass_enabled() -> bool:
    """Return whether personal-use market fetches may skip only robots.txt."""

    return os.getenv(MARKET_ROBOTS_BYPASS_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def fetch_once(
    fetch: Fetch,
    url: str,
    *,
    ticker: str = "",
    policy: MarketFetchPolicy | None = None,
    logger: logging.Logger | None = None,
) -> str:
    """Fetch one URL with an optional policy; convenient for small callers."""

    return MarketFetchRunner(fetch, policy=policy, logger=logger).fetch_once(url, ticker=ticker)


def normalize_tickers(tickers: Iterable[str]) -> list[str]:
    """Trim, de-duplicate, and preserve ticker order."""

    out: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        ticker = str(raw).strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def render_csv(fields: tuple[str, ...], rows: Iterable[dict[str, object]]) -> str:
    """Render row dicts as CSV text with a fixed header; None renders as empty."""

    def cell(value: object) -> str:
        return "" if value is None else str(value)

    lines = [",".join(fields)]
    lines.extend(",".join(cell(row.get(field)) for field in fields) for row in rows)
    return "\n".join(lines) + "\n"


def _looks_rate_limited(exc: Exception) -> bool:
    if isinstance(exc, MarketRateLimitError):
        return True
    message = str(exc).lower()
    return "429" in message or "too many requests" in message or "rate limit" in message


def _ensure_file_logging(logger: logging.Logger, policy: MarketFetchPolicy) -> None:
    if policy.log_path is None:
        return
    path = Path(policy.log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = str(path.resolve())
    for handler in logger.handlers:
        if getattr(handler, "_market_fetch_log_path", None) == marker:
            return
    handler = RotatingFileHandler(
        path,
        maxBytes=max(int(policy.max_log_bytes), 1),
        backupCount=max(int(policy.backup_count), 0),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler._market_fetch_log_path = marker  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
