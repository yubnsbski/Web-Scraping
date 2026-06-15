"""Market price fetcher for the portfolio simulator.

Fetches the latest close per ticker from a public CSV endpoint via the
robots-respecting, rate-limited, cached :class:`SafeFetcher`. The default source
is Stooq's snapshot CSV (free public quotes); the URL is configurable via the
``MARKET_PRICE_URL_TEMPLATE`` env so the operator can point at a source they are
permitted to use. ``fetch`` is injectable for offline testing.

Personal-use, on-demand quotes only — no redistribution, no trading.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Callable, Iterable

from investment_assistant.ingestion.fetcher import SafeFetcher
from investment_assistant.observability import get_logger

_logger = get_logger("portfolio.prices")

# Stooq snapshot CSV header: Symbol,Date,Time,Open,High,Low,Close,Volume
DEFAULT_PRICE_URL_TEMPLATE = "https://stooq.com/q/l/?s={ticker}.jp&f=sd2t2ohlcv&h&e=csv"
PRICE_URL_TEMPLATE_ENV = "MARKET_PRICE_URL_TEMPLATE"


def parse_close(csv_text: str) -> float | None:
    """Return the Close price from a quote CSV, or None if unavailable."""

    rows = [row for row in csv.reader(io.StringIO(csv_text)) if row]
    if len(rows) < 2:
        return None
    header = [cell.strip().lower() for cell in rows[0]]
    if "close" not in header:
        return None
    index = header.index("close")
    last = rows[-1]
    if index >= len(last):
        return None
    try:
        value = float(last[index])
    except ValueError:
        return None
    return value if value > 0 else None


def _default_fetch(url: str) -> str:
    return SafeFetcher().fetch_document(url).html


def fetch_prices(
    tickers: Iterable[str],
    *,
    fetch: Callable[[str], str] | None = None,
    url_template: str | None = None,
) -> dict[str, object]:
    """Fetch latest close prices for ``tickers`` (ticker -> price or None)."""

    fetcher = fetch or _default_fetch
    template = url_template or os.getenv(PRICE_URL_TEMPLATE_ENV) or DEFAULT_PRICE_URL_TEMPLATE
    prices: dict[str, float | None] = {}
    notes: dict[str, str] = {}
    for raw in tickers:
        ticker = str(raw).strip()
        if not ticker or ticker in prices:
            continue
        url = template.format(ticker=ticker.lower())
        try:
            prices[ticker] = parse_close(fetcher(url))
            if prices[ticker] is None:
                notes[ticker] = "no_close_price_returned"
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the batch
            _logger.warning("price fetch failed ticker=%s error=%s", ticker, type(exc).__name__)
            prices[ticker] = None
            notes[ticker] = type(exc).__name__
    return {"prices": prices, "notes": notes, "source": template}
