"""Yahoo!ファイナンス fundamentals (financial info) fetcher.

Complements the EDINET financials (cash flow, equity ratio, payout) with
market-based metrics — PER / PBR / dividend yield / market cap / EPS / DPS —
from Yahoo's v7 quote endpoint, which returns many symbols in one request.
Request pacing/retry/batching is delegated to the shared
:class:`~investment_assistant.portfolio._market_common.MarketFetchRunner`.

Personal-use, on-demand only. Honors robots.txt unless the personal-use bypass
env (``MARKET_ALLOW_ROBOTS_BYPASS``) is set.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable

from investment_assistant.observability import get_logger
from investment_assistant.portfolio._market_common import (
    MarketFetchPolicy,
    MarketFetchRunner,
    default_fetch,
    normalize_tickers,
)

_logger = get_logger("portfolio.yahoo_financials")

YAHOO_QUOTE_URL_TEMPLATE = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"

# Yahoo v7 quote field -> our normalized key.
_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("regularMarketPrice", "price"),
    ("trailingPE", "per"),
    ("priceToBook", "pbr"),
    ("trailingAnnualDividendRate", "dps"),
    ("trailingAnnualDividendYield", "dividend_yield"),
    ("epsTrailingTwelveMonths", "eps"),
    ("marketCap", "market_cap"),
)


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def parse_yahoo_quote(json_text: str) -> dict[str, dict[str, object]]:
    """Parse a v7 quote payload into ``{ticker: {metrics}}`` (``.T`` stripped)."""

    out: dict[str, dict[str, object]] = {}
    try:
        results = json.loads(json_text)["quoteResponse"]["result"]
    except (ValueError, KeyError, TypeError):
        return out
    if not isinstance(results, list):
        return out
    for item in results:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        ticker = symbol[:-2] if symbol.upper().endswith(".T") else symbol
        if not ticker:
            continue
        metrics: dict[str, object] = {}
        name = item.get("longName") or item.get("shortName")
        if isinstance(name, str) and name:
            metrics["name"] = name
        for src, dst in _FIELD_MAP:
            value = _num(item.get(src))
            if value is not None:
                metrics[dst] = value
        out[ticker] = metrics
    return out


def fetch_yahoo_financials(
    tickers: Iterable[str],
    *,
    fetch: Callable[[str], str] | None = None,
    rate_limit: MarketFetchPolicy | None = None,
) -> dict[str, object]:
    """Fetch fundamentals for ``tickers`` in batched v7 quote requests.

    Symbols are queried one batch per request (batch size from the policy), with
    rate-limit pacing/retry between batches when ``rate_limit`` is set.
    """

    fetcher = fetch or default_fetch
    runner = MarketFetchRunner(fetcher, policy=rate_limit, logger=_logger)
    financials: dict[str, dict[str, object]] = {}
    notes: dict[str, str] = {}
    for batch in runner.batches(normalize_tickers(tickers)):
        symbols = ",".join(f"{ticker}.T" for ticker in batch)
        url = YAHOO_QUOTE_URL_TEMPLATE.format(symbols=symbols)
        try:
            parsed = parse_yahoo_quote(
                runner.fetch_once(url, ticker=batch[0] if batch else "")
            )
        except Exception as exc:  # noqa: BLE001 - one bad batch must not abort the rest
            _logger.warning("financials fetch failed error=%s", type(exc).__name__)
            for ticker in batch:
                notes[ticker] = type(exc).__name__
            parsed = {}
        for ticker in batch:
            if ticker in parsed:
                financials[ticker] = parsed[ticker]
            elif ticker not in notes:
                notes[ticker] = "not_found"
    result: dict[str, object] = {
        "provider_id": "yfinance",
        "financials": financials,
        "counts": {ticker: len(metrics) for ticker, metrics in financials.items()},
        "notes": notes,
    }
    if rate_limit is not None:
        result["rate_limit"] = runner.summary()
    return result
