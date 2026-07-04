"""Read-only data inventory for the local investment dashboard."""

from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from investment_assistant.financials import load_financials
from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
from investment_assistant.financials.loader import DISCLAIMER
from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.portfolio.price_inbox import DEFAULT_INBOX_PATH
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH

JsonDict = dict[str, Any]

_DEFAULT_CURRENT_PRICES_PATH = "local_docs/market/current_prices.csv"
_DEFAULT_DAILY_BARS_PATH = "local_docs/market/daily_bars.csv"
_DEFAULT_YAHOO_FINANCIALS_PATH = "local_docs/market/yahoo_financials.csv"
_DEFAULT_EDINET_FINANCIALS_PATH = "local_docs/edinet/financials.csv"
_DEFAULT_MARKET_LOG_PATH = "local_docs/logs/market_fetch.log"
_DEFAULT_JPX_LISTED_ISSUES_PATH = "local_docs/jpx/listed_issues.csv"
_DEFAULT_COMPANY_MASTER_PATH = "local_docs/company_master/company_master.csv"
_DEFAULT_DOMESTIC_UNIVERSE_PATH = "local_docs/market/domestic_universe.csv"

_TICKER_COLUMNS = ("ticker", "code", "\u30b3\u30fc\u30c9", "ticker_or_fund_code", "fund_code")
_DATE_COLUMNS = ("price_as_of", "as_of", "date", "\u65e5\u4ed8", "period_end", "fiscal_year")


def data_status(body: JsonDict) -> JsonDict:
    """Return file-level data health without fetching or mutating anything."""

    selected_financials = _path_from_body(body, "financials_csv", str(DEFAULT_FINANCIALS_CSV))
    datasets = [
        _csv_dataset(
            dataset_id="selected_financials",
            label="選択中の財務CSV",
            path=selected_financials,
            provider="EDINET / 手入力 / サンプル",
            role="保有分析・候補抽出・レポートの基礎",
            freshness_days=30,
            required=True,
        ),
        _csv_dataset(
            dataset_id="jpx_listed_issues",
            label="JPX上場一覧",
            path=_path_from_body(body, "jpx_listed_issues_path", _DEFAULT_JPX_LISTED_ISSUES_PATH),
            provider="JPX",
            role="東証上場銘柄数と市場区分の基準",
            freshness_days=45,
            required=False,
        ),
        _csv_dataset(
            dataset_id="company_master",
            label="会社マスター",
            path=_path_from_body(body, "company_master_path", _DEFAULT_COMPANY_MASTER_PATH),
            provider="JPX派生ローカルCSV",
            role="証券コード、社名、市場区分、国内株式フラグの基準",
            freshness_days=45,
            required=False,
        ),
        _csv_dataset(
            dataset_id="market_financials",
            label="市場財務指標",
            path=_path_from_body(body, "market_financials_path", _DEFAULT_YAHOO_FINANCIALS_PATH),
            provider="Yahoo! ファイナンス",
            role="株価・PBR・DPS・配当利回りの補完",
            freshness_days=3,
            required=False,
        ),
        _csv_dataset(
            dataset_id="daily_bars",
            label="株価四本値・出来高",
            path=_path_from_body(body, "daily_bars_path", _DEFAULT_DAILY_BARS_PATH),
            provider="Yahoo! ファイナンス",
            role="価格系列、出来高、簡易トレンド確認",
            freshness_days=3,
            required=False,
        ),
        _csv_dataset(
            dataset_id="price_inbox",
            label="手動価格CSV",
            path=_path_from_body(body, "price_inbox_path", str(DEFAULT_INBOX_PATH)),
            provider="ユーザーCSV",
            role="スクレイピングできない場合の手動補完",
            freshness_days=7,
            required=False,
        ),
        _csv_dataset(
            dataset_id="edinet_financials",
            label="EDINET財務CSV",
            path=_path_from_body(body, "edinet_financials_path", _DEFAULT_EDINET_FINANCIALS_PATH),
            provider="金融庁 EDINET",
            role="営業CF・自己資本比率・配当履歴の基礎",
            freshness_days=30,
            required=False,
        ),
        _sqlite_dataset(
            dataset_id="rag_db",
            label="RAG検索DB",
            path=_path_from_body(body, "rag_db_path", str(DEFAULT_RAG_DB_PATH)),
            provider="ローカルSQLite",
            role="根拠検索、引用確認、AI確認",
            freshness_days=30,
            required=False,
        ),
        _log_dataset(
            dataset_id="market_fetch_log",
            label="市場取得ログ",
            path=_path_from_body(body, "market_log_path", _DEFAULT_MARKET_LOG_PATH),
            provider="ローカルログ",
            role="429対策、リトライ、失敗銘柄の追跡",
            freshness_days=7,
            required=False,
        ),
    ]

    _annotate_daily_bars_coverage(datasets)
    actions = _refresh_actions(datasets)
    summary = _summary(datasets, actions=actions)
    return {
        "status": summary["overall_status"],
        "checked_at": _now_iso(),
        "summary": summary,
        "datasets": datasets,
        "actions": actions,
        "auto_trading": False,
        "call_real_api": False,
    }


