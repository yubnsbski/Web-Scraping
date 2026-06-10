"""Load company financial CSVs and build a non-advisory comparison."""

from __future__ import annotations

import csv
from pathlib import Path

from investment_assistant.financials.models import (
    FINANCIAL_COLUMNS,
    FinancialPoint,
    equity_ratio_to_percent,
)

DISCLAIMER = (
    "これはユーザー提供データに基づく機械的な集計であり、投資助言・売買推奨・"
    "将来リターンの保証ではありません。最終的な投資判断はユーザー本人が行います。"
    "自動売買は行いません。"
)


def _require_columns(fieldnames: set[str], required: tuple[str, ...]) -> None:
    missing = [c for c in required if c not in fieldnames]
    if missing:
        raise ValueError(f"CSVに必要な列がありません: {missing}")


def _parse_float(value: str | None, *, row: int, column: str) -> float:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{row}行目の{column}が空です")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{row}行目の{column}が数値ではありません: {text!r}") from exc


def _parse_int(value: str | None, *, row: int, column: str) -> int:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{row}行目の{column}が空です")
    try:
        return int(float(text))
    except ValueError as exc:
        raise ValueError(f"{row}行目の{column}が整数ではありません: {text!r}") from exc


def load_financials(path: str | Path) -> list[FinancialPoint]:
    """Read a financial CSV into FinancialPoint rows."""

    points: list[FinancialPoint] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(set(reader.fieldnames or []), FINANCIAL_COLUMNS)
        for index, raw in enumerate(reader, start=2):
            points.append(
                FinancialPoint(
                    ticker=(raw["ticker"] or "").strip(),
                    name=(raw["name"] or "").strip(),
                    fiscal_year=_parse_int(raw["fiscal_year"], row=index, column="fiscal_year"),
                    operating_cf=_parse_float(
                        raw["operating_cf"], row=index, column="operating_cf"
                    ),
                    equity_ratio=equity_ratio_to_percent(
                        _parse_float(raw["equity_ratio"], row=index, column="equity_ratio")
                    )
                    or 0.0,
                    dividend_per_share=_parse_float(
                        raw["dividend_per_share"], row=index, column="dividend_per_share"
                    ),
                    payout_policy=(raw["payout_policy"] or "").strip(),
                )
            )
    return points


def _dividend_cut_years(rows: list[FinancialPoint]) -> list[int]:
    """Fiscal years where dividend_per_share fell below the previous year."""

    ordered = sorted(rows, key=lambda r: r.fiscal_year)
    cuts: list[int] = []
    for prev, curr in zip(ordered, ordered[1:], strict=False):
        if curr.dividend_per_share < prev.dividend_per_share:
            cuts.append(curr.fiscal_year)
    return cuts


def _dividend_trend(rows: list[FinancialPoint]) -> str:
    """Classify the dividend path: increasing / flat / cut / mixed."""

    ordered = sorted(rows, key=lambda r: r.fiscal_year)
    return _series_trend([r.dividend_per_share for r in ordered])


def _series_trend(series: list[float]) -> str:
    """Classify a fiscal-year-ordered numeric series.

    increasing / declining / flat / mixed / insufficient. Shared by dividend and
    operating cash-flow trends so the classification stays consistent.
    """

    if len(series) < 2:
        return "insufficient"
    ups = downs = 0
    for prev, curr in zip(series, series[1:], strict=False):
        if curr > prev:
            ups += 1
        elif curr < prev:
            downs += 1
    if downs == 0 and ups > 0:
        return "increasing"
    if downs > 0 and ups == 0:
        return "declining"
    if ups == 0 and downs == 0:
        return "flat"
    return "mixed"


def compare_financials(points: list[FinancialPoint]) -> dict[str, object]:
    """Build a per-company comparison summary (mechanical, non-advisory)."""

    by_ticker: dict[str, list[FinancialPoint]] = {}
    for p in points:
        by_ticker.setdefault(p.ticker, []).append(p)

    companies: list[dict[str, object]] = []
    for ticker, rows in by_ticker.items():
        ordered = sorted(rows, key=lambda r: r.fiscal_year)
        latest = ordered[-1]
        companies.append(
            {
                "ticker": ticker,
                "name": latest.name,
                "latest_fiscal_year": latest.fiscal_year,
                "latest_operating_cf": latest.operating_cf,
                "latest_equity_ratio": latest.equity_ratio,
                "latest_dividend_per_share": latest.dividend_per_share,
                "dividend_cut_years": _dividend_cut_years(ordered),
                "dividend_trend": _dividend_trend(ordered),
                "operating_cf_trend": _series_trend([r.operating_cf for r in ordered]),
                "equity_ratio_trend": _series_trend([r.equity_ratio for r in ordered]),
                "payout_policy": latest.payout_policy,
                "years": [r.fiscal_year for r in ordered],
                "dividend_series": [r.dividend_per_share for r in ordered],
                "operating_cf_series": [r.operating_cf for r in ordered],
                "equity_ratio_series": [r.equity_ratio for r in ordered],
            }
        )
    companies.sort(key=lambda c: str(c["ticker"]))
    return {"companies": companies, "disclaimer": DISCLAIMER}
