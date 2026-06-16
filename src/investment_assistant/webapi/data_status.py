"""Read-only data inventory for the local investment dashboard."""

from __future__ import annotations

import csv
import sqlite3
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

_DEFAULT_DAILY_BARS_PATH = "local_docs/market/daily_bars.csv"
_DEFAULT_YAHOO_FINANCIALS_PATH = "local_docs/market/yahoo_financials.csv"
_DEFAULT_EDINET_FINANCIALS_PATH = "local_docs/edinet/financials.csv"
_DEFAULT_MARKET_LOG_PATH = "local_docs/logs/market_fetch.log"


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
        tickers = _unique_values(rows, ("ticker", "code", "ticker_or_fund_code", "fund_code"))
        latest = _latest_value(rows, ("price_as_of", "as_of", "date", "period_end", "fiscal_year"))
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
            "status": "ready",
            "exists": True,
            "size_bytes": stat.st_size,
            "modified_at": modified_at.isoformat().replace("+00:00", "Z"),
            "age_hours": round(age_hours, 2),
        }
    )
    return item


def _status_for_existing(base: JsonDict, *, row_count: int) -> str:
    if row_count <= 0:
        return "empty"
    age_hours = base.get("age_hours")
    freshness_days = base.get("freshness_days")
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
        for column in columns:
            value = str(row.get(column) or "").strip()
            if value:
                values.add(value)
                break
    return values


def _latest_value(rows: Iterable[JsonDict], columns: tuple[str, ...]) -> str | None:
    latest: str | None = None
    for row in rows:
        for column in columns:
            value = str(row.get(column) or "").strip()
            if value and (latest is None or value > latest):
                latest = value
            if value:
                break
    return latest


def _read_text_lines(path: Path, *, max_lines: int) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.splitlines()[-max_lines:]


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def _refresh_actions(datasets: list[JsonDict]) -> list[JsonDict]:
    actions: list[JsonDict] = []
    for item in datasets:
        status = str(item.get("status") or "unknown")
        if status == "ready":
            continue
        dataset_id = str(item.get("id") or "")
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
            actions.append(
                {
                    "id": "refresh_daily_bars",
                    "dataset_id": dataset_id,
                    "label": "株価四本値・出来高を更新",
                    "reason": reason,
                    "action_type": "daily_bars",
                    "safe_to_run": True,
                    "priority": 30,
                }
            )
        elif dataset_id == "price_inbox":
            actions.append(
                {
                    "id": "check_price_inbox",
                    "dataset_id": dataset_id,
                    "label": "手動価格CSVを確認",
                    "reason": "CSVを配置した後に反映確認します。",
                    "action_type": "price_inbox",
                    "safe_to_run": True,
                    "priority": 40,
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


def _action_reason(status: str) -> str:
    if status == "missing":
        return "ファイルが未取得です。"
    if status == "stale":
        return "最終更新から時間が経っています。"
    if status == "empty":
        return "ファイルはありますがデータ行がありません。"
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
    return {
        "overall_status": overall,
        "dataset_count": len(datasets),
        "status_counts": counts,
        "required_missing": required_missing,
        "ready_count": counts.get("ready", 0),
        "stale_count": counts.get("stale", 0),
        "missing_count": counts.get("missing", 0),
        "error_count": counts.get("error", 0),
        "action_count": len(actions),
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