def data_quality_profile(body: JsonDict) -> JsonDict:
    """Profile local market data quality against the latest JPX universe.

    This is read-only: it never fetches external data and never mutates local CSVs.
    """

    sources = {
        "jpx_listed_issues": _quality_load_csv(
            _path_from_body(body, "jpx_listed_issues_path", _DEFAULT_JPX_LISTED_ISSUES_PATH),
            freshness_days=45,
        ),
        "company_master": _quality_load_csv(
            _path_from_body(body, "company_master_path", _DEFAULT_COMPANY_MASTER_PATH),
            freshness_days=45,
        ),
        "domestic_universe": _quality_load_csv(
            _path_from_body(body, "domestic_universe_path", _DEFAULT_DOMESTIC_UNIVERSE_PATH),
            freshness_days=45,
        ),
        "current_prices": _quality_load_csv(
            _path_from_body(body, "current_prices_path", _DEFAULT_CURRENT_PRICES_PATH),
            freshness_days=3,
        ),
        "market_financials": _quality_load_csv(
            _path_from_body(body, "market_financials_path", _DEFAULT_YAHOO_FINANCIALS_PATH),
            freshness_days=7,
        ),
        "daily_bars": _quality_load_csv(
            _path_from_body(body, "daily_bars_path", _DEFAULT_DAILY_BARS_PATH),
            freshness_days=7,
        ),
    }

    jpx_rows = _quality_rows(sources["jpx_listed_issues"])
    company_rows = _quality_rows(sources["company_master"])
    universe_rows = _quality_rows(sources["domestic_universe"])
    price_rows = _quality_rows(sources["current_prices"])
    financial_rows = _quality_rows(sources["market_financials"])
    bar_rows = _quality_rows(sources["daily_bars"])

    jpx_all = {_normalize_ticker(v) for v in _unique_values(jpx_rows, _TICKER_COLUMNS)}
    jpx_domestic = _jpx_domestic_tickers(jpx_rows)
    company_all = {_normalize_ticker(v) for v in _unique_values(company_rows, _TICKER_COLUMNS)}
    company_domestic = _company_domestic_tickers(company_rows)
    universe_tickers = {
        _normalize_ticker(v) for v in _unique_values(universe_rows, _TICKER_COLUMNS)
    }
    price_tickers = {_normalize_ticker(v) for v in _unique_values(price_rows, _TICKER_COLUMNS)}
    financial_tickers = {
        _normalize_ticker(v) for v in _unique_values(financial_rows, _TICKER_COLUMNS)
    }
    bar_tickers = {_normalize_ticker(v) for v in _unique_values(bar_rows, _TICKER_COLUMNS)}

    price_outside_jpx = price_tickers - jpx_all
    financial_outside_jpx = financial_tickers - jpx_all
    bars_outside_jpx = bar_tickers - jpx_all
    current_missing = jpx_domestic - price_tickers
    financial_missing = jpx_domestic - financial_tickers
    bars_missing = jpx_domestic - bar_tickers
    company_missing = jpx_all - company_all
    company_extra = company_all - jpx_all
    universe_missing = jpx_domestic - universe_tickers
    universe_extra = universe_tickers - jpx_domestic

    price_coverage = _coverage_metrics(jpx_domestic, price_tickers, "current_prices")
    financial_coverage = _coverage_metrics(jpx_domestic, financial_tickers, "market_financials")
    bars_coverage = _coverage_metrics(jpx_domestic, bar_tickers, "daily_bars")

    accuracy_off_universe = (
        len(price_outside_jpx) + len(financial_outside_jpx) + len(bars_outside_jpx)
    )
    completeness_score = round(
        (
            price_coverage["current_prices_coverage_percent"]
            + financial_coverage["market_financials_coverage_percent"]
            + bars_coverage["daily_bars_coverage_percent"]
        )
        / 3.0,
        2,
    )
    consistency_gap = (
        len(company_missing) + len(company_extra) + len(universe_missing) + len(universe_extra)
    )
    duplicate_metrics = {
        "jpx_duplicate_code_count": _duplicate_key_count(
            jpx_rows, ("\u30b3\u30fc\u30c9", "code", "ticker")
        ),
        "company_master_duplicate_ticker_count": _duplicate_key_count(
            company_rows, _TICKER_COLUMNS
        ),
        "domestic_universe_duplicate_ticker_count": _duplicate_key_count(
            universe_rows, _TICKER_COLUMNS
        ),
        "current_prices_duplicate_ticker_count": _duplicate_key_count(price_rows, _TICKER_COLUMNS),
        "market_financials_duplicate_ticker_count": _duplicate_key_count(
            financial_rows, _TICKER_COLUMNS
        ),
        "daily_bars_duplicate_ticker_date_count": _duplicate_key_count(
            bar_rows, ("ticker", "date")
        ),
    }
    invalid_tickers_by_source = {
        "jpx_listed_issues": _invalid_ticker_samples(jpx_rows),
        "company_master": _invalid_ticker_samples(company_rows),
        "domestic_universe": _invalid_ticker_samples(universe_rows),
        "current_prices": _invalid_ticker_samples(price_rows),
        "market_financials": _invalid_ticker_samples(financial_rows),
        "daily_bars": _invalid_ticker_samples(bar_rows),
    }
    invalid_metrics = {
        "jpx_invalid_ticker_count": len(invalid_tickers_by_source["jpx_listed_issues"]),
        "company_master_invalid_ticker_count": len(
            invalid_tickers_by_source["company_master"]
        ),
        "domestic_universe_invalid_ticker_count": len(
            invalid_tickers_by_source["domestic_universe"]
        ),
        "current_prices_invalid_ticker_count": len(
            invalid_tickers_by_source["current_prices"]
        ),
        "market_financials_invalid_ticker_count": len(
            invalid_tickers_by_source["market_financials"]
        ),
        "daily_bars_invalid_ticker_count": len(invalid_tickers_by_source["daily_bars"]),
    }
    stale_or_missing = [
        dataset_id
        for dataset_id, source in sources.items()
        if str(source.get("status")) in {"missing", "empty", "error", "stale"}
    ]

    dimensions = [
        _quality_dimension(
            dimension_id="accuracy",
            label="Accuracy",
            status="needs_attention" if accuracy_off_universe else "pass",
            score=max(0.0, 100.0 - min(50.0, accuracy_off_universe * 2.0)),
            metrics={
                "current_prices_outside_jpx_all_count": len(price_outside_jpx),
                "market_financials_outside_jpx_all_count": len(financial_outside_jpx),
                "daily_bars_outside_jpx_all_count": len(bars_outside_jpx),
                "current_prices_outside_jpx_all_sample": _sample_values(price_outside_jpx),
                "market_financials_outside_jpx_all_sample": _sample_values(financial_outside_jpx),
                "daily_bars_outside_jpx_all_sample": _sample_values(bars_outside_jpx),
            },
            observations=[
                "Compares Yahoo-derived datasets with the official JPX listed-issues universe.",
            ],
            actions=["Review off-universe Yahoo tickers before treating them as current listings."],
        ),
        _quality_dimension(
            dimension_id="completeness",
            label="Completeness",
            status="needs_attention"
            if current_missing or financial_missing or bars_missing
            else "pass",
            score=completeness_score,
            metrics={
                **price_coverage,
                **financial_coverage,
                **bars_coverage,
                "current_prices_missing_from_jpx_domestic_sample": _sample_values(current_missing),
                "market_financials_missing_from_jpx_domestic_sample": _sample_values(
                    financial_missing
                ),
                "daily_bars_missing_from_jpx_domestic_sample": _sample_values(bars_missing),
            },
            observations=[
                "Measures coverage against JPX domestic stocks, "
                "not against stale local Yahoo rows.",
            ],
            actions=[
                "Backfill missing JPX domestic tickers in Yahoo price, financial, or OHLCV data."
            ],
        ),
        _quality_dimension(
            dimension_id="consistency",
            label="Consistency",
            status="needs_attention" if consistency_gap else "pass",
            score=max(0.0, 100.0 - min(50.0, consistency_gap * 2.0)),
            metrics={
                "company_master_missing_jpx_all_count": len(company_missing),
                "company_master_extra_vs_jpx_all_count": len(company_extra),
                "domestic_universe_missing_jpx_domestic_count": len(universe_missing),
                "domestic_universe_extra_vs_jpx_domestic_count": len(universe_extra),
                "company_master_domestic_count": len(company_domestic),
                "company_master_missing_jpx_all_sample": _sample_values(company_missing),
                "company_master_extra_vs_jpx_all_sample": _sample_values(company_extra),
                "domestic_universe_missing_jpx_domestic_sample": _sample_values(universe_missing),
                "domestic_universe_extra_vs_jpx_domestic_sample": _sample_values(universe_extra),
            },
            observations=["Checks whether local master files agree with the JPX source of truth."],
            actions=[
                "Regenerate company_master and domestic_universe from JPX when counts diverge."
            ],
        ),
        _quality_dimension(
            dimension_id="timeliness",
            label="Timeliness",
            status="needs_attention" if stale_or_missing else "pass",
            score=max(0.0, 100.0 - min(60.0, len(stale_or_missing) * 12.0)),
            metrics={
                "stale_or_missing_dataset_count": len(stale_or_missing),
                "stale_or_missing_datasets": stale_or_missing,
                "latest_values": {
                    key: source.get("latest_value") for key, source in sources.items()
                },
            },
            observations=[
                "Uses local file age and latest values only; no network fetch is performed."
            ],
            actions=["Refresh stale datasets before analysis screens or reports."],
        ),
        _quality_dimension(
            dimension_id="uniqueness",
            label="Uniqueness",
            status="needs_attention" if any(duplicate_metrics.values()) else "pass",
            score=max(0.0, 100.0 - min(60.0, sum(duplicate_metrics.values()) * 3.0)),
            metrics=duplicate_metrics,
            observations=["Detects duplicate master rows and duplicate OHLCV ticker-date keys."],
            actions=["Deduplicate primary keys before registering data into RAG or scoring."],
        ),
        _quality_dimension(
            dimension_id="validity",
            label="Validity",
            status="needs_attention" if any(invalid_metrics.values()) else "pass",
            score=max(0.0, 100.0 - min(60.0, sum(invalid_metrics.values()) * 3.0)),
            metrics={
                **invalid_metrics,
                "accepted_ticker_rule": (
                    "4-5 uppercase alphanumeric characters; supports newer "
                    "JPX codes such as 130A and 92015."
                ),
                "invalid_ticker_samples": {
                    key: values[:10] for key, values in invalid_tickers_by_source.items()
                },
            },
            observations=[
                "Validates ticker shape without rejecting JPX alphanumeric and 5-character codes."
            ],
            actions=["Normalize or quarantine invalid ticker rows before downstream use."],
        ),
    ]

    needs_attention = [item for item in dimensions if item["status"] != "pass"]
    recommended_actions = _unique_ordered(
        action for item in needs_attention for action in item.get("recommended_actions", [])
    )
    return {
        "status": "pass" if not needs_attention else "needs_attention",
        "checked_at": _now_iso(),
        "summary": {
            "dimension_count": len(dimensions),
            "pass_count": len(dimensions) - len(needs_attention),
            "needs_attention_count": len(needs_attention),
            "jpx_all_count": len(jpx_all),
            "jpx_domestic_stock_count": len(jpx_domestic),
            "recommended_action_count": len(recommended_actions),
        },
        "sources": {key: _quality_source_summary(value) for key, value in sources.items()},
        "dimensions": dimensions,
        "recommended_actions": recommended_actions,
        "write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
    }


