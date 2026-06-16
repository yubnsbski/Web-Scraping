"""Market-data CLI runners (Yahoo Finance OHLCV / intraday).

Split out of :mod:`investment_assistant.cli` to keep the entry point small;
``cli`` re-exports :func:`run_market_ohlcv` and :func:`run_yahoo_intraday` so the
public ``investment_assistant.cli.run_*`` API is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from investment_assistant.edinet.registry import build_edinet_targets_from_registry
from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.portfolio._market_common import (
    DEFAULT_YAHOO_RATE_LIMIT_POLICY,
    MarketFetchPolicy,
    render_csv,
)

DEFAULT_DAILY_BARS_PATH = "local_docs/market/yahoo_daily_bars.csv"
_DAILY_BARS_FIELDS = ("ticker", "date", "open", "high", "low", "close", "volume")

__all__ = [
    "DEFAULT_DAILY_BARS_PATH",
    "run_market_bars",
    "run_market_financials",
    "run_market_inbox",
    "run_market_ohlcv",
    "run_yahoo_intraday",
]

CsvWriter = Callable[[list[dict[str, object]]], str]


def run_market_financials(
    *,
    tickers: list[str] | None = None,
    registry_path: str | Path | None = None,
    max_count: int = 0,
    fetch: Callable[[str], str] | None = None,
    rate_limit_policy: MarketFetchPolicy | None = DEFAULT_YAHOO_RATE_LIMIT_POLICY,
) -> dict[str, object]:
    """Fetch Yahoo!ファイナンス fundamentals (PER/PBR/yield/EPS/DPS/market cap).

    Same universe expansion and ``max_count`` semantics as the other market
    runners; complements the EDINET financials with market-based metrics.
    """

    from investment_assistant.portfolio.yahoo_financials import fetch_yahoo_financials

    resolved = _resolve_market_tickers(tickers, registry_path)
    if max_count and max_count > 0:
        resolved = resolved[:max_count]
    return fetch_yahoo_financials(resolved, fetch=fetch, rate_limit=rate_limit_policy)


def run_market_bars(
    *,
    tickers: list[str] | None = None,
    registry_path: str | Path | None = None,
    max_count: int = 0,
    save: bool = False,
    output_path: str | Path = DEFAULT_DAILY_BARS_PATH,
    fetch: Callable[[str], str] | None = None,
    rate_limit_policy: MarketFetchPolicy | None = DEFAULT_YAHOO_RATE_LIMIT_POLICY,
) -> dict[str, object]:
    """Bulk-fetch daily OHLCV for a universe and flatten it into one bars table.

    Expands ``tickers`` and/or ``registry_path`` (e.g. a Nikkei 225 / JPX EDINET
    registry), capped by ``max_count`` (``0`` = all), and aggregates every bar
    into rows ``(ticker, date, open, high, low, close, volume)``. With ``save``
    it writes a single ``daily_bars`` CSV. Counts mirror the bulk-update UI.
    """

    from investment_assistant.portfolio.ohlcv import fetch_ohlcv

    resolved = _resolve_market_tickers(tickers, registry_path)
    if max_count and max_count > 0:
        resolved = resolved[:max_count]

    result = fetch_ohlcv(resolved, fetch=fetch, rate_limit=rate_limit_policy)
    series = result.get("ohlcv", {})
    rows: list[dict[str, object]] = []
    matched = 0
    if isinstance(series, dict):
        for ticker, bars in series.items():
            if bars:
                matched += 1
            for bar in bars:
                rows.append({"ticker": ticker, **bar})

    out: dict[str, object] = {
        "provider_id": "yfinance",
        "selected": len(resolved),
        "matched_tickers": matched,
        "rows": len(rows),
        "saved": False,
        "output_path": str(output_path),
        "notes": result.get("notes", {}),
    }
    if save:
        path = reject_path_traversal(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_csv(_DAILY_BARS_FIELDS, rows), encoding="utf-8")
        out["saved"] = True
        out["output_path"] = str(path)
    return out


def run_market_inbox(*, path: str | Path | None = None) -> dict[str, object]:
    """Report the price-inbox file status and the tickers it yields (no network).

    Backs both the UI's「ファイルから反映」action and the daily scheduled check.
    """

    from investment_assistant.portfolio.price_inbox import (
        DEFAULT_INBOX_PATH,
        inbox_status,
    )

    return inbox_status(path if path is not None else DEFAULT_INBOX_PATH)


def _resolve_market_tickers(
    tickers: list[str] | None, registry_path: str | Path | None
) -> list[str]:
    """Expand explicit tickers plus any registry entries into a de-duplicated list."""

    resolved: list[str] = []
    seen: set[str] = set()
    for raw in tickers or []:
        ticker = str(raw).strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            resolved.append(ticker)
    if registry_path is not None:
        for target in build_edinet_targets_from_registry(registry_path):
            ticker = str(target.ticker).strip()
            if ticker and ticker not in seen:
                seen.add(ticker)
                resolved.append(ticker)
    return resolved


def _persist_or_inline(
    result: dict[str, object],
    *,
    output_dir: str | Path | None,
    series_key: str,
    csv_writer: CsvWriter,
) -> dict[str, object]:
    """With ``output_dir`` set, write one ``<ticker>.csv`` per ticker and drop the
    bulky inline series from ``result``; otherwise return ``result`` unchanged."""

    if output_dir is None:
        return result
    base = reject_path_traversal(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    series = result.pop(series_key)
    saved: list[str] = []
    if isinstance(series, dict):
        for ticker, rows in series.items():
            path = base / f"{ticker}.csv"
            path.write_text(csv_writer(rows), encoding="utf-8")
            saved.append(str(path))
    result["output_dir"] = str(base)
    result["saved_paths"] = saved
    return result


def run_market_ohlcv(
    *,
    tickers: list[str] | None = None,
    registry_path: str | Path | None = None,
    max_count: int = 0,
    range_: str = "1mo",
    interval: str = "1d",
    output_dir: str | Path | None = None,
    fetch: Callable[[str], str] | None = None,
    rate_limit_policy: MarketFetchPolicy | None = DEFAULT_YAHOO_RATE_LIMIT_POLICY,
) -> dict[str, object]:
    """Scrape daily OHLCV from Yahoo Finance for explicit tickers or a registry.

    Tickers come from ``tickers`` and/or every eligible entry in ``registry_path``
    (e.g. a Nikkei 225 / JPX EDINET registry). ``max_count`` caps the universe
    (``0`` = all). With ``output_dir`` set, one ``<ticker>.csv`` is written per
    ticker and the bulky inline series is omitted from the return value.
    """

    from investment_assistant.portfolio.ohlcv import fetch_ohlcv, ohlcv_csv_text

    resolved = _resolve_market_tickers(tickers, registry_path)
    if max_count and max_count > 0:
        resolved = resolved[:max_count]

    result = fetch_ohlcv(
        resolved,
        range_=range_,
        interval=interval,
        fetch=fetch,
        rate_limit=rate_limit_policy,
    )
    result["tickers_count"] = len(resolved)
    return _persist_or_inline(
        result, output_dir=output_dir, series_key="ohlcv", csv_writer=ohlcv_csv_text
    )


def run_yahoo_intraday(
    *,
    tickers: list[str] | None = None,
    registry_path: str | Path | None = None,
    max_count: int = 0,
    output_dir: str | Path | None = None,
    fetch: Callable[[str], str] | None = None,
    rate_limit_policy: MarketFetchPolicy | None = DEFAULT_YAHOO_RATE_LIMIT_POLICY,
) -> dict[str, object]:
    """Scrape today's minute-bar series from Yahoo Finance Japan.

    Same universe expansion as :func:`run_market_ohlcv` (explicit ``tickers``
    and/or a registry, capped by ``max_count`` where ``0`` = all). With
    ``output_dir`` set, one ``<ticker>.csv`` is written per ticker and the inline
    series is omitted from the return value.
    """

    from investment_assistant.portfolio.yahoo_intraday import (
        fetch_yahoo_intraday,
        intraday_csv_text,
    )

    resolved = _resolve_market_tickers(tickers, registry_path)
    if max_count and max_count > 0:
        resolved = resolved[:max_count]

    result = fetch_yahoo_intraday(resolved, fetch=fetch, rate_limit=rate_limit_policy)
    result["tickers_count"] = len(resolved)
    return _persist_or_inline(
        result, output_dir=output_dir, series_key="intraday", csv_writer=intraday_csv_text
    )
