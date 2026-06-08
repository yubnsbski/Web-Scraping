"""Bridge EDINET filings into the cross-company financials comparison.

Turns the metrics extracted from an EDINET CSV (``FinancialValue``) into the
:class:`~investment_assistant.financials.models.FinancialPoint` rows that the
existing :func:`~investment_assistant.financials.compare_financials` consumes.
That reuses the already-tested dividend-cut / trend logic on official numbers
instead of re-implementing analysis here.

One filing yields at most one point (its reporting period). A multi-year series
— and therefore dividend-cut / trend detection — accumulates as more periods are
ingested (a wide date scan, or weekly runs that persist a per-filing sidecar).

No network I/O.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path

from investment_assistant.edinet.csv_extract import FinancialValue, select_metrics
from investment_assistant.edinet.models import EdinetDocument
from investment_assistant.financials.models import FINANCIAL_COLUMNS, FinancialPoint

_LABEL_OPERATING_CF = "営業活動によるキャッシュ・フロー"
_LABEL_EQUITY_RATIO = "自己資本比率"
_LABEL_DIVIDEND = "１株当たり配当"
_LABEL_PAYOUT = "配当性向"


def build_financial_point(
    document: EdinetDocument,
    values: Iterable[FinancialValue],
    *,
    ticker: str,
    company: str | None = None,
) -> FinancialPoint | None:
    """Build one ``FinancialPoint`` from a filing's extracted values.

    Returns ``None`` when the filing has no usable fiscal year or no dividend
    figure — the dividend anchors the time series, so filings without it are
    skipped rather than polluting the trend with zeros.
    """

    fiscal_year = _fiscal_year(document.period_end)
    if fiscal_year is None:
        return None

    grouped = select_metrics(values)

    def first_value(label: str) -> float | None:
        items = grouped.get(label)
        if not items:
            return None
        return _to_float(items[0].value)

    dividend = first_value(_LABEL_DIVIDEND)
    if dividend is None:
        return None

    payout = first_value(_LABEL_PAYOUT)
    name = company or document.filer_name or ticker
    return FinancialPoint(
        ticker=ticker,
        name=name,
        fiscal_year=fiscal_year,
        operating_cf=first_value(_LABEL_OPERATING_CF) or 0.0,
        equity_ratio=first_value(_LABEL_EQUITY_RATIO) or 0.0,
        dividend_per_share=dividend,
        payout_policy=f"配当性向 {payout}%" if payout is not None else "",
    )


def dedupe_points(points: Iterable[FinancialPoint]) -> list[FinancialPoint]:
    """Keep the first point per ``(ticker, fiscal_year)``.

    Callers pass points newest-filing-first, so the newest filing's figures win
    when the same period appears in more than one filing.
    """

    seen: set[tuple[str, int]] = set()
    result: list[FinancialPoint] = []
    for point in points:
        key = (point.ticker, point.fiscal_year)
        if key in seen:
            continue
        seen.add(key)
        result.append(point)
    return result


def point_to_row(point: FinancialPoint) -> dict[str, str]:
    """Render a point as a CSV row matching ``FINANCIAL_COLUMNS``."""

    return {
        "ticker": point.ticker,
        "name": point.name,
        "fiscal_year": str(point.fiscal_year),
        "operating_cf": _format_number(point.operating_cf),
        "equity_ratio": _format_number(point.equity_ratio),
        "dividend_per_share": _format_number(point.dividend_per_share),
        "payout_policy": point.payout_policy,
    }


def point_from_mapping(row: Mapping[str, object]) -> FinancialPoint | None:
    """Reconstruct a point from a stored row (sidecar JSON / CSV)."""

    fiscal_year = _to_int(row.get("fiscal_year"))
    ticker = str(row.get("ticker") or "").strip()
    if fiscal_year is None or not ticker:
        return None
    return FinancialPoint(
        ticker=ticker,
        name=str(row.get("name") or "").strip(),
        fiscal_year=fiscal_year,
        operating_cf=_to_float(str(row.get("operating_cf") or "0")) or 0.0,
        equity_ratio=_to_float(str(row.get("equity_ratio") or "0")) or 0.0,
        dividend_per_share=_to_float(str(row.get("dividend_per_share") or "0")) or 0.0,
        payout_policy=str(row.get("payout_policy") or ""),
    )


def write_financials_csv(points: Iterable[FinancialPoint], path: str | Path) -> str:
    """Write points to a CSV compatible with ``load_financials``."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(points, key=lambda p: (p.ticker, p.fiscal_year))
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FINANCIAL_COLUMNS))
        writer.writeheader()
        for point in ordered:
            writer.writerow(point_to_row(point))
    return str(target)


def _fiscal_year(period_end: str | None) -> int | None:
    if not period_end or len(period_end) < 4:
        return None
    try:
        return int(period_end[:4])
    except ValueError:
        return None


def _to_float(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_int(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)
