"""Yahoo Finance OHLCV scraper for the portfolio tooling.

Fetches daily OHLCV (open/high/low/close/volume) bars per ticker from the Yahoo
Finance v8 chart JSON endpoint via the robots-respecting, rate-limited, cached
:class:`SafeFetcher`. Tokyo-listed symbols are queried as ``{ticker}.T``.
``fetch`` is injectable for offline testing.

Personal-use, on-demand quotes only — respect the source's terms; no
redistribution, no trading.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from investment_assistant.observability import get_logger
from investment_assistant.portfolio._market_common import (
    RateLimitPolicy,
    Sleeper,
    default_fetch,
    fetch_once,
    pause_after,
    render_csv,
    unique_tickers,
)

_logger = get_logger("portfolio.ohlcv")

YAHOO_OHLCV_URL_TEMPLATE = (
    "https://query1.finance.yahoo.com/v8/finance/chart/"
    "{ticker}.T?range={range}&interval={interval}"
)

_OHLCV_FIELDS = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class OhlcvBar:
    """One daily OHLCV bar (trading-date local to the exchange)."""

    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None


def _num(seq: object, index: int) -> float | None:
    if isinstance(seq, list) and index < len(seq) and isinstance(seq[index], int | float):
        return float(seq[index])
    return None


def _vol(seq: object, index: int) -> int | None:
    value = _num(seq, index)
    return int(value) if value is not None else None


def parse_yahoo_ohlcv(json_text: str) -> list[OhlcvBar]:
    """Parse Yahoo v8 chart JSON into OHLCV bars (empty list on malformed input).

    Timestamps are shifted by the payload's ``gmtoffset`` so each bar's ``date``
    is the trading date in the exchange's local time, and fully-null rows (which
    Yahoo emits for non-trading days) are dropped.
    """

    try:
        result = json.loads(json_text)["chart"]["result"][0]
    except (ValueError, KeyError, TypeError, IndexError):
        return []
    if not isinstance(result, dict):
        return []
    timestamps = result.get("timestamp")
    if not isinstance(timestamps, list):
        return []
    try:
        quote = result["indicators"]["quote"][0]
    except (KeyError, TypeError, IndexError):
        return []
    if not isinstance(quote, dict):
        return []

    meta = result.get("meta")
    raw_offset = meta.get("gmtoffset") if isinstance(meta, dict) else 0
    gmtoffset = int(raw_offset) if isinstance(raw_offset, int | float) else 0

    opens, highs = quote.get("open"), quote.get("high")
    lows, closes, volumes = quote.get("low"), quote.get("close"), quote.get("volume")

    bars: list[OhlcvBar] = []
    for index, timestamp in enumerate(timestamps):
        if not isinstance(timestamp, int | float):
            continue
        o, h = _num(opens, index), _num(highs, index)
        low, close = _num(lows, index), _num(closes, index)
        if o is None and h is None and low is None and close is None:
            continue
        date = datetime.fromtimestamp(int(timestamp) + gmtoffset, tz=UTC).date().isoformat()
        bars.append(OhlcvBar(date, o, h, low, close, _vol(volumes, index)))
    return bars


def fetch_ohlcv(
    tickers: Iterable[str],
    *,
    fetch: Callable[[str], str] | None = None,
    range_: str = "1mo",
    interval: str = "1d",
    rate_limit: RateLimitPolicy | None = None,
    sleeper: Sleeper = time.sleep,
) -> dict[str, object]:
    """Scrape daily OHLCV series for every ticker (no implicit count cap).

    Returns ``{"ohlcv": {ticker: [bar, ...]}, "counts": {...}, "notes": {...}}``;
    a single failing ticker is recorded in ``notes`` and never aborts the batch.
    With ``rate_limit`` set, requests are spaced and retried with backoff to avoid
    Yahoo 429s (the CLI/API supply a safe policy for large batches).
    """

    fetcher = fetch or default_fetch
    resolved = unique_tickers(tickers)
    total = len(resolved)
    series: dict[str, list[dict[str, object]]] = {}
    counts: dict[str, int] = {}
    notes: dict[str, str] = {}
    for index, ticker in enumerate(resolved):
        url = YAHOO_OHLCV_URL_TEMPLATE.format(
            ticker=ticker.lower(), range=range_, interval=interval
        )
        try:
            body = fetch_once(fetcher, url, policy=rate_limit, sleeper=sleeper, logger=_logger)
            bars = parse_yahoo_ohlcv(body)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the batch
            _logger.warning("ohlcv fetch failed ticker=%s error=%s", ticker, type(exc).__name__)
            series[ticker] = []
            counts[ticker] = 0
            notes[ticker] = type(exc).__name__
        else:
            series[ticker] = [asdict(bar) for bar in bars]
            counts[ticker] = len(bars)
        if rate_limit is not None:
            pause_after(index, total, policy=rate_limit, sleeper=sleeper)
    return {
        "provider_id": "yfinance",
        "range": range_,
        "interval": interval,
        "ohlcv": series,
        "counts": counts,
        "notes": notes,
    }


def ohlcv_csv_text(bars: Iterable[dict[str, object]]) -> str:
    """Render OHLCV bar dicts as CSV text with a fixed header."""

    return render_csv(_OHLCV_FIELDS, bars)
