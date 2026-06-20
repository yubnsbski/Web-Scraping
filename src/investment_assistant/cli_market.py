"""Market-data CLI runners (Yahoo Finance OHLCV / intraday).

Split out of :mod:`investment_assistant.cli` to keep the entry point small;
``cli`` re-exports :func:`run_market_ohlcv` and :func:`run_yahoo_intraday` so the
public ``investment_assistant.cli.run_*`` API is unchanged.
"""

from __future__ import annotations

import csv
import io
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
DEFAULT_DAILY_BARS_PATH = "local_docs/market/daily_bars.csv"
DEFAULT_MARKET_RAG_DIR = "local_docs/market/rag"

__all__ = [
    "DEFAULT_YAHOO_FINANCIALS_PATH",
    "check_daily_refresh_readiness",
    "run_market_bars_backfill",
    "run_market_daily_refresh",
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
        new_rows = (
            cast("dict[str, dict[str, object]]", financials)
            if isinstance(financials, dict)
            else {}
        )
        # Merge into any previously saved rows so fetching one ticker (or a
        # fetch that returns nothing) never discards tickers scraped earlier.
        merged = {**_read_existing_market_financials(path), **new_rows}
        path.write_text(yahoo_financials_csv_text(merged), encoding="utf-8-sig")
        result["saved"] = True
        result["output_path"] = str(path)
        result["saved_tickers"] = len(merged)
        result["new_or_updated_tickers"] = len(new_rows)
    return result


def _read_existing_market_financials(path: Path) -> dict[str, dict[str, object]]:
    """Load a previously saved Yahoo financials CSV as ``{ticker: metrics}``.

    Lets a fetch merge into (rather than overwrite) the accumulated file, so
    fetching a single ticker — or a fetch that returns nothing — never discards
    rows scraped on earlier runs.
    """

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
    out: dict[str, dict[str, object]] = {}
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿"), newline=""))
    for row in reader:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        out[ticker] = {
            key: value
            for key, value in row.items()
            if key and key != "ticker" and value not in (None, "")
        }
    return out


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


def _write_daily_bars_csv(ohlcv: object, path: str | Path) -> int:
    """Write the inline OHLCV map to a consolidated daily_bars CSV; return rows."""

    out = reject_path_traversal(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["ticker", "date", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        if isinstance(ohlcv, dict):
            for ticker, rows in ohlcv.items():
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
    return count


_BAR_FIELDS = ("ticker", "date", "open", "high", "low", "close", "volume")


def _normalize_bar_ticker(value: str) -> str:
    text = value.strip().upper()
    return text[:-2] if text.endswith(".T") else text


def run_market_bars_backfill(
    *,
    tickers: list[str],
    range_: str = "6mo",
    daily_bars_path: str | Path = DEFAULT_DAILY_BARS_PATH,
    fetch: Callable[[str], str] | None = None,
    rate_limit_policy: MarketFetchPolicy | None = DEFAULT_YAHOO_RATE_LIMIT_POLICY,
) -> dict[str, object]:
    """Fetch OHLCV for ``tickers`` and **merge** them into the daily-bars CSV.

    Unlike the full daily refresh (which rewrites the file), this keeps every
    other ticker already in ``daily_bars.csv`` and only replaces rows for the
    requested codes, so "backfill the missing watch-list names" never wipes the
    accumulated history.
    """

    resolved = [str(t).strip() for t in tickers if str(t).strip()]
    if not resolved:
        return {"tickers_count": 0, "rows_written": 0, "daily_bars_path": str(daily_bars_path)}
    ohlcv_result = run_market_ohlcv(
        tickers=resolved, range_=range_, fetch=fetch, rate_limit_policy=rate_limit_policy
    )
    rows_written = _merge_daily_bars_csv(ohlcv_result.get("ohlcv"), daily_bars_path)
    return {
        "tickers_count": len(resolved),
        "rows_written": rows_written,
        "daily_bars_path": str(daily_bars_path),
        "auto_trading": False,
        "call_real_api": False,
    }


def _merge_daily_bars_csv(ohlcv: object, path: str | Path) -> int:
    """Merge an OHLCV map into the daily-bars CSV; return new rows written.

    Existing rows for the fetched tickers are dropped and replaced; rows for all
    other tickers are preserved.
    """

    out = reject_path_traversal(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Only tickers that actually returned rows replace their history; a ticker
    # that fetched nothing keeps its existing rows (so a transient failure in a
    # daily refresh never wipes yesterday's data — it is retried next run).
    new_tickers = {
        _normalize_bar_ticker(str(ticker))
        for ticker, rows in (ohlcv.items() if isinstance(ohlcv, dict) else [])
        if isinstance(rows, list) and rows
    }
    kept: list[dict[str, str]] = []
    if out.is_file():
        raw = out.read_bytes()
        for encoding in ("utf-8-sig", "cp932", "utf-8"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿"), newline=""))
        for row in reader:
            if _normalize_bar_ticker(str(row.get("ticker") or "")) not in new_tickers:
                kept.append({field: str(row.get(field) or "") for field in _BAR_FIELDS})

    new_rows = 0
    with out.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_BAR_FIELDS))
        writer.writeheader()
        for row in kept:
            writer.writerow(row)
        if isinstance(ohlcv, dict):
            for ticker, rows in ohlcv.items():
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
                    new_rows += 1
    return new_rows


def run_market_daily_refresh(
    *,
    tickers: list[str],
    range_: str = "1y",
    daily_bars_path: str | Path = DEFAULT_DAILY_BARS_PATH,
    financials_path: str | Path = DEFAULT_YAHOO_FINANCIALS_PATH,
    rag_dir: str | Path = DEFAULT_MARKET_RAG_DIR,
    rag_db_path: str | Path | None = None,
    build_rag: bool = True,
    max_count: int = 0,
    fetch: Callable[[str], str] | None = None,
    rate_limit_policy: MarketFetchPolicy | None = DEFAULT_YAHOO_RATE_LIMIT_POLICY,
) -> dict[str, object]:
    """One-shot daily refresh: OHLCV -> daily_bars.csv, financials, RAG rebuild.

    Designed to be scheduled (e.g. Windows Task Scheduler at 07:00) so the latest
    finance data is ready each morning. ``fetch`` is injectable for testing.
    """

    resolved = [str(t).strip() for t in tickers if str(t).strip()]
    if max_count and max_count > 0:
        resolved = resolved[:max_count]

    ohlcv_result = run_market_ohlcv(
        tickers=resolved, range_=range_, fetch=fetch, rate_limit_policy=rate_limit_policy
    )
    # Merge (not overwrite) so a ticker that fails to fetch today keeps its
    # existing bars and is simply retried tomorrow — the daily refresh
    # self-heals transient gaps instead of dropping data on a bad fetch.
    daily_bars_count = _merge_daily_bars_csv(ohlcv_result.get("ohlcv"), daily_bars_path)

    fin_result = run_market_financials(
        tickers=resolved,
        save=True,
        output_path=financials_path,
        fetch=fetch,
        rate_limit_policy=rate_limit_policy,
    )

    # Report what's still missing after this run so the morning log shows the
    # remaining gaps (they are recovered automatically on the next refresh).
    from investment_assistant.portfolio.market_gaps import find_market_gaps

    gaps = find_market_gaps(
        resolved, daily_bars_csv=daily_bars_path, financials_csv=financials_path
    )

    rag_summary: dict[str, object] | None = None
    if build_rag:
        from investment_assistant.portfolio.market_rag import build_market_evidence_docs
        from investment_assistant.rag.indexer import index_directory
        from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH

        db = str(rag_db_path) if rag_db_path is not None else str(DEFAULT_RAG_DB_PATH)
        rag_summary = build_market_evidence_docs(
            financials_csv=financials_path,
            output_dir=rag_dir,
            daily_bars_csv=daily_bars_path,
            include_forecast=True,
        )
        if rag_summary.get("documents_written"):
            rag_summary["index"] = index_directory(path=rag_dir, db_path=db)

    return {
        "tickers_count": len(resolved),
        "range": range_,
        "daily_bars_path": str(daily_bars_path),
        "daily_bars_count": daily_bars_count,
        "financials_path": str(financials_path),
        "financials_matched": fin_result.get("matched_tickers"),
        "gaps": gaps["counts"],
        "missing_any": gaps["missing_any"],
        "rag": rag_summary,
        "auto_trading": False,
        "call_real_api": False,
    }


def check_daily_refresh_readiness(
    *,
    tickers: list[str],
    daily_bars_path: str | Path = DEFAULT_DAILY_BARS_PATH,
    financials_path: str | Path = DEFAULT_YAHOO_FINANCIALS_PATH,
    rag_dir: str | Path = DEFAULT_MARKET_RAG_DIR,
    build_rag: bool = True,
) -> dict[str, object]:
    """Pre-flight for ``market-daily-refresh``: validate config without fetching.

    Lets a user confirm a scheduled job will work (tickers resolve, output paths
    are writable) in a second, instead of waiting for the multi-hour live run.
    """

    resolved = [str(t).strip() for t in tickers if str(t).strip()]
    issues: list[str] = []
    if not resolved:
        issues.append("no tickers resolved (build the universe or pass --tickers)")

    targets: list[tuple[str, Path]] = [
        ("daily_bars", Path(daily_bars_path).parent),
        ("financials", Path(financials_path).parent),
    ]
    if build_rag:
        targets.append(("rag_dir", Path(rag_dir)))
    for label, directory in targets:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - platform-dependent
            issues.append(f"{label} path not writable: {directory} ({exc})")

    return {
        "check": True,
        "tickers_count": len(resolved),
        "build_rag": build_rag,
        "ready": not issues,
        "issues": issues,
        "auto_trading": False,
        "call_real_api": False,
    }