def financials_preview(body: JsonDict) -> JsonDict:
    """Return a compact, read-only preview of the selected financial CSV."""

    path = _path_from_body(body, "financials_csv", str(DEFAULT_FINANCIALS_CSV))
    limit = max(1, min(_as_int(body.get("limit"), 25), 200))
    if not path.exists():
        return {
            "status": "missing",
            "path": str(path),
            "row_count": 0,
            "company_count": 0,
            "rows": [],
            "warnings": ["財務CSVが見つかりません。EDINET取得またはCSVパスを確認してください。"],
            "disclaimer": DISCLAIMER,
            "auto_trading": False,
            "call_real_api": False,
        }

    try:
        points = load_financials(path)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        return {
            "status": "error",
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
            "row_count": 0,
            "company_count": 0,
            "rows": [],
            "warnings": ["財務CSVを読み取れません。列名・文字コード・数値形式を確認してください。"],
            "disclaimer": DISCLAIMER,
            "auto_trading": False,
            "call_real_api": False,
        }

    latest_by_ticker: dict[str, JsonDict] = {}
    fiscal_years: set[int] = set()
    for point in points:
        fiscal_years.add(point.fiscal_year)
        current = latest_by_ticker.get(point.ticker)
        if current is not None and int(current["fiscal_year"]) >= point.fiscal_year:
            continue
        latest_by_ticker[point.ticker] = {
            "ticker": point.ticker,
            "name": point.name,
            "fiscal_year": point.fiscal_year,
            "operating_cf": point.operating_cf,
            "equity_ratio": point.equity_ratio,
            "dividend_per_share": point.dividend_per_share,
            "payout_policy": point.payout_policy,
            "available_fields": {
                "operating_cf": True,
                "equity_ratio": True,
                "dividend_per_share": True,
            },
        }

    rows = sorted(latest_by_ticker.values(), key=lambda item: str(item["ticker"]))
    status = "ready" if rows else "empty"
    warnings: list[str] = []
    if not rows:
        warnings.append("財務CSVに表示できる銘柄行がありません。")
    if len(rows) > limit:
        warnings.append(f"表示は先頭{limit}件です。全体は{len(rows)}銘柄あります。")

    return {
        "status": status,
        "path": str(path),
        "row_count": len(points),
        "company_count": len(rows),
        "fiscal_years": sorted(fiscal_years, reverse=True)[:8],
        "rows": rows[:limit],
        "limit": limit,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
        "auto_trading": False,
        "call_real_api": False,
    }


