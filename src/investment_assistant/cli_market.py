"""Market-data CLI runners (Yahoo Finance OHLCV / intraday).

Split out of :mod:`investment_assistant.cli` to keep the entry point small;
``cli`` re-exports :func:`run_market_ohlcv` and :func:`run_yahoo_intraday` so the
public ``investment_assistant.cli.run_*`` API is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from investment_assistant.edinet.registry import build_edinet_targets_from_registry
from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.portfolio._market_common import (
    DEFAULT_YAHOO_RATE_LIMIT_POLICY,
    MarketFetchPolicy,
)

DEFAULT_YAHOO_FINANCIALS_PATH = "local_docs/market/yahoo_financials.csv"

__all__ = [
    "DEFAULT_YAHOO_FINANCIALS_PATH",
    "run_market_financials",
    "run_market_inbox",
    "run_market_ohlcv",
    "run_yahoo_intraday",
]

CsvWriter = Callable[[list[dict[str, object]]], str]


def run_market_inbox(*, path: str | Path | None = None) -> dict[str, object]:
    """Report the manually-dropped price-CSV inbox status (no network).

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


def run_market_financials(
    *,
    tickers: list[str] | None = None,
    registry_path: str | Path | None = None,
    max_count: int = 0,
    save: bool = False,
    output_path: str | Path = DEFAULT_YAHOO_FINANCIALS_PATH,
    fetch: Callable[[str], str] | None = None,
    rate_limit_policy: MarketFetchPolicy | None = DEFAULT_YAHOO_RATE_LIMIT_POLICY,
) -> dict[str, object]:
    """Fetch Yahoo market fundamentals for explicit tickers or a registry."""

    from investment_assistant.portfolio.yahoo_financials import (
        fetch_yahoo_financials,
        yahoo_financials_csv_text,
    )

    resolved = _resolve_market_tickers(tickers, registry_path)
    if max_count and max_count > 0:
        resolved = resolved[:max_count]

    result = fetch_yahoo_financials(
        resolved,
        fetch=fetch,
        rate_limit=rate_limit_policy,
    )
    result["tickers_count"] = len(resolved)
    result["saved"] = False
    result["output_path"] = str(output_path)
    if save:
        path = reject_path_traversal(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        financials = result.get("financials")
        if isinstance(financials, dict):
            path.write_text(
                yahoo_financials_csv_text(
                    cast("dict[str, dict[str, object]]", financials)
                ),
                encoding="utf-8-sig",
            )
        else:
            path.write_text(yahoo_financials_csv_text({}), encoding="utf-8-sig")
        result["saved"] = True
        result["output_path"] = str(path)
    return result


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
