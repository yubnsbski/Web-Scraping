"""Tests for the financials comparison loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.financials import (
    compare_financials,
    load_financials,
)
from investment_assistant.financials.models import equity_ratio_to_percent

SAMPLE = Path("examples/financials_sample.csv")


def _companies() -> dict[str, dict[str, object]]:
    points = load_financials(SAMPLE)
    result = compare_financials(points)
    companies = result["companies"]
    assert isinstance(companies, list)
    return {str(c["ticker"]): c for c in companies}


def test_loads_all_rows() -> None:
    points = load_financials(SAMPLE)
    assert len(points) == 10


def test_increasing_company_has_no_cuts() -> None:
    stable = _companies()["7203"]
    assert stable["dividend_trend"] == "increasing"
    assert stable["dividend_cut_years"] == []
    assert stable["latest_operating_cf"] == 1105000.0
    assert stable["latest_equity_ratio"] == 62.3


def test_volatile_company_detects_cut_years() -> None:
    volatile = _companies()["9999"]
    assert volatile["dividend_trend"] == "mixed"
    assert volatile["dividend_cut_years"] == [2023, 2025]
    assert volatile["latest_dividend_per_share"] == 45.0


def test_comparison_includes_operating_cf_and_equity_trends() -> None:
    company = _companies()["7203"]
    # Additive trend/series keys are present and fiscal-year ordered.
    assert company["operating_cf_trend"] in {
        "increasing",
        "declining",
        "flat",
        "mixed",
        "insufficient",
    }
    assert company["equity_ratio_trend"] in {
        "increasing",
        "declining",
        "flat",
        "mixed",
        "insufficient",
    }
    assert isinstance(company["operating_cf_series"], list)
    assert len(company["operating_cf_series"]) == len(company["years"])
    assert len(company["equity_ratio_series"]) == len(company["years"])


def test_companies_sorted_by_ticker() -> None:
    companies = _companies()
    assert list(companies.keys()) == ["7203", "9999"]


def test_equity_ratio_to_percent_normalises_fraction() -> None:
    # 0–1 EDINET fractions become percentages; already-percent values pass through.
    assert equity_ratio_to_percent(0.766) == 76.6
    assert equity_ratio_to_percent(1.0) == 100.0
    assert equity_ratio_to_percent(62.3) == 62.3
    # Idempotent: re-applying does not double-scale a percentage.
    assert equity_ratio_to_percent(equity_ratio_to_percent(0.5)) == 50.0
    assert equity_ratio_to_percent(None) is None
    assert equity_ratio_to_percent(0.0) == 0.0


def test_load_normalises_fractional_equity_ratio(tmp_path: Path) -> None:
    path = tmp_path / "fractional.csv"
    path.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "7974,任天堂,2024,500000,0.766,189,記載なし\n",
        encoding="utf-8",
    )
    points = load_financials(path)
    assert points[0].equity_ratio == 76.6


def test_missing_column_raises() -> None:
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8"
    ) as handle:
        handle.write("ticker,name\\n7203,Foo\\n")
        bad = handle.name
    with pytest.raises(ValueError, match="必要な列"):
        load_financials(bad)
    Path(bad).unlink(missing_ok=True)