def _quality_load_csv(path: Path, *, freshness_days: int) -> JsonDict:
    if not path.exists():
        return {
            "status": "missing",
            "path": str(path),
            "row_count": 0,
            "column_count": 0,
            "columns": [],
            "rows": [],
            "freshness_days": freshness_days,
        }
    try:
        rows, columns = _read_csv_rows(path)
    except (OSError, UnicodeError, csv.Error) as exc:
        return {
            "status": "error",
            "path": str(path),
            "row_count": 0,
            "column_count": 0,
            "columns": [],
            "rows": [],
            "freshness_days": freshness_days,
            "error": f"{type(exc).__name__}: {exc}",
        }
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    age_hours = max(0.0, (datetime.now(UTC) - modified_at).total_seconds() / 3600.0)
    status = _freshness_status(
        age_hours=age_hours, freshness_days=freshness_days, row_count=len(rows)
    )
    return {
        "status": status,
        "path": str(path),
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": columns[:12],
        "rows": rows,
        "ticker_count": len({_normalize_ticker(v) for v in _unique_values(rows, _TICKER_COLUMNS)}),
        "latest_value": _latest_value(rows, _DATE_COLUMNS),
        "freshness_days": freshness_days,
        "modified_at": modified_at.isoformat().replace("+00:00", "Z"),
        "age_hours": round(age_hours, 2),
    }


