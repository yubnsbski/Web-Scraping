"""Market-data JSON API handlers.

This module keeps provider-policy checks, ticker validation, and market fetch
runner dispatch out of the larger framework-agnostic ``service`` module.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from investment_assistant import cli
from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.webapi.errors import ApiError

JsonDict = dict[str, Any]

_MAX_MARKET_TICKERS = 50
_YAHOO_PRICE_PROVIDER_IDS = {"yfinance", "yahoo", "yahoo_finance"}
_DEFAULT_NIKKEI225_REGISTRY = "examples/source_registry_nikkei225_edinet.yaml"
_DEFAULT_DAILY_BARS_PATH = "local_docs/market/daily_bars.csv"
_DEFAULT_YAHOO_FINANCIALS_PATH = "local_docs/market/yahoo_financials.csv"


def market_prices(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.provider_policy import ensure_provider_allowed
    from investment_assistant.portfolio._market_common import DEFAULT_YAHOO_RATE_LIMIT_POLICY
    from investment_assistant.portfolio.prices import fetch_prices

    tickers = _market_ticker_list(body)
    if not tickers:
        raise ApiError("tickers must be a non-empty list or comma-separated string")
    provider_id = str(body.get("provider_id") or "yfinance")
    runtime_mode = _runtime_mode(body)
    try:
        policy = ensure_provider_allowed(provider_id, runtime_mode=runtime_mode)
    except ValueError as exc:
        raise ApiError(str(exc), status=400) from exc
    rate_limit = (
        DEFAULT_YAHOO_RATE_LIMIT_POLICY
        if provider_id.strip().lower() in _YAHOO_PRICE_PROVIDER_IDS
        else None
    )
    result = fetch_prices(tickers, provider_id=provider_id, rate_limit=rate_limit)
    result["provider_policy"] = policy.to_dict()
    return result


def market_bars(body: JsonDict) -> JsonDict:
    """Compatibility alias for daily Yahoo OHLCV bars."""

    return market_ohlcv(body)


def market_ohlcv(body: JsonDict) -> JsonDict:
    tickers, runtime_mode = _market_universe(body)
    _ensure_market_provider("yfinance", runtime_mode)
    result = cli.run_market_ohlcv(
        tickers=tickers,
        range_=str(body.get("range") or "1mo"),
        interval=str(body.get("interval") or "1d"),
    )
    if _as_bool(body.get("save_csv"), False) or body.get("daily_bars_path"):
        _attach_daily_bars_csv(result, str(body.get("daily_bars_path") or _DEFAULT_DAILY_BARS_PATH))
    return result


def market_bars_universe(body: JsonDict) -> JsonDict:
    """Fetch Yahoo OHLCV for a wider universe and save a consolidated CSV.

    Supported universe inputs:
    - ``tickers``: explicit list/comma-separated string
    - ``registry_path``: EDINET/source registry
    - ``universe``/``scope`` = ``nikkei225``: bundled Nikkei 225 registry
    - ``universe``/``scope`` = ``financials_csv``/``prime``/``all``: tickers from a financial CSV
    """

    runtime_mode = _runtime_mode(body)
    _ensure_market_provider("yfinance", runtime_mode)
    tickers, registry_path, universe_source = _resolve_bars_universe(body)
    max_count = _as_int(body.get("max_count", body.get("limit")), 0)
    result = cli.run_market_ohlcv(
        tickers=tickers or None,
        registry_path=registry_path,
        max_count=max_count,
        range_=str(body.get("range") or "1mo"),
        interval=str(body.get("interval") or "1d"),
    )
    result["universe_source"] = universe_source
    result["max_count"] = max_count
    _attach_daily_bars_csv(result, str(body.get("daily_bars_path") or _DEFAULT_DAILY_BARS_PATH))
    return result


def market_financials(body: JsonDict) -> JsonDict:
    """Fetch Yahoo market fundamentals for explicit tickers or a wider universe."""

    runtime_mode = _runtime_mode(body)
    _ensure_market_provider("yfinance", runtime_mode)
    tickers, registry_path, universe_source = _resolve_bars_universe(body)
    max_count = _as_int(body.get("max_count", body.get("limit")), 0)
    output_path = str(
        body.get("output_path")
        or body.get("financials_path")
        or _DEFAULT_YAHOO_FINANCIALS_PATH
    )
    result = cli.run_market_financials(
        tickers=tickers or None,
        registry_path=registry_path,
        max_count=max_count,
        save=_as_bool(body.get("save_csv"), False) or bool(body.get("output_path")),
        output_path=output_path,
    )
    result["universe_source"] = universe_source
    result["max_count"] = max_count
    return result


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
        raise ApiError("tickers must be a non-empty list or comma-separated string")
    if len(tickers) > _MAX_MARKET_TICKERS:
        raise ApiError(f"too many tickers (max {_MAX_MARKET_TICKERS})")
    return tickers, _runtime_mode(body)


def _runtime_mode(body: JsonDict) -> str:
    return str(
        body.get("runtime_mode")
        or os.getenv("INVESTMENT_ASSISTANT_RUNTIME_MODE")
        or "development"
    )


def _ensure_market_provider(provider_id: str, runtime_mode: str) -> None:
    from investment_assistant.investment.provider_policy import ensure_provider_allowed

    try:
        ensure_provider_allowed(provider_id, runtime_mode=runtime_mode)
    except ValueError as exc:
        raise ApiError(str(exc), status=400) from exc


def _resolve_bars_universe(body: JsonDict) -> tuple[list[str], str | None, str]:
    tickers = _market_ticker_list(body)
    if tickers:
        return tickers, None, "tickers"

    raw_registry = body.get("registry_path")
    if raw_registry:
        return [], str(raw_registry), "registry_path"

    scope = str(body.get("universe") or body.get("scope") or "financials_csv").strip().lower()
    if scope in {"nikkei225", "nikkei_225", "nikkei-225", "日経225"}:
        return [], _DEFAULT_NIKKEI225_REGISTRY, "nikkei225_registry"

    if scope in {
        "financials",
        "financials_csv",
        "all",
        "domestic",
        "prime",
        "tse_prime",
        "東証プライム",
    }:
        path = str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV)
        financial_tickers = _tickers_from_financials_csv(path)
        if not financial_tickers:
            raise ApiError(f"no tickers found in financials_csv: {path}")
        return financial_tickers, None, f"financials_csv:{path}"

    raise ApiError("provide tickers, registry_path, or a supported universe")


def _tickers_from_financials_csv(path: str | Path) -> list[str]:
    from investment_assistant.financials import load_financials

    seen: set[str] = set()
    out: list[str] = []
    for point in load_financials(path):
        ticker = str(point.ticker).strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def _attach_daily_bars_csv(result: JsonDict, path: str) -> None:
    bars = result.get("ohlcv")
    if not isinstance(bars, dict):
        result["daily_bars_path"] = path
        result["daily_bars_count"] = 0
        return

    output_path = reject_path_traversal(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ticker", "date", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        for ticker, rows in bars.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                writer.writerow(
                    {
                        "ticker": str(ticker),
                        "date": row.get("date"),
                        "open": row.get("open"),
                        "high": row.get("high"),
                        "low": row.get("low"),
                        "close": row.get("close"),
                        "volume": row.get("volume"),
                    }
                )
                count += 1
    result["daily_bars_path"] = str(output_path)
    result["daily_bars_count"] = count


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
