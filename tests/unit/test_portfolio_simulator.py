"""Tests for the dividend-portfolio simulator, universe, and market prices."""

from __future__ import annotations

from pathlib import Path

from investment_assistant.portfolio.prices import fetch_prices, parse_close
from investment_assistant.portfolio.simulator import (
    build_universe,
    dividend_band,
    estimate_safety,
    simulate_portfolio,
)

_NO_CSV = "/nonexistent/financials.csv"
_CSV_HEADER = "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"


def _csv(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "financials.csv"
    path.write_text(_CSV_HEADER + rows, encoding="utf-8")
    return path


def test_dividend_band_bollinger() -> None:
    band = dividend_band([30.0, 40.0, 50.0])
    assert band is not None
    assert band["mean"] == 40.0
    assert band["lower"] < band["mean"] < band["upper"]
    assert band["lower"] >= 0.0
    assert dividend_band([]) is None
    single = dividend_band([40.0])
    assert single is not None and single["lower"] == single["upper"] == 40.0


def test_estimate_safety_signals() -> None:
    assert estimate_safety({"dividend_trend": "increasing", "dividend_cut_years": []}) == 1.0
    risky = estimate_safety(
        {
            "dividend_trend": "declining",
            "dividend_cut_years": [2023, 2024],
            "latest_equity_ratio": 10,
        }
    )
    assert risky == 0.7  # 1 - (0.15 declining + 0.10 cuts + 0.05 low-equity)


def test_simulate_equal_weight_conservative_basis() -> None:
    out = simulate_portfolio(
        budget=1_000_000,
        holdings=[
            {"ticker": "A", "price": 1000, "dividend_per_share": 40},
            {"ticker": "B", "price": 2000, "dividend_per_share": 50},
        ],
        auto_weight="equal",
        financials_csv=_NO_CSV,  # no series -> conservative == latest
    )
    assert out["available"] is True
    allocs = {a["ticker"]: a for a in out["allocations"]}  # type: ignore[union-attr]
    assert allocs["A"]["shares"] == 500
    assert allocs["A"]["annual_dividend"] == 500 * 40
    proj = out["projection"]
    assert len(proj["years"]) == 11  # type: ignore[index]
    assert proj["reinvested"][-1] >= proj["conservative"][-1]  # type: ignore[index]


def test_simulate_fixed_shares_and_amount_modes() -> None:
    shares_out = simulate_portfolio(
        budget=0,
        holdings=[{"ticker": "A", "price": 1000, "dividend_per_share": 40, "shares": 300}],
        auto_weight="shares",
        financials_csv=_NO_CSV,
    )
    assert shares_out["allocations"][0]["shares"] == 300  # type: ignore[index]

    amount_out = simulate_portfolio(
        budget=0,
        holdings=[{"ticker": "A", "price": 1000, "dividend_per_share": 40, "amount": 350000}],
        auto_weight="amount",
        financials_csv=_NO_CSV,
    )
    assert amount_out["allocations"][0]["shares"] == 300  # floor(350000/100000)*100


def test_simulate_conservative_below_latest_with_history(tmp_path: Path) -> None:
    csv = _csv(tmp_path, "8306,MUFG,2023,1000,5,30,安定\n8306,MUFG,2024,1100,5,50,安定\n")
    out = simulate_portfolio(
        budget=1_000_000,
        holdings=[{"ticker": "8306", "price": 1600}],
        auto_weight="equal",
        financials_csv=str(csv),
    )
    alloc = out["allocations"][0]  # type: ignore[index]
    assert alloc["dividend_per_share_latest"] == 50.0
    assert alloc["dividend_per_share"] < 50.0  # conservative band lower


def test_build_universe_sorts_by_safety(tmp_path: Path) -> None:
    csv = _csv(
        tmp_path,
        "8306,MUFG,2023,1000,5,30,安定\n8306,MUFG,2024,1100,5,50,安定\n9999,Risk,2024,100,10,5,記載なし\n",
    )
    universe = build_universe(str(csv), prices={"8306": 1600})
    assert universe[0]["ticker"] in {"8306", "9999"}
    row = next(r for r in universe if r["ticker"] == "8306")
    assert row["dividend_latest"] == 50.0
    assert row["yield_latest"] is not None


def test_optimize_cash_min_minimises_leftover() -> None:
    # Budget 1,200,000 with lots of 700,000 and 600,000: weight-floor would buy
    # one 700k lot (cash 500k), but cash_min buys two 600k lots (cash 0).
    out = simulate_portfolio(
        budget=1_200_000,
        holdings=[
            {"ticker": "A", "price": 7000, "dividend_per_share": 100},
            {"ticker": "B", "price": 6000, "dividend_per_share": 100},
        ],
        optimization="cash_min",
        financials_csv=_NO_CSV,
    )
    assert out["optimization"] == "cash_min"
    assert out["summary"]["cash_left"] == 0  # type: ignore[index]
    allocs = {a["ticker"]: a for a in out["allocations"]}  # type: ignore[union-attr]
    assert allocs["B"]["shares"] == 200 and allocs["A"]["shares"] == 0


def test_optimize_dividend_max_picks_best_yield() -> None:
    # Same price; B pays more -> dividend_max should concentrate on B.
    out = simulate_portfolio(
        budget=1_000_000,
        holdings=[
            {"ticker": "A", "price": 1000, "dividend_per_share": 10},
            {"ticker": "B", "price": 1000, "dividend_per_share": 60},
        ],
        optimization="dividend_max",
        dividend_basis="latest",
        financials_csv=_NO_CSV,
    )
    allocs = {a["ticker"]: a for a in out["allocations"]}  # type: ignore[union-attr]
    assert allocs["B"]["shares"] == 1000 and allocs["A"]["shares"] == 0
    assert out["summary"]["annual_dividend"] == 1000 * 60  # type: ignore[index]


def test_optimize_balanced_weights_dividend_by_safety(tmp_path: Path) -> None:
    # A has a slightly better raw yield but a dividend cut; B is safe and steady.
    # balanced (yield × safety) should prefer the safer B.
    csv = _csv(
        tmp_path,
        "A,Aco,2023,1000,60,80,安定\nA,Aco,2024,1000,60,40,安定\n"  # cut -> low safety
        "B,Bco,2023,1000,60,50,安定\nB,Bco,2024,1000,60,55,安定\n",  # steady -> safe
    )
    out = simulate_portfolio(
        budget=1_000_000,
        holdings=[
            {"ticker": "A", "price": 1000},
            {"ticker": "B", "price": 1000},
        ],
        optimization="balanced",
        dividend_basis="latest",
        financials_csv=str(csv),
    )
    allocs = {a["ticker"]: a for a in out["allocations"]}  # type: ignore[union-attr]
    assert allocs["B"]["shares"] > allocs["A"]["shares"]


def test_optimize_ignored_for_fixed_share_modes() -> None:
    out = simulate_portfolio(
        budget=0,
        holdings=[{"ticker": "A", "price": 1000, "dividend_per_share": 40, "shares": 300}],
        auto_weight="shares",
        optimization="dividend_max",  # must not override fixed shares
        financials_csv=_NO_CSV,
    )
    assert out["allocations"][0]["shares"] == 300  # type: ignore[index]


def test_no_valid_holdings_returns_unavailable() -> None:
    out = simulate_portfolio(
        budget=1000, holdings=[{"ticker": "X", "price": 0}], financials_csv=_NO_CSV
    )
    assert out["available"] is False


def test_parse_close_from_quote_csv() -> None:
    text = (
        "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
        "8306.JP,2026-06-08,15:00:00,1590,1610,1585,1602,1000\n"
    )
    assert parse_close(text) == 1602.0
    assert parse_close("Symbol,Close\n8306.JP,N/D\n") is None
    assert parse_close("") is None


def test_fetch_prices_with_injected_fetch() -> None:
    def fake(url: str) -> str:
        _ = url
        return "Symbol,Date,Time,Open,High,Low,Close,Volume\nX.JP,2026,15,1,1,1,123.0,1\n"

    out = fetch_prices(["8306", "9432"], fetch=fake)
    prices = out["prices"]
    assert isinstance(prices, dict)
    assert prices["8306"] == 123.0 and prices["9432"] == 123.0


def test_fetch_prices_records_errors() -> None:
    def boom(url: str) -> str:
        raise RuntimeError("net")

    out = fetch_prices(["8306"], fetch=boom)
    assert out["prices"]["8306"] is None  # type: ignore[index]
    assert "8306" in out["notes"]  # type: ignore[operator]
