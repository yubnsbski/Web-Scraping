"""Data catalog for the local investment assistant workspace."""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from investment_assistant.financials.current_yield import (
    DEFAULT_CURRENT_YIELDS_CSV,
    load_current_yields,
)
from investment_assistant.financials.dividend_quality import normalize_dividend_points
from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
from investment_assistant.financials.loader import load_financials
from investment_assistant.investment.universe import (
    DEFAULT_JPX_LISTED_ISSUES_PATH,
    load_jpx_listed_issues,
)
from investment_assistant.portfolio.price_store import (
    DEFAULT_CURRENT_PRICES_CSV,
    load_current_prices,
)

JsonDict = dict[str, Any]
DEFAULT_COMPANY_MASTER_CSV = Path("local_docs/company_master/company_master.csv")


def build_data_catalog(
    *,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    jpx_listed_path: str | Path = DEFAULT_JPX_LISTED_ISSUES_PATH,
    company_master_path: str | Path = DEFAULT_COMPANY_MASTER_CSV,
    market_prices_path: str | Path = DEFAULT_CURRENT_PRICES_CSV,
    current_yields_path: str | Path = DEFAULT_CURRENT_YIELDS_CSV,
    stale_after_days: int = 7,
) -> JsonDict:
    """Return a single status view over all local data files."""

    stale_days = max(int(stale_after_days), 1)
    datasets = [
        _financials_dataset(Path(financials_csv), stale_days),
        _jpx_listed_dataset(Path(jpx_listed_path), stale_days),
        _company_master_dataset(Path(company_master_path), stale_days),
        _market_prices_dataset(Path(market_prices_path), stale_days),
        _current_yields_dataset(Path(current_yields_path), stale_days),
    ]
    by_key = {str(item["key"]): item for item in datasets}
    missing = [item for item in datasets if item["status"] == "missing"]
    stale = [item for item in datasets if item["status"] == "stale"]
    invalid = [item for item in datasets if item["status"] == "invalid"]
    return {
        "available": True,
        "status": "needs_attention" if missing or stale or invalid else "ready",
        "generated_at": datetime.now(UTC).isoformat(),
        "canonical_paths": {
            "financials_csv": str(financials_csv),
            "jpx_listed_path": str(jpx_listed_path),
            "company_master_path": str(company_master_path),
            "market_prices_path": str(market_prices_path),
            "current_yields_path": str(current_yields_path),
        },
        "datasets": datasets,
        "by_key": by_key,
        "summary": {
            "dataset_count": len(datasets),
            "ready_count": sum(1 for item in datasets if item["status"] == "ready"),
            "missing_count": len(missing),
            "stale_count": len(stale),
            "invalid_count": len(invalid),
        },
        "next_actions": _next_actions(datasets),
        "auto_trading": False,
        "call_real_api": False,
    }


def _financials_dataset(path: Path, stale_after_days: int) -> JsonDict:
    def reader() -> JsonDict:
        points, _ = normalize_dividend_points(load_financials(path))
        tickers = {point.ticker for point in points}
        latest_year = max((point.fiscal_year for point in points), default=None)
        return {
            "row_count": len(points),
            "company_count": len(tickers),
            "latest_fiscal_year": latest_year,
        }

    return _dataset(
        key="financials",
        label="EDINET財務",
        path=path,
        stale_after_days=stale_after_days,
        reader=reader,
        purpose="候補抽出、保有分析、レポート根拠",
    )


def _jpx_listed_dataset(path: Path, stale_after_days: int) -> JsonDict:
    def reader() -> JsonDict:
        issues = load_jpx_listed_issues(path)
        return {
            "row_count": len(issues),
            "prime_count": sum(1 for issue in issues if issue.is_prime),
            "as_of": _max_text(issue.as_of for issue in issues),
        }

    return _dataset(
        key="jpx_listed",
        label="JPX上場一覧",
        path=path,
        stale_after_days=stale_after_days,
        reader=reader,
        purpose="証券コード検索、東証プライム選択、会社マスター作成",
    )


