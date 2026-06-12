"""Small EDINET summary helpers for investment MVP payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

TREND_LABELS: dict[str, str] = {
    "increasing": "増加傾向",
    "declining": "減少傾向",
    "flat": "横ばい",
    "mixed": "増減混在",
    "insufficient": "データ不足",
}


def trend_label(value: object) -> str:
    """Return a Japanese label for a normalized financial trend value."""

    key = str(value or "insufficient")
    return TREND_LABELS.get(key, key)


def build_edinet_summary(
    company: Mapping[str, object],
    *,
    financials_csv: str | Path,
    generated_at: str,
) -> dict[str, object]:
    """Build a compact, display-ready EDINET financial summary."""

    years = _list(company.get("years"))
    cut_years = _list(company.get("dividend_cut_years"))
    dividend_series = _list(company.get("dividend_series"))
    dividend_trend = str(company.get("dividend_trend") or "insufficient")
    operating_cf_trend = str(company.get("operating_cf_trend") or "insufficient")
    equity_ratio_trend = str(company.get("equity_ratio_trend") or "insufficient")
    return {
        "source_type": "edinet_financials",
        "source_ref": str(financials_csv),
        "ticker": str(company.get("ticker") or ""),
        "name": str(company.get("name") or ""),
        "latest_fiscal_year": company.get("latest_fiscal_year"),
        "latest_operating_cf": company.get("latest_operating_cf"),
        "latest_equity_ratio": company.get("latest_equity_ratio"),
        "latest_dividend_per_share": company.get("latest_dividend_per_share"),
        "dividend_cut_years": cut_years,
        "dividend_trend": dividend_trend,
        "dividend_trend_label": trend_label(dividend_trend),
        "operating_cf_trend": operating_cf_trend,
        "operating_cf_trend_label": trend_label(operating_cf_trend),
        "equity_ratio_trend": equity_ratio_trend,
        "equity_ratio_trend_label": trend_label(equity_ratio_trend),
        "periods": len(years) if years else len(dividend_series),
        "payout_policy": company.get("payout_policy"),
        "last_updated": generated_at,
        "note": "EDINET由来の取得済み財務CSVを機械集計した比較材料です。",
    }


def _list(value: object) -> list[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return list(value)
