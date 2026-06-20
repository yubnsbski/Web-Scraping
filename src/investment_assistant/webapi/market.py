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
_DEFAULT_DOMESTIC_UNIVERSE_PATH = "local_docs/market/domestic_universe.csv"
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
    if _as_bool(body.get("index_rag"), False) and result.get("saved"):
        result["rag"] = _index_financials_into_rag(
            str(result.get("output_path") or output_path), body
        )
    return result


def market_forecast(body: JsonDict) -> JsonDict:
    """Forecast next-horizon closes for one ticker from the saved daily-bars CSV."""

    from investment_assistant.portfolio.market_forecast import forecast_ticker

    ticker = str(body.get("ticker") or "").strip()
    if not ticker:
        raise ApiError("ticker is required")
    daily_bars_csv = str(body.get("daily_bars_csv") or _DEFAULT_DAILY_BARS_PATH)
    if not Path(daily_bars_csv).is_file():
        raise ApiError(f"daily bars CSV not found: {daily_bars_csv}")
    try:
        return forecast_ticker(
            daily_bars_csv=daily_bars_csv,
            ticker=ticker,
            horizon=_as_int(body.get("horizon"), 5),
            include_ml=_as_bool(body.get("include_ml"), True),
            evaluate=_as_bool(body.get("evaluate"), True),
        )
    except ValueError as exc:
        raise ApiError(str(exc), status=400) from exc


def market_forecast_screen(body: JsonDict) -> JsonDict:
    """Rank tickers in the daily-bars CSV by forecast expected return."""

    from investment_assistant.portfolio.market_forecast import screen_by_forecast

    daily_bars_csv = str(body.get("daily_bars_csv") or _DEFAULT_DAILY_BARS_PATH)
    if not Path(daily_bars_csv).is_file():
        raise ApiError(f"daily bars CSV not found: {daily_bars_csv}")
    try:
        max_abs = float(body.get("max_abs_return", 30.0))
    except (TypeError, ValueError):
        max_abs = 30.0
    ranked = screen_by_forecast(
        daily_bars_csv,
        horizon=_as_int(body.get("horizon"), 5),
        include_ml=_as_bool(body.get("include_ml"), False),
        top=_as_int(body.get("top"), 50),
        max_abs_return_pct=max_abs,
    )
    return {
        "ranked_count": len(ranked),
        "horizon": _as_int(body.get("horizon"), 5),
        "results": ranked,
        "auto_trading": False,
        "call_real_api": False,
    }


def market_gaps(body: JsonDict) -> JsonDict:
    """Report which requested tickers lack a price and/or enough daily bars."""

    from investment_assistant.portfolio.market_gaps import find_market_gaps

    return find_market_gaps(
        _ticker_list(body),
        daily_bars_csv=str(body.get("daily_bars_csv") or _DEFAULT_DAILY_BARS_PATH),
        financials_csv=str(body.get("market_financials_csv") or _DEFAULT_YAHOO_FINANCIALS_PATH),
    )


def market_backfill(body: JsonDict) -> JsonDict:
    """Fetch only the missing data for the requested tickers (price + daily bars).

    Computes the gaps for the requested watch list, then fetches market
    fundamentals for the price-less codes and OHLCV for the bar-less codes,
    merging both into their CSVs without disturbing other tickers.
    """

    from investment_assistant import cli
    from investment_assistant.portfolio.market_gaps import find_market_gaps

    runtime_mode = _runtime_mode(body)
    _ensure_market_provider("yfinance", runtime_mode)
    daily_bars_csv = str(body.get("daily_bars_csv") or _DEFAULT_DAILY_BARS_PATH)
    financials_csv = str(body.get("market_financials_csv") or _DEFAULT_YAHOO_FINANCIALS_PATH)
    gaps = find_market_gaps(
        _ticker_list(body), daily_bars_csv=daily_bars_csv, financials_csv=financials_csv
    )

    price_result = None
    if gaps["missing_price"]:
        price_result = cli.run_market_financials(
            tickers=list(gaps["missing_price"]),
            save=True,
            output_path=financials_csv,
        )
    bars_result = None
    if gaps["missing_bars"]:
        bars_result = cli.run_market_bars_backfill(
            tickers=list(gaps["missing_bars"]),
            range_=str(body.get("range") or "6mo"),
            daily_bars_path=daily_bars_csv,
        )
    return {
        "gaps_before": gaps,
        "price_backfill": price_result,
        "bars_backfill": bars_result,
        "gaps_after": find_market_gaps(
            _ticker_list(body), daily_bars_csv=daily_bars_csv, financials_csv=financials_csv
        ),
        "auto_trading": False,
        "call_real_api": False,
    }


def _ticker_list(body: JsonDict) -> list[str]:
    raw = body.get("tickers")
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part for part in raw.replace(",", " ").split() if part]
    return []


