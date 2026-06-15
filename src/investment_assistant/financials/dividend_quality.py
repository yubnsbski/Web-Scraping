"""Dividend per-share validation and unit correction.

The financial pipeline stores dividends as yen per share. EDINET filings and
manual CSVs can still carry obvious unit mistakes after extraction or copy/paste
work, most commonly 10x/100x values. This module keeps the correction
deterministic and conservative: it only changes a value when a previous fiscal
year or an extreme price-based yield makes the unit error clear.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace

from investment_assistant.financials.models import FINANCIAL_COLUMNS, FinancialPoint

DEFAULT_MAX_REASONABLE_YIELD_PCT = 15.0
DEFAULT_EXTREME_YIELD_PCT = 50.0
_UNIT_FACTORS = (100.0, 10.0)


@dataclass(frozen=True)
class DividendQualityCheck:
    """One validation/correction event for a dividend per-share value."""

    ticker: str
    fiscal_year: int
    original_value: float
    checked_value: float
    status: str
    code: str
    message: str
    previous_value: float | None = None
    price: float | None = None
    original_yield_pct: float | None = None
    checked_yield_pct: float | None = None
    correction_factor: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


def normalize_dividend_per_share(
    value: float,
    *,
    ticker: str = "",
    fiscal_year: int = 0,
    previous_value: float | None = None,
    price: float | None = None,
    max_reasonable_yield_pct: float = DEFAULT_MAX_REASONABLE_YIELD_PCT,
    extreme_yield_pct: float = DEFAULT_EXTREME_YIELD_PCT,
) -> tuple[float, DividendQualityCheck | None]:
    """Return a validated dividend-per-share value and optional audit check."""

    original = float(value)
    if original < 0:
        return 0.0, DividendQualityCheck(
            ticker=ticker,
            fiscal_year=fiscal_year,
            original_value=original,
            checked_value=0.0,
            status="corrected",
            code="dividend_negative_clamped",
            message="Negative dividend per share was clamped to 0.",
            previous_value=previous_value,
            price=price,
            original_yield_pct=_yield_pct(original, price),
            checked_yield_pct=_yield_pct(0.0, price),
        )

    previous = _positive(previous_value)
    market_price = _positive(price)

    if previous is not None:
        corrected = _correction_from_previous(
            original,
            previous,
            market_price,
            max_reasonable_yield_pct,
        )
        if corrected is not None:
            value_after, factor = corrected
            return value_after, DividendQualityCheck(
                ticker=ticker,
                fiscal_year=fiscal_year,
                original_value=original,
                checked_value=value_after,
                status="corrected",
                code="dividend_unit_scale_corrected",
                message=(
                    "Dividend per share looked 10x/100x larger than the prior "
                    "accepted fiscal-year value and was unit-normalized."
                ),
                previous_value=previous,
                price=market_price,
                original_yield_pct=_yield_pct(original, market_price),
                checked_yield_pct=_yield_pct(value_after, market_price),
                correction_factor=factor,
            )

    original_yield = _yield_pct(original, market_price)
    if original_yield is not None:
        corrected = _correction_from_extreme_yield(
            original,
            market_price,
            max_reasonable_yield_pct=max_reasonable_yield_pct,
            extreme_yield_pct=extreme_yield_pct,
        )
        if corrected is not None:
            value_after, factor = corrected
            return value_after, DividendQualityCheck(
                ticker=ticker,
                fiscal_year=fiscal_year,
                original_value=original,
                checked_value=value_after,
                status="corrected",
                code="dividend_yield_unit_scale_corrected",
                message=(
                    "Dividend per share implied an extreme yield; a 10x/100x "
                    "unit correction produced a plausible yield."
                ),
                previous_value=previous,
                price=market_price,
                original_yield_pct=original_yield,
                checked_yield_pct=_yield_pct(value_after, market_price),
                correction_factor=factor,
            )
        if original_yield > max_reasonable_yield_pct:
            return original, DividendQualityCheck(
                ticker=ticker,
                fiscal_year=fiscal_year,
                original_value=original,
                checked_value=original,
                status="warn",
                code="dividend_yield_high_review",
                message=(
                    "Dividend per share implies a high yield; verify the source "
                    "before relying on this value."
                ),
                previous_value=previous,
                price=market_price,
                original_yield_pct=original_yield,
                checked_yield_pct=original_yield,
            )

    return original, None


def normalize_dividend_points(
    points: Sequence[FinancialPoint],
) -> tuple[list[FinancialPoint], dict[str, object]]:
    """Normalize dividend values within each ticker's fiscal-year series."""

    indexed = list(enumerate(points))
    corrected_by_index: dict[int, FinancialPoint] = {}
    checks: list[DividendQualityCheck] = []

    by_ticker: dict[str, list[tuple[int, FinancialPoint]]] = {}
    for index, point in indexed:
        by_ticker.setdefault(point.ticker, []).append((index, point))

    for ticker_points in by_ticker.values():
        previous: float | None = None
        for index, point in sorted(ticker_points, key=lambda item: item[1].fiscal_year):
            value, check = normalize_dividend_per_share(
                point.dividend_per_share,
                ticker=point.ticker,
                fiscal_year=point.fiscal_year,
                previous_value=previous,
            )
            if check is not None:
                checks.append(check)
            corrected_by_index[index] = (
                replace(point, dividend_per_share=value)
                if value != point.dividend_per_share
                else point
            )
            if value > 0:
                previous = value

    normalized = [corrected_by_index.get(index, point) for index, point in indexed]
    return normalized, dividend_quality_summary(checks)


