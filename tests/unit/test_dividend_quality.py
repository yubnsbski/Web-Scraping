from __future__ import annotations

from investment_assistant.financials.dividend_quality import (
    financial_points_to_csv_text,
    normalize_dividend_per_share,
    normalize_dividend_points,
)
from investment_assistant.financials.models import FinancialPoint


def _point(ticker: str, year: int, dps: float) -> FinancialPoint:
    return FinancialPoint(
        ticker=ticker,
        name="sample",
        fiscal_year=year,
        operating_cf=0.0,
        equity_ratio=0.0,
        dividend_per_share=dps,
        payout_policy="",
    )


def test_normalize_dividend_per_share_corrects_previous_year_unit_jump() -> None:
    value, check = normalize_dividend_per_share(
        4100.0,
        ticker="8306",
        fiscal_year=2025,
        previous_value=41.0,
    )

    assert value == 41.0
    assert check is not None
    assert check.status == "corrected"
    assert check.correction_factor == 100.0
    assert check.code == "dividend_unit_scale_corrected"


def test_normalize_dividend_per_share_warns_high_yield_without_clear_unit_fix() -> None:
    value, check = normalize_dividend_per_share(
        180.0,
        ticker="9999",
        fiscal_year=2025,
        price=1000.0,
    )

    assert value == 180.0
    assert check is not None
    assert check.status == "warn"
    assert check.code == "dividend_yield_high_review"
    assert check.original_yield_pct == 18.0


def test_normalize_dividend_per_share_corrects_extreme_price_yield() -> None:
    value, check = normalize_dividend_per_share(
        4100.0,
        ticker="7203",
        fiscal_year=2025,
        price=1000.0,
    )

    assert value == 41.0
    assert check is not None
    assert check.status == "corrected"
    assert check.checked_yield_pct == 4.1


def test_normalize_dividend_points_preserves_order_and_reports_summary() -> None:
    points = [
        _point("B", 2024, 30.0),
        _point("A", 2024, 40.0),
        _point("A", 2025, 4000.0),
    ]

    normalized, summary = normalize_dividend_points(points)

    assert [point.ticker for point in normalized] == ["B", "A", "A"]
    assert [point.dividend_per_share for point in normalized] == [30.0, 40.0, 40.0]
    assert summary["status"] == "corrected"
    assert summary["corrected_count"] == 1
    assert summary["warning_count"] == 0


def test_financial_points_to_csv_text_uses_canonical_columns() -> None:
    text = financial_points_to_csv_text([_point("8306", 2024, 41.0)])

    assert text.splitlines()[0] == (
        "ticker,name,fiscal_year,operating_cf,equity_ratio,"
        "dividend_per_share,payout_policy"
    )
    assert "8306,sample,2024,0,0,41," in text