def _quality_rows(source: JsonDict) -> list[JsonDict]:
    rows = source.get("rows")
    return rows if isinstance(rows, list) else []


def _quality_source_summary(source: JsonDict) -> JsonDict:
    return {key: value for key, value in source.items() if key not in {"rows"}}


def _quality_dimension(
    *,
    dimension_id: str,
    label: str,
    status: str,
    score: float,
    metrics: JsonDict,
    observations: list[str],
    actions: list[str],
) -> JsonDict:
    return {
        "id": dimension_id,
        "label": label,
        "status": status,
        "score": round(float(score), 2),
        "metrics": metrics,
        "observations": observations,
        "recommended_actions": actions if status != "pass" else [],
    }


def _jpx_domestic_tickers(rows: Iterable[JsonDict]) -> set[str]:
    tickers: set[str] = set()
    for row in rows:
        segment = _row_first_value(
            row,
            ("\u5e02\u5834\u30fb\u5546\u54c1\u533a\u5206", "market_segment_raw", "market_segment"),
        )
        ticker = _row_first_value(row, _TICKER_COLUMNS)
        if ticker and "\u5185\u56fd\u682a\u5f0f" in segment:
            tickers.add(_normalize_ticker(ticker))
    return tickers


def _company_domestic_tickers(rows: Iterable[JsonDict]) -> set[str]:
    tickers: set[str] = set()
    for row in rows:
        ticker = _row_first_value(row, _TICKER_COLUMNS)
        if not ticker:
            continue
        segment = _row_first_value(
            row,
            ("market_segment_raw", "market_segment", "\u5e02\u5834\u30fb\u5546\u54c1\u533a\u5206"),
        )
        if _truthy(row.get("is_domestic_stock")) or "\u5185\u56fd\u682a\u5f0f" in segment:
            tickers.add(_normalize_ticker(ticker))
    return tickers


def _coverage_metrics(reference: set[str], covered: set[str], prefix: str) -> JsonDict:
    overlap = reference & covered
    missing = reference - covered
    percent = round((len(overlap) / len(reference) * 100.0), 2) if reference else 0.0
    return {
        f"{prefix}_reference_count": len(reference),
        f"{prefix}_covered_count": len(overlap),
        f"{prefix}_missing_count": len(missing),
        f"{prefix}_coverage_percent": percent,
    }


def _duplicate_key_count(rows: Iterable[JsonDict], columns: tuple[str, ...]) -> int:
    counter: Counter[str] = Counter()
    for row in rows:
        if len(columns) == 1:
            key = _row_first_value(row, columns)
        else:
            parts = [_row_first_value(row, (column,)) for column in columns]
            key = "|".join(
                _normalize_ticker(part) if index == 0 else part for index, part in enumerate(parts)
            )
        if key and key.strip("|"):
            counter[key] += 1
    return sum(1 for count in counter.values() if count > 1)