def dividend_quality_summary(
    checks: Iterable[DividendQualityCheck],
) -> dict[str, object]:
    """Summarize dividend validation events for API payloads."""

    check_list = list(checks)
    corrected = [check for check in check_list if check.status == "corrected"]
    warnings = [check for check in check_list if check.status == "warn"]
    status = "ok"
    if corrected:
        status = "corrected"
    elif warnings:
        status = "warn"
    return {
        "status": status,
        "checked_rule": "dividend_per_share unit/yield sanity",
        "max_reasonable_yield_pct": DEFAULT_MAX_REASONABLE_YIELD_PCT,
        "extreme_yield_pct": DEFAULT_EXTREME_YIELD_PCT,
        "corrected_count": len(corrected),
        "warning_count": len(warnings),
        "checks": [check.to_dict() for check in check_list],
    }


def financial_points_to_csv_text(points: Sequence[FinancialPoint]) -> str:
    """Serialize financial points as the canonical financials.csv format."""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(FINANCIAL_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for point in sorted(points, key=lambda p: (p.ticker, p.fiscal_year)):
        writer.writerow(
            {
                "ticker": point.ticker,
                "name": point.name,
                "fiscal_year": str(point.fiscal_year),
                "operating_cf": _format_number(point.operating_cf),
                "equity_ratio": _format_number(point.equity_ratio),
                "dividend_per_share": _format_number(point.dividend_per_share),
                "payout_policy": point.payout_policy,
            }
        )
    return output.getvalue()


def _correction_from_previous(
    original: float,
    previous: float,
    price: float | None,
    max_reasonable_yield_pct: float,
) -> tuple[float, float] | None:
    if original <= 0 or previous <= 0:
        return None
    original_gap = _log_gap(original, previous)
    candidates: list[tuple[float, float, float]] = []
    for factor in _UNIT_FACTORS:
        if original < previous * factor * 0.65:
            continue
        scaled = original / factor
        if scaled <= 0:
            continue
        scaled_yield = _yield_pct(scaled, price)
        if scaled_yield is not None and scaled_yield > max_reasonable_yield_pct:
            continue
        scaled_gap = _log_gap(scaled, previous)
        if scaled_gap < original_gap / 3:
            candidates.append((scaled_gap, scaled, factor))
    if not candidates:
        return None
    _, value, factor = min(candidates, key=lambda item: item[0])
    return value, factor


def _correction_from_extreme_yield(
    original: float,
    price: float | None,
    *,
    max_reasonable_yield_pct: float,
    extreme_yield_pct: float,
) -> tuple[float, float] | None:
    original_yield = _yield_pct(original, price)
    if original_yield is None or original_yield < extreme_yield_pct:
        return None
    candidates: list[tuple[float, float, float]] = []
    for factor in _UNIT_FACTORS:
        scaled = original / factor
        scaled_yield = _yield_pct(scaled, price)
        if scaled > 0 and scaled_yield is not None and scaled_yield <= max_reasonable_yield_pct:
            candidates.append((scaled_yield, scaled, factor))
    if not candidates:
        return None
    # Keep the largest still-plausible yield so 800/1000 becomes 80 -> 8%,
    # while 4100/1000 becomes 410% -> 4.1%.
    _, value, factor = max(candidates, key=lambda item: item[0])
    return value, factor


def _yield_pct(dividend_per_share: float, price: float | None) -> float | None:
    price_value = _positive(price)
    if price_value is None:
        return None
    return round(dividend_per_share / price_value * 100.0, 6)


def _positive(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _log_gap(a: float, b: float) -> float:
    return abs(math.log(a / b))


def _format_number(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)