def market_heatmap(body: JsonDict) -> JsonDict:
    """At-a-glance watch grid: latest close + day-over-day % change per ticker."""

    from investment_assistant.portfolio.market_heatmap import build_market_heatmap

    daily_bars_csv = str(body.get("daily_bars_csv") or _DEFAULT_DAILY_BARS_PATH)
    if not Path(daily_bars_csv).is_file():
        raise ApiError(f"daily bars CSV not found: {daily_bars_csv}")
    raw_tickers = body.get("tickers")
    tickers = (
        [str(item) for item in raw_tickers if str(item).strip()]
        if isinstance(raw_tickers, list)
        else None
    )
    return build_market_heatmap(
        daily_bars_csv,
        tickers=tickers,
        names=_market_financials_names(body),
        sort_by=str(body.get("sort_by") or "change"),
        limit=_as_int(body.get("limit"), 0),
    )


def _market_financials_names(body: JsonDict) -> dict[str, str]:
    """Map ticker -> display name from the scraped Yahoo financials CSV (or empty)."""

    import csv
    import io

    path = Path(str(body.get("market_financials_csv") or _DEFAULT_YAHOO_FINANCIALS_PATH))
    if not path.is_file():
        return {}
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    names: dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿"), newline=""))
    for row in reader:
        ticker = str(row.get("ticker") or row.get("code") or "").strip().upper()
        ticker = ticker[:-2] if ticker.endswith(".T") else ticker
        name = str(row.get("name") or "").strip()
        if ticker and name:
            names.setdefault(ticker, name)
    return names


def _index_financials_into_rag(financials_csv: str, body: JsonDict) -> JsonDict:
    """Build per-ticker RAG evidence from the just-saved financials CSV and index it.

    Lets a normal "市場財務指標の更新" grow the RAG store with no extra step.
    """

    from investment_assistant.portfolio.market_rag import build_market_evidence_docs
    from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH

    if not Path(financials_csv).is_file():
        return {"documents_written": 0, "skipped": "financials_csv_missing"}
    bars = str(body.get("daily_bars_csv") or _DEFAULT_DAILY_BARS_PATH)
    rag = build_market_evidence_docs(
        financials_csv=financials_csv,
        output_dir=str(body.get("rag_output_dir") or "local_docs/market/rag"),
        daily_bars_csv=bars if Path(bars).is_file() else None,
    )
    if rag["documents_written"]:
        rag["index"] = cli.run_rag_index_dir(
            path=rag["output_dir"], db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
        )
    return rag


def market_intraday(body: JsonDict) -> JsonDict:
    tickers, runtime_mode = _market_universe(body)
    _ensure_market_provider("yahoo_jp_intraday", runtime_mode)
    return cli.run_yahoo_intraday(tickers=tickers)


def market_inbox(body: JsonDict) -> JsonDict:
    """Report the manually-dropped price-CSV inbox status (no network)."""

    raw_path = body.get("path")
    return cli.run_market_inbox(path=str(raw_path) if raw_path else None)


def market_rag_build(body: JsonDict) -> JsonDict:
    """Render per-ticker RAG evidence notes from the saved market CSVs and index them.

    Lets the existing data-update flow grow the RAG store from data already
    collected, with no network and no separate CLI step.
    """

    from investment_assistant.portfolio.market_rag import build_market_evidence_docs
    from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH

    financials_csv = str(body.get("financials_csv") or _DEFAULT_YAHOO_FINANCIALS_PATH)
    if not Path(financials_csv).is_file():
        raise ApiError(f"financials CSV not found: {financials_csv}")
    raw_bars = str(body.get("daily_bars_csv") or _DEFAULT_DAILY_BARS_PATH)
    daily_bars_csv = raw_bars if Path(raw_bars).is_file() else None
    output_dir = str(body.get("output_dir") or "local_docs/market/rag")

    result = build_market_evidence_docs(
        financials_csv=financials_csv,
        output_dir=output_dir,
        daily_bars_csv=daily_bars_csv,
    )
    if _as_bool(body.get("index_after_build"), True) and result["documents_written"]:
        db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
        result["index"] = cli.run_rag_index_dir(path=output_dir, db_path=db_path)
    return result


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

    domestic_scopes = {
        "all",
        "domestic",
        "domestic_stocks",
        "stock",
        "prime",
        "tse_prime",
        "東証プライム",
        "standard",
        "growth",
    }
    if scope in domestic_scopes:
        domestic = _tickers_from_domestic_universe(scope)
        if domestic:
            return domestic, None, f"domestic_universe:{scope}"

    if scope in {"financials", "financials_csv"} | domestic_scopes:
        path = str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV)
        financial_tickers = _tickers_from_financials_csv(path)
        if not financial_tickers:
            raise ApiError(f"no tickers found in financials_csv: {path}")
        return financial_tickers, None, f"financials_csv:{path}"

    raise ApiError("provide tickers, registry_path, or a supported universe")


def _tickers_from_domestic_universe(scope: str) -> list[str]:
    """Tickers from the JPX-derived domestic universe CSV, or empty if absent.

    Operators build the CSV once with ``portfolio.jpx_universe`` from JPX's
    public listed-issues file; until then this returns ``[]`` and the caller
    falls back to the financials CSV (preserving prior behavior).
    """

    universe_path = os.getenv("MARKET_DOMESTIC_UNIVERSE_PATH") or _DEFAULT_DOMESTIC_UNIVERSE_PATH
    if not Path(universe_path).is_file():
        return []
    from investment_assistant.portfolio.jpx_universe import load_domestic_universe_tickers

    return load_domestic_universe_tickers(universe_path, scope=scope)


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