def _company_master_dataset(path: Path, stale_after_days: int) -> JsonDict:
    def reader() -> JsonDict:
        rows = _read_csv_rows(path)
        return {
            "row_count": len(rows),
            "prime_count": sum(
                1
                for row in rows
                if "プライム"
                in str(row.get("market_segment") or row.get("market_segment_label") or "")
            ),
            "financials_count": sum(1 for row in rows if _truthy(row.get("has_financials"))),
        }

    return _dataset(
        key="company_master",
        label="会社マスター",
        path=path,
        stale_after_days=stale_after_days,
        reader=reader,
        purpose="銘柄選択、日経225/東証プライム/財務取得状況の統合表示",
    )


def _market_prices_dataset(path: Path, stale_after_days: int) -> JsonDict:
    def reader() -> JsonDict:
        facts = load_current_prices(path)
        return {
            "row_count": len(facts),
            "ticker_count": len(facts),
            "latest_as_of": _max_text(fact.as_of for fact in facts.values()),
            "providers": sorted({fact.provider_id for fact in facts.values() if fact.provider_id}),
        }

    return _dataset(
        key="market_prices",
        label="株価スナップショット",
        path=path,
        stale_after_days=1,
        reader=reader,
        purpose="試算画面の株価初期値と取得失敗時のフォールバック",
    )


def _current_yields_dataset(path: Path, stale_after_days: int) -> JsonDict:
    def reader() -> JsonDict:
        facts = load_current_yields(path)
        return {
            "row_count": len(facts),
            "ticker_count": len(facts),
            "latest_as_of": _max_text(fact.as_of for fact in facts.values()),
            "providers": sorted({fact.provider_id for fact in facts.values() if fact.provider_id}),
        }

    return _dataset(
        key="current_yields",
        label="現在配当・利回り",
        path=path,
        stale_after_days=stale_after_days,
        reader=reader,
        purpose="EDINET配当と現在株価の単位ずれ補正",
    )


def _dataset(
    *,
    key: str,
    label: str,
    path: Path,
    stale_after_days: int,
    reader: Callable[[], JsonDict],
    purpose: str,
) -> JsonDict:
    base: JsonDict = {
        "key": key,
        "label": label,
        "path": str(path),
        "purpose": purpose,
        "stale_after_days": stale_after_days,
        "auto_trading": False,
    }
    if not path.is_file():
        return {
            **base,
            "available": False,
            "status": "missing",
            "modified_at": None,
            "age_days": None,
            "row_count": 0,
        }
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
    age_days = (datetime.now(UTC) - modified_at).total_seconds() / 86400
    try:
        extra = reader()
    except (OSError, ValueError, csv.Error) as exc:
        return {
            **base,
            "available": False,
            "status": "invalid",
            "modified_at": modified_at.isoformat(),
            "age_days": round(age_days, 2),
            "row_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        **base,
        "available": True,
        "status": "stale" if age_days > stale_after_days else "ready",
        "modified_at": modified_at.isoformat(),
        "age_days": round(age_days, 2),
        **extra,
    }


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _max_text(values: Iterable[object]) -> str:
    strings = [str(value).strip() for value in values if str(value or "").strip()]
    return max(strings) if strings else ""


def _next_actions(datasets: list[JsonDict]) -> list[str]:
    actions: list[str] = []
    by_key = {str(item["key"]): item for item in datasets}
    if by_key["jpx_listed"]["status"] == "missing":
        actions.append("JPX公式データを取得して、東証プライムを選択できる状態にする。")
    if by_key["financials"]["status"] == "missing":
        actions.append("EDINETまたは手動CSVで財務データを作成する。")
    if by_key["company_master"]["status"] in {"missing", "stale"}:
        actions.append("会社マスターを更新して、会社情報と財務取得状況をそろえる。")
    if by_key["market_prices"]["status"] in {"missing", "stale"}:
        actions.append("J-Quantsまたは許可済み価格ソースで株価を更新する。")
    if by_key["current_yields"]["status"] == "missing":
        actions.append("必要な銘柄だけ現在配当・利回りデータを追加する。")
    return actions