def _invalid_ticker_samples(rows: Iterable[JsonDict], *, limit: int | None = None) -> list[str]:
    """Return unique invalid tickers, in first-seen order.

    ``limit`` caps the number of results collected; ``None`` collects all of
    them (used when the caller needs a count as well as a sample).
    """

    invalid: list[str] = []
    seen: set[str] = set()
    for row in rows:
        raw = _row_first_value(row, _TICKER_COLUMNS)
        if not raw:
            continue
        ticker = _normalize_ticker(raw)
        if ticker in seen or _valid_ticker(ticker):
            continue
        invalid.append(ticker)
        seen.add(ticker)
        if limit is not None and len(invalid) >= limit:
            break
    return invalid


def _row_first_value(row: JsonDict, columns: tuple[str, ...]) -> str:
    for column in columns:
        value = str(row.get(column) or "").strip()
        if value:
            return value
    return ""


def _normalize_ticker(value: str) -> str:
    return str(value or "").strip().upper()


def _valid_ticker(value: str) -> bool:
    ticker = _normalize_ticker(value)
    return 4 <= len(ticker) <= 5 and ticker.isalnum()


def _sample_values(values: set[str], *, limit: int = 10) -> list[str]:
    return sorted(values)[:limit]


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _unique_ordered(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _csv_dataset(
    *,
    dataset_id: str,
    label: str,
    path: Path,
    provider: str,
    role: str,
    freshness_days: int,
    required: bool,
) -> JsonDict:
    base = _base_dataset(
        dataset_id=dataset_id,
        label=label,
        path=path,
        kind="csv",
        provider=provider,
        role=role,
        freshness_days=freshness_days,
        required=required,
    )
    if base["status"] == "missing":
        return base
    try:
        rows, columns = _read_csv_rows(path)
        tickers = _unique_values(
            rows, ("ticker", "code", "コード", "ticker_or_fund_code", "fund_code")
        )
        latest = _latest_value(
            rows, ("price_as_of", "as_of", "date", "日付", "period_end", "fiscal_year")
        )
        base.update(
            {
                "row_count": len(rows),
                "column_count": len(columns),
                "columns": columns[:12],
                "ticker_count": len(tickers),
                "latest_value": latest,
            }
        )
        base["status"] = _status_for_existing(base, row_count=len(rows))
    except (OSError, UnicodeError, csv.Error) as exc:
        base.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return base


def _sqlite_dataset(
    *,
    dataset_id: str,
    label: str,
    path: Path,
    provider: str,
    role: str,
    freshness_days: int,
    required: bool,
) -> JsonDict:
    base = _base_dataset(
        dataset_id=dataset_id,
        label=label,
        path=path,
        kind="sqlite",
        provider=provider,
        role=role,
        freshness_days=freshness_days,
        required=required,
    )
    if base["status"] == "missing":
        return base
    try:
        tables: dict[str, int] = {}
        with sqlite3.connect(path) as conn:
            table_rows = conn.execute(
                "select name from sqlite_master where type = 'table' order by name"
            ).fetchall()
            for (name,) in table_rows:
                if isinstance(name, str) and _safe_sqlite_identifier(name):
                    count = conn.execute(f'select count(*) from "{name}"').fetchone()[0]
                    tables[name] = int(count)
        base.update(
            {"table_count": len(tables), "tables": tables, "row_count": sum(tables.values())}
        )
        base["status"] = _status_for_existing(base, row_count=sum(tables.values()))
    except sqlite3.DatabaseError as exc:
        base.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return base


def _log_dataset(
    *,
    dataset_id: str,
    label: str,
    path: Path,
    provider: str,
    role: str,
    freshness_days: int,
    required: bool,
) -> JsonDict:
    base = _base_dataset(
        dataset_id=dataset_id,
        label=label,
        path=path,
        kind="log",
        provider=provider,
        role=role,
        freshness_days=freshness_days,
        required=required,
    )
    if base["status"] == "missing":
        return base
    try:
        lines = _read_text_lines(path, max_lines=6)
        base.update({"line_count": _count_lines(path), "tail": lines})
        base["status"] = _status_for_existing(base, row_count=int(base["line_count"]))
    except (OSError, UnicodeError) as exc:
        base.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return base


def _base_dataset(
    *,
    dataset_id: str,
    label: str,
    path: Path,
    kind: str,
    provider: str,
    role: str,
    freshness_days: int,
    required: bool,
) -> JsonDict:
    item: JsonDict = {
        "id": dataset_id,
        "label": label,
        "kind": kind,
        "path": str(path),
        "provider": provider,
        "role": role,
        "required": required,
        "freshness_days": freshness_days,
    }
    if not path.exists():
        item.update({"status": "missing", "exists": False, "row_count": 0})
        return item
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    age_hours = max(0.0, (datetime.now(UTC) - modified_at).total_seconds() / 3600.0)
    item.update(
        {
            # row_count is unknown at this stage (nothing has been parsed yet), so this
            # is never "empty" here; the caller re-derives the real status once it knows
            # the row count via `_status_for_existing`.
            "status": _freshness_status(
                age_hours=age_hours, freshness_days=freshness_days, row_count=1
            ),
            "exists": True,
            "size_bytes": stat.st_size,
            "modified_at": modified_at.isoformat().replace("+00:00", "Z"),
            "age_hours": round(age_hours, 2),
        }
    )
    return item


def _status_for_existing(base: JsonDict, *, row_count: int) -> str:
    return _freshness_status(
        age_hours=base.get("age_hours"),
        freshness_days=base.get("freshness_days"),
        row_count=row_count,
    )


def _freshness_status(*, age_hours: object, freshness_days: object, row_count: int) -> str:
    """Classify an existing dataset as ``empty``, ``stale``, or ``ready``.

    ``row_count <= 0`` always means ``empty``, regardless of age. Otherwise the
    dataset is ``stale`` once its age (hours) exceeds ``freshness_days`` * 24;
    a missing or non-numeric age/freshness input is treated as ``ready``.
    """

    if row_count <= 0:
        return "empty"
    if (
        isinstance(age_hours, int | float)
        and isinstance(freshness_days, int | float)
        and age_hours > float(freshness_days) * 24.0
    ):
        return "stale"
    return "ready"


def _read_csv_rows(path: Path) -> tuple[list[JsonDict], list[str]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            with path.open(newline="", encoding=encoding) as handle:
                reader = csv.DictReader(handle)
                columns = [str(name) for name in (reader.fieldnames or [])]
                rows = [dict(row) for row in reader]
                return rows, columns
        except UnicodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return [], []


def _unique_values(rows: Iterable[JsonDict], columns: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    for row in rows:
        value = _row_first_value(row, columns)
        if value:
            values.add(value)
    return values


def _latest_value(rows: Iterable[JsonDict], columns: tuple[str, ...]) -> str | None:
    latest: str | None = None
    for row in rows:
        value = _row_first_value(row, columns)
        if value and (latest is None or value > latest):
            latest = value
    return latest


def _read_text_lines(path: Path, *, max_lines: int) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.splitlines()[-max_lines:]


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def _annotate_daily_bars_coverage(datasets: list[JsonDict]) -> None:
    market = _dataset_by_id(datasets, "market_financials")
    bars = _dataset_by_id(datasets, "daily_bars")
    if market is None or bars is None:
        return

    reference_count = _as_int(market.get("ticker_count"), 0)
    covered_count = _as_int(bars.get("ticker_count"), 0)
    if reference_count <= 0:
        return

    percent = round((covered_count / reference_count) * 100.0, 2)
    minimum = min(reference_count, 50)
    bars.update(
        {
            "coverage_reference_dataset": "market_financials",
            "coverage_reference_ticker_count": reference_count,
            "coverage_ticker_count": covered_count,
            "coverage_percent": percent,
            "coverage_min_ticker_count": minimum,
        }
    )
    if covered_count >= minimum or str(bars.get("status")) in {"missing", "empty", "error"}:
        return

    warnings = list(bars.get("warnings") or [])
    warnings.append(
        f"OHLCVの対象銘柄が少ないです（{covered_count}/{reference_count}銘柄、{percent}%）。"
    )
    bars["warnings"] = warnings
    bars["status"] = "partial"


def _dataset_by_id(datasets: list[JsonDict], dataset_id: str) -> JsonDict | None:
    for item in datasets:
        if str(item.get("id") or "") == dataset_id:
            return item
    return None


def _refresh_actions(datasets: list[JsonDict]) -> list[JsonDict]:
    actions: list[JsonDict] = []
    for item in datasets:
        status = str(item.get("status") or "unknown")
        dataset_id = str(item.get("id") or "")
        if status == "ready":
            if dataset_id == "daily_bars" and _should_offer_daily_bars_expansion(item):
                actions.append(_daily_bars_action(item, expand=True))
            continue
        reason = _action_reason(status)
        if dataset_id == "market_financials":
            actions.append(
                {
                    "id": "refresh_market_financials",
                    "dataset_id": dataset_id,
                    "label": "市場財務指標を更新",
                    "reason": reason,
                    "action_type": "market_financials",
                    "safe_to_run": True,
                    "priority": 20,
                }
            )
        elif dataset_id == "daily_bars":
            actions.append(_daily_bars_action(item, reason=reason))
        elif dataset_id == "price_inbox":
            actions.append(
                {
                    "id": "check_price_inbox",
                    "dataset_id": dataset_id,
                    "label": "手動価格CSVを確認",
                    "reason": "手動価格CSVを使う場合だけ、配置後に反映確認します。",
                    "action_type": "price_inbox",
                    "safe_to_run": True,
                    "optional": True,
                    "priority": 80,
                }
            )
        elif dataset_id == "selected_financials":
            actions.append(
                {
                    "id": "fix_selected_financials",
                    "dataset_id": dataset_id,
                    "label": "財務CSVパスを確認",
                    "reason": reason,
                    "action_type": "manual",
                    "safe_to_run": False,
                    "priority": 10,
                }
            )
        elif dataset_id == "edinet_financials":
            actions.append(
                {
                    "id": "prepare_edinet_financials",
                    "dataset_id": dataset_id,
                    "label": "EDINET財務を取得",
                    "reason": "EDINET APIキーと対象範囲を確認してから取得します。",
                    "action_type": "manual",
                    "safe_to_run": False,
                    "priority": 50,
                }
            )
        elif dataset_id == "rag_db":
            actions.append(
                {
                    "id": "build_rag_db",
                    "dataset_id": dataset_id,
                    "label": "RAG検索DBを構築",
                    "reason": "根拠資料を登録してから検索DBを作ります。",
                    "action_type": "manual",
                    "safe_to_run": False,
                    "priority": 60,
                }
            )

    actions.sort(key=lambda action: int(action.get("priority", 999)))
    return actions


def _should_offer_daily_bars_expansion(item: JsonDict) -> bool:
    reference_count = _as_int(item.get("coverage_reference_ticker_count"), 0)
    covered_count = _as_int(item.get("coverage_ticker_count"), 0)
    percent = float(item.get("coverage_percent") or 0.0)
    return reference_count > 0 and covered_count < reference_count and percent < 25.0


def _daily_bars_action(
    item: JsonDict,
    *,
    reason: str | None = None,
    expand: bool = False,
) -> JsonDict:
    reference_count = _as_int(item.get("coverage_reference_ticker_count"), 0)
    covered_count = _as_int(item.get("coverage_ticker_count"), 0)
    if expand:
        recommended_max = min(reference_count or 100, max(100, covered_count + 50))
        return {
            "id": "expand_daily_bars",
            "dataset_id": "daily_bars",
            "label": "OHLCVを追加取得",
            "reason": "利用可能ですが全体カバー率が低めです。必要な範囲を追加取得できます。",
            "action_type": "daily_bars",
            "safe_to_run": True,
            "recommended_scope": "domestic",
            "recommended_max_count": recommended_max,
            "recommended_range": "1mo",
            "optional": True,
            "priority": 35,
        }
    return {
        "id": "refresh_daily_bars",
        "dataset_id": "daily_bars",
        "label": "株価四本値・出来高を更新",
        "reason": reason or "状態確認が必要です。",
        "action_type": "daily_bars",
        "safe_to_run": True,
        "recommended_scope": "domestic",
        "recommended_max_count": int(item.get("coverage_min_ticker_count") or 50),
        "recommended_range": "1mo",
        "priority": 30,
    }


def _action_reason(status: str) -> str:
    if status == "missing":
        return "ファイルが未取得です。"
    if status == "stale":
        return "最終更新から時間が経っています。"
    if status == "empty":
        return "ファイルはありますがデータ行がありません。"
    if status == "partial":
        return "取得済みですが対象銘柄のカバー率が不足しています。"
    if status == "error":
        return "読み取りエラーがあります。"
    return "状態確認が必要です。"


def _summary(datasets: list[JsonDict], *, actions: list[JsonDict]) -> JsonDict:
    counts: dict[str, int] = {}
    for item in datasets:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    required_missing = [
        str(item["label"])
        for item in datasets
        if item.get("required") and item.get("status") in {"missing", "empty", "error"}
    ]
    overall = "needs_setup" if required_missing else "ready"
    if any(item.get("status") == "error" for item in datasets):
        overall = "error"
    elif any(item.get("status") == "stale" for item in datasets):
        overall = "stale"
    elif any(item.get("status") == "partial" for item in datasets):
        overall = "needs_attention"
    optional_action_count = sum(1 for action in actions if action.get("optional"))
    required_action_count = len(actions) - optional_action_count
    return {
        "overall_status": overall,
        "dataset_count": len(datasets),
        "status_counts": counts,
        "required_missing": required_missing,
        "ready_count": counts.get("ready", 0),
        "stale_count": counts.get("stale", 0),
        "partial_count": counts.get("partial", 0),
        "missing_count": counts.get("missing", 0),
        "error_count": counts.get("error", 0),
        "action_count": len(actions),
        "required_action_count": required_action_count,
        "optional_action_count": optional_action_count,
        "safe_action_count": sum(1 for action in actions if action.get("safe_to_run")),
    }


def _path_from_body(body: JsonDict, key: str, default: str) -> Path:
    raw = body.get(key)
    path = str(raw).strip() if raw else default
    return reject_path_traversal(path)


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_sqlite_identifier(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char == "_" for char in value)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
