"""HTTP-facing routes for configurable Yahoo! Finance market-data refreshes."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
from investment_assistant.investment.universe import (
    DEFAULT_JPX_LISTED_ISSUES_PATH,
    DEFAULT_NIKKEI225_REGISTRY,
    build_market_universe,
)
from investment_assistant.portfolio.bar_store import DEFAULT_DAILY_BARS_CSV, load_daily_bars
from investment_assistant.portfolio.price_store import (
    DEFAULT_CURRENT_PRICES_CSV,
    load_current_prices,
)
from investment_assistant.portfolio.yahoo_market import (
    ALLOWED_INTERVALS,
    ALLOWED_RANGES,
    DEFAULT_YAHOO_FUNDAMENTALS_CSV,
    load_yahoo_fundamentals,
    normalize_tickers,
    refresh_yahoo_market,
)

JsonDict = dict[str, Any]
_MAX_AUTO_TICKERS = 200
_MAX_CUSTOM_TICKERS = 50
_ROUTES = {
    ("GET", "/api/market/yahoo/status"),
    ("POST", "/api/market/yahoo/status"),
    ("POST", "/api/market/yahoo/refresh"),
}


def handle_yahoo_market_api(
    method: str,
    path: str,
    body: JsonDict | None = None,
) -> tuple[int, JsonDict] | None:
    """Handle Yahoo routes or return ``None`` when the core router should continue."""

    normalized = (method.upper(), path.rstrip("/") or "/")
    if normalized not in _ROUTES:
        return None
    try:
        if normalized[1] == "/api/market/yahoo/status":
            return 200, yahoo_market_status(body or {})
        return 200, yahoo_market_refresh(body or {})
    except (ValueError, KeyError, OSError) as exc:
        return 400, {"error": f"{type(exc).__name__}: {exc}"}


def available_yahoo_market_routes() -> list[str]:
    return sorted(f"{method} {path}" for method, path in _ROUTES)


def yahoo_market_refresh(body: JsonDict) -> JsonDict:
    mode = str(body.get("mode") or "auto").strip().lower()
    tickers, selection = _resolve_tickers(body, mode=mode)
    range_ = str(body.get("range") or "1mo").strip()
    interval = str(body.get("interval") or "1d").strip()
    if range_ not in ALLOWED_RANGES:
        raise ValueError(f"range must be one of: {', '.join(sorted(ALLOWED_RANGES))}")
    if interval not in ALLOWED_INTERVALS:
        raise ValueError(f"interval must be one of: {', '.join(sorted(ALLOWED_INTERVALS))}")

    result = refresh_yahoo_market(
        tickers,
        range_=range_,
        interval=interval,
        fetch_ohlcv=_as_bool(body.get("fetch_ohlcv"), True),
        fetch_fundamentals=_as_bool(body.get("fetch_fundamentals"), True),
        daily_bars_path=str(body.get("daily_bars_path") or DEFAULT_DAILY_BARS_CSV),
        current_prices_path=str(
            body.get("current_prices_path") or DEFAULT_CURRENT_PRICES_CSV
        ),
        fundamentals_path=str(
            body.get("fundamentals_path") or DEFAULT_YAHOO_FUNDAMENTALS_CSV
        ),
    )
    result["mode"] = mode
    result["selection"] = selection
    result["configuration"] = {
        "range": range_,
        "interval": interval,
        "fetch_ohlcv": _as_bool(body.get("fetch_ohlcv"), True),
        "fetch_fundamentals": _as_bool(body.get("fetch_fundamentals"), True),
    }
    return result


def yahoo_market_status(body: JsonDict) -> JsonDict:
    daily_bars_path = Path(str(body.get("daily_bars_path") or DEFAULT_DAILY_BARS_CSV))
    current_prices_path = Path(
        str(body.get("current_prices_path") or DEFAULT_CURRENT_PRICES_CSV)
    )
    fundamentals_path = Path(
        str(body.get("fundamentals_path") or DEFAULT_YAHOO_FUNDAMENTALS_CSV)
    )
    bars = load_daily_bars(daily_bars_path)
    prices = load_current_prices(current_prices_path)
    fundamentals = load_yahoo_fundamentals(fundamentals_path)
    yahoo_bars = [bar for bar in bars if bar.provider_id == "yahoo_finance"]
    yahoo_prices = [
        fact for fact in prices.values() if fact.provider_id == "yahoo_finance"
    ]
    datasets = [
        _dataset_status(
            "ohlcv",
            "株価四本値・出来高",
            daily_bars_path,
            row_count=len(yahoo_bars),
            ticker_count=len({bar.ticker for bar in yahoo_bars}),
        ),
        _dataset_status(
            "current_prices",
            "現在価格",
            current_prices_path,
            row_count=len(yahoo_prices),
            ticker_count=len(yahoo_prices),
        ),
        _dataset_status(
            "fundamentals",
            "市場財務指標",
            fundamentals_path,
            row_count=len(fundamentals),
            ticker_count=len(fundamentals),
        ),
    ]
    ready_count = sum(1 for item in datasets if item["status"] == "ready")
    return {
        "status": "ready" if ready_count == len(datasets) else "partial",
        "provider_id": "yahoo_finance",
        "datasets": datasets,
        "summary": {
            "ready_count": ready_count,
            "missing_count": len(datasets) - ready_count,
        },
        "policy": {
            "personal_use_only": True,
            "robots_checked": True,
            "rate_limited": True,
            "redistribution": False,
            "auto_trading": False,
        },
        "auto_trading": False,
        "call_real_api": False,
    }


def _resolve_tickers(body: JsonDict, *, mode: str) -> tuple[list[str], JsonDict]:
    if mode == "custom":
        tickers = _ticker_list(body.get("tickers"))
        if not tickers:
            raise ValueError("custom mode requires tickers")
        if len(tickers) > _MAX_CUSTOM_TICKERS:
            raise ValueError(f"custom mode supports at most {_MAX_CUSTOM_TICKERS} tickers")
        return tickers, {
            "mode": "custom",
            "selected_count": len(tickers),
            "tickers_sample": tickers[:20],
        }
    if mode != "auto":
        raise ValueError("mode must be auto or custom")

    max_tickers = _bounded_int(body.get("max_tickers"), default=20, maximum=_MAX_AUTO_TICKERS)
    scope = str(body.get("scope") or "nikkei225").strip().lower()
    universe = build_market_universe(
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        jpx_listed_path=str(
            body.get("jpx_listed_path") or DEFAULT_JPX_LISTED_ISSUES_PATH
        ),
        nikkei225_registry=str(
            body.get("nikkei225_registry") or DEFAULT_NIKKEI225_REGISTRY
        ),
        query=str(body.get("query") or ""),
        scope=scope,
        limit=max_tickers,
    )
    raw_rows = universe.get("securities")
    rows = (
        [row for row in raw_rows if isinstance(row, dict)]
        if isinstance(raw_rows, list)
        else []
    )
    tickers = normalize_tickers(
        row.get("ticker") or row.get("code") or "" for row in rows
    )
    if not tickers:
        raise ValueError(
            "automatic selection found no tickers; prepare JPX/EDINET data or use custom mode"
        )
    return tickers, {
        "mode": "auto",
        "scope": scope,
        "selected_count": len(tickers),
        "universe_total_count": _as_int(universe.get("total_count"), len(tickers)),
        "jpx_listed_count": _as_int(universe.get("jpx_listed_count"), 0),
        "nikkei225_count": _as_int(universe.get("nikkei225_count"), 0),
        "financials_count": _as_int(universe.get("financials_count"), 0),
        "tickers_sample": tickers[:20],
        "hint": str(universe.get("hint") or ""),
    }


def _ticker_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw = [item for item in re.split(r"[\s,、，]+", value) if item]
    elif isinstance(value, list):
        raw = [str(item) for item in value]
    else:
        raw = []
    return normalize_tickers(raw)


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_int(value: object, *, default: int, maximum: int) -> int:
    return min(max(_as_int(value, default), 1), maximum)


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _dataset_status(
    key: str,
    label: str,
    path: Path,
    *,
    row_count: int,
    ticker_count: int,
) -> JsonDict:
    modified_at: str | None = None
    if path.is_file():
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    return {
        "key": key,
        "label": label,
        "status": "ready" if row_count > 0 else "missing",
        "path": str(path),
        "row_count": row_count,
        "ticker_count": ticker_count,
        "modified_at": modified_at,
    }
