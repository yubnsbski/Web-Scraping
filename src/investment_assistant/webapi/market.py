"""Market-data JSON API handlers.

This module keeps provider-policy checks, ticker validation, and market fetch
runner dispatch out of the larger framework-agnostic ``service`` module.
"""

from __future__ import annotations

import os
from typing import Any

from investment_assistant import cli

JsonDict = dict[str, Any]

_MAX_MARKET_TICKERS = 50
_YAHOO_PRICE_PROVIDER_IDS = {"yfinance", "yahoo", "yahoo_finance"}


def market_prices(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.provider_policy import ensure_provider_allowed
    from investment_assistant.portfolio._market_common import DEFAULT_YAHOO_RATE_LIMIT_POLICY
    from investment_assistant.portfolio.prices import fetch_prices

    raw = body.get("tickers")
    tickers = [str(t) for t in raw] if isinstance(raw, list) else []
    provider_id = str(body.get("provider_id") or "stooq_public_csv")
    runtime_mode = _runtime_mode(body)
    policy = ensure_provider_allowed(provider_id, runtime_mode=runtime_mode)
    rate_limit = (
        DEFAULT_YAHOO_RATE_LIMIT_POLICY
        if provider_id.strip().lower() in _YAHOO_PRICE_PROVIDER_IDS
        else None
    )
    result = fetch_prices(tickers, provider_id=provider_id, rate_limit=rate_limit)
    result["provider_policy"] = policy.to_dict()
    return result


def market_ohlcv(body: JsonDict) -> JsonDict:
    tickers, runtime_mode = _market_universe(body)
    _ensure_market_provider("yfinance", runtime_mode)
    return cli.run_market_ohlcv(
        tickers=tickers,
        range_=str(body.get("range") or "1mo"),
        interval=str(body.get("interval") or "1d"),
    )


def market_intraday(body: JsonDict) -> JsonDict:
    tickers, runtime_mode = _market_universe(body)
    _ensure_market_provider("yahoo_jp_intraday", runtime_mode)
    return cli.run_yahoo_intraday(tickers=tickers)


def _market_ticker_list(body: JsonDict) -> list[str]:
    """Accept ``tickers`` as a list or a comma-separated string; trim blanks."""

    raw = body.get("tickers")
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, list):
        items = [str(item) for item in raw]
    else:
        items = []
    return [ticker.strip() for ticker in items if ticker.strip()]


def _market_universe(body: JsonDict) -> tuple[list[str], str]:
    """Validate and return ``(tickers, runtime_mode)`` for a market scrape."""

    tickers = _market_ticker_list(body)
    if not tickers:
        raise ValueError("tickers must be a non-empty list or comma-separated string")
    if len(tickers) > _MAX_MARKET_TICKERS:
        raise ValueError(f"too many tickers (max {_MAX_MARKET_TICKERS})")
    return tickers, _runtime_mode(body)


def _runtime_mode(body: JsonDict) -> str:
    return str(
        body.get("runtime_mode")
        or os.getenv("INVESTMENT_ASSISTANT_RUNTIME_MODE")
        or "development"
    )


def _ensure_market_provider(provider_id: str, runtime_mode: str) -> None:
    from investment_assistant.investment.provider_policy import ensure_provider_allowed

    ensure_provider_allowed(provider_id, runtime_mode=runtime_mode)
