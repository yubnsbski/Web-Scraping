"""Market price fetcher for the portfolio simulator.

Fetches the latest close per ticker from a public endpoint via the
robots-respecting, rate-limited, cached :class:`SafeFetcher`. Two providers are
built in and selected by ``provider_id``:

* ``stooq_public_csv`` (default) — Stooq snapshot CSV.
* ``yfinance`` — Yahoo Finance v8 chart JSON (Tokyo ``.T`` symbols).

The default provider and Stooq URL are overridable via the ``MARKET_PRICE_PROVIDER``
and ``MARKET_PRICE_URL_TEMPLATE`` envs, and ``fetch`` is injectable for offline
testing.

Personal-use, on-demand quotes only — no redistribution, no trading.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Callable, Iterable

from investment_assistant.observability import get_logger
from investment_assistant.portfolio._market_common import (
    MarketFetchPolicy,
    MarketFetchRunner,
    default_fetch,
    normalize_tickers,
)

_logger = get_logger("portfolio.prices")

# Stooq snapshot CSV header: Symbol,Date,Time,Open,High,Low,Close,Volume
DEFAULT_PRICE_URL_TEMPLATE = "https://stooq.com/q/l/?s={ticker}.jp&f=sd2t2ohlcv&h&e=csv"
# Yahoo Finance v8 chart JSON for a Tokyo-listed symbol (e.g. 8306 -> 8306.T).
YAHOO_CHART_URL_TEMPLATE = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.T?range=5d&interval=1d"
)
PRICE_URL_TEMPLATE_ENV = "MARKET_PRICE_URL_TEMPLATE"
PRICE_PROVIDER_ENV = "MARKET_PRICE_PROVIDER"
DEFAULT_PROVIDER_ID = "stooq_public_csv"
# Aliases that all mean "Yahoo Finance".
_YAHOO_PROVIDER_IDS = {"yfinance", "yahoo", "yahoo_finance"}


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


def parse_yahoo_close(json_text: str) -> float | None:
    """Return the latest close from a Yahoo Finance v8 chart JSON payload.

    Prefers ``meta.regularMarketPrice``; falls back to the last non-null close in
    the daily ``indicators.quote`` series. Returns None on any malformed payload.
    """

    try:
        result = json.loads(json_text)["chart"]["result"][0]
    except (ValueError, KeyError, TypeError, IndexError):
        return None

    meta = result.get("meta") if isinstance(result, dict) else None
    if isinstance(meta, dict):
        price = meta.get("regularMarketPrice")
        if isinstance(price, int | float) and price > 0:
            return float(price)

    try:
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, TypeError, IndexError):
        return None
    if not isinstance(closes, list):
        return None
    for value in reversed(closes):
        if isinstance(value, int | float) and value > 0:
            return float(value)
    return None


def _resolve_provider(
    provider_id: str | None, url_template: str | None
) -> tuple[str, str, Callable[[str], float | None]]:
    """Resolve ``(canonical_provider_id, url_template, parser)`` for a request.

    An explicit ``url_template`` always wins. Otherwise the provider is taken
    from ``provider_id`` (or the ``MARKET_PRICE_PROVIDER`` env, default Stooq),
    and Stooq additionally honors the ``MARKET_PRICE_URL_TEMPLATE`` env.
    """

    pid = (provider_id or os.getenv(PRICE_PROVIDER_ENV) or DEFAULT_PROVIDER_ID).strip().lower()
    if pid in _YAHOO_PROVIDER_IDS:
        return "yfinance", url_template or YAHOO_CHART_URL_TEMPLATE, parse_yahoo_close
    template = url_template or os.getenv(PRICE_URL_TEMPLATE_ENV) or DEFAULT_PRICE_URL_TEMPLATE
    return "stooq_public_csv", template, parse_close


def fetch_prices(
    tickers: Iterable[str],
    *,
    provider_id: str | None = None,
    fetch: Callable[[str], str] | None = None,
    url_template: str | None = None,
    rate_limit: MarketFetchPolicy | None = None,
) -> dict[str, object]:
    """Fetch latest close prices for ``tickers`` (ticker -> price or None).

    ``provider_id`` selects the data source (``stooq_public_csv`` or
    ``yfinance``); the matching URL template and response parser are applied so
    the caller's provider choice actually drives the fetch.
    """

    fetcher = fetch or default_fetch
    runner = MarketFetchRunner(fetcher, policy=rate_limit, logger=_logger)
    resolved_id, template, parser = _resolve_provider(provider_id, url_template)
    prices: dict[str, float | None] = {}
    notes: dict[str, str] = {}
    for batch in runner.batches(normalize_tickers(tickers)):
        for ticker in batch:
            url = template.format(ticker=ticker.lower())
            try:
                prices[ticker] = parser(runner.fetch_once(url, ticker=ticker))
            except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the batch
                _logger.warning("price fetch failed ticker=%s error=%s", ticker, type(exc).__name__)
                prices[ticker] = None
                notes[ticker] = type(exc).__name__
    result: dict[str, object] = {
        "prices": prices,
        "notes": notes,
        "source": template,
        "provider_id": resolved_id,
    }
    if rate_limit is not None:
        result["rate_limit"] = runner.summary()
    return result
