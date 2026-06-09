"""Tests for the dividend-portfolio simulator."""

from __future__ import annotations

from investment_assistant.portfolio.simulator import estimate_haircut, simulate_portfolio

_NO_CSV = "/nonexistent/financials.csv"  # forces haircut defaults


def test_estimate_haircut_signals() -> None:
    assert estimate_haircut(None) == 0.05
    assert estimate_haircut({"dividend_trend": "increasing", "dividend_cut_years": []}) == 0.0
    heavy = estimate_haircut(
        {
            "dividend_trend": "declining",
            "dividend_cut_years": [2023, 2024],
            "latest_equity_ratio": 15,
            "operating_cf_trend": "declining",
        }
    )
    assert heavy == 0.35  # 0.15 + 0.10 + 0.05 + 0.05
    capped = estimate_haircut({"dividend_trend": "declining", "dividend_cut_years": [1, 2, 3, 4]})
    assert capped <= 0.5


def test_simulate_allocates_whole_lots_and_projects() -> None:
    out = simulate_portfolio(
        budget=1_000_000,
        holdings=[
            {"ticker": "A", "price": 1000, "dividend_per_share": 40, "weight": 1},
            {"ticker": "B", "price": 2000, "dividend_per_share": 50, "weight": 1},
        ],
        years=10,
        reinvest=True,
        auto_weight="manual",
        financials_csv=_NO_CSV,
    )
    assert out["available"] is True
    allocs = {a["ticker"]: a for a in out["allocations"]}  # type: ignore[union-attr]
    assert allocs["A"]["shares"] == 500  # floor(500000 / (1000*100)) * 100
    assert allocs["A"]["invested"] == 500000
    assert allocs["A"]["annual_dividend"] == 500 * 40

    summary = out["summary"]
    assert summary["invested"] <= 1_000_000  # type: ignore[operator]
    assert summary["cash_left"] >= 0  # type: ignore[operator]
    assert summary["annual_dividend"] > 0  # type: ignore[operator]

    proj = out["projection"]
    assert len(proj["years"]) == 11  # type: ignore[index]
    assert len(proj["reinvested"]) == 11  # type: ignore[index]
    # Snowball reinvestment beats flat nominal income by the final year.
    assert proj["reinvested"][-1] >= proj["nominal"][-1]  # type: ignore[index]

    surface = out["surface"]
    assert len(surface["yields"]) == 8  # type: ignore[index]
    assert len(surface["z"]) == 8 and len(surface["z"][0]) == 10  # type: ignore[index]


def test_auto_weight_yield_favours_higher_yield() -> None:
    out = simulate_portfolio(
        budget=1_000_000,
        holdings=[
            {"ticker": "L", "price": 1000, "dividend_per_share": 10},
            {"ticker": "H", "price": 1000, "dividend_per_share": 50},
        ],
        auto_weight="yield",
        financials_csv=_NO_CSV,
    )
    by = {a["ticker"]: a for a in out["allocations"]}  # type: ignore[union-attr]
    assert by["H"]["weight"] > by["L"]["weight"]


def test_no_valid_holdings_returns_unavailable() -> None:
    out = simulate_portfolio(
        budget=1000, holdings=[{"ticker": "X", "price": 0}], financials_csv=_NO_CSV
    )
    assert out["available"] is False
