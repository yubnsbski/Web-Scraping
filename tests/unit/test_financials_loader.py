"""Tests for the financials comparison loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.financials import (
    compare_financials,
    load_financials,
)

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


def test_companies_sorted_by_ticker() -> None:
    companies = _companies()
    assert list(companies.keys()) == ["7203", "9999"]


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
