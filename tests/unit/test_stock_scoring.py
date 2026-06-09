"""Tests for EDINET-financials-based stock scoring."""

from __future__ import annotations

from pathlib import Path

from investment_assistant.scoring.stock import (
    STRATEGY_PRESETS,
    StockScoreWeights,
    build_stock_metrics,
    run_stock_scoring,
    score_for_ticker,
    score_stocks,
)

_CSV_HEADER = "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"


def _comparison() -> dict[str, object]:
    return {
        "companies": [
            {
                "ticker": "A",
                "name": "Strong",
                "latest_dividend_per_share": 50.0,
                "dividend_trend": "increasing",
                "dividend_cut_years": [],
                "latest_equity_ratio": 60.0,
                "operating_cf_trend": "increasing",
                "dividend_series": [40.0, 45.0, 50.0],
            },
            {
                "ticker": "B",
                "name": "Weak",
                "latest_dividend_per_share": 10.0,
                "dividend_trend": "declining",
                "dividend_cut_years": [2023, 2024],
                "latest_equity_ratio": 20.0,
                "operating_cf_trend": "declining",
                "dividend_series": [30.0, 20.0, 10.0],
            },
            {
                "ticker": "C",
                "name": "Mid",
                "latest_dividend_per_share": 30.0,
                "dividend_trend": "flat",
                "dividend_cut_years": [],
                "latest_equity_ratio": 40.0,
                "operating_cf_trend": "flat",
                "dividend_series": [30.0, 30.0, 30.0],
            },
        ]
    }


def test_build_metrics_and_ranking_order() -> None:
    metrics = build_stock_metrics(_comparison())
    assert {m.ticker for m in metrics} == {"A", "B", "C"}
    ranked = score_stocks(metrics)
    assert [s.ticker for s in ranked] == ["A", "C", "B"]
    assert ranked[0].rank == 1
    assert 0.0 <= ranked[0].total_score <= 1.0
    assert any("減配なし" in note for note in ranked[0].rationale)


def test_filters_exclude_cuts_and_low_equity() -> None:
    metrics = build_stock_metrics(_comparison())
    out = score_stocks(metrics, exclude_dividend_cut=True)
    assert "B" not in {s.ticker for s in out}  # B had dividend cuts
    out2 = score_stocks(metrics, min_equity_ratio=35.0)
    assert {s.ticker for s in out2} == {"A", "C"}  # B equity 20 < 35


def test_presets_reweight() -> None:
    assert set(STRATEGY_PRESETS) == {"balanced", "high_yield", "defensive", "growth"}
    w = STRATEGY_PRESETS["high_yield"].normalized()
    assert w.dividend_level > w.equity_ratio  # high-yield favours dividend level
    total = (
        w.dividend_level + w.dividend_trend + w.dividend_safety + w.equity_ratio + w.operating_cf
    )
    assert abs(total - 1.0) < 1e-9


def _write_csv(tmp_path: Path) -> Path:
    path = tmp_path / "financials.csv"
    path.write_text(
        _CSV_HEADER
        + "8306,MUFG,2023,1000,5.0,32,安定配当\n"
        + "8306,MUFG,2024,1100,5.2,41,安定配当\n"
        + "9999,Cutter,2023,500,30,40,記載なし\n"
        + "9999,Cutter,2024,400,28,25,記載なし\n",
        encoding="utf-8",
    )
    return path


def test_run_stock_scoring_from_csv(tmp_path: Path) -> None:
    result = run_stock_scoring(financials_csv=str(_write_csv(tmp_path)), strategy="high_yield")
    assert result["available"] is True
    assert result["strategy"] == "high_yield"
    assert result["count"] == 2
    tickers = [row["ticker"] for row in result["results"]]  # type: ignore[index]
    assert set(tickers) == {"8306", "9999"}


def test_run_stock_scoring_missing_csv(tmp_path: Path) -> None:
    result = run_stock_scoring(financials_csv=str(tmp_path / "nope.csv"))
    assert result["available"] is False
    assert result["results"] == []


def test_score_for_ticker(tmp_path: Path) -> None:
    row = score_for_ticker(ticker="8306", financials_csv=str(_write_csv(tmp_path)))
    assert row is not None
    assert row["ticker"] == "8306"
    assert "total_score" in row
    assert score_for_ticker(ticker="0000", financials_csv=str(_write_csv(tmp_path))) is None


def test_weights_reject_all_zero() -> None:
    import pytest

    with pytest.raises(ValueError, match="positive"):
        StockScoreWeights(0, 0, 0, 0, 0).normalized()
