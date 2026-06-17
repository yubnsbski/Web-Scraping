"""Edge coverage for the dividend-quality stock scorer.

Additive / conflict-light: locks behaviors the main scoring test does not assert
— the dividend-cut safety penalty curve, all-equal normalization, the
min_periods filter, and the score-tie ticker tie-break.
"""

from __future__ import annotations

from investment_assistant.scoring.stock import StockMetrics, score_stocks


def _metric(
    ticker: str,
    *,
    cut: int = 0,
    dividend: float = 100.0,
    equity: float = 50.0,
    periods: int = 3,
) -> StockMetrics:
    return StockMetrics(
        ticker=ticker,
        name=ticker,
        dividend_latest=dividend,
        dividend_trend="flat",
        cut_count=cut,
        equity_ratio=equity,
        operating_cf_trend="flat",
        periods=periods,
    )


def test_dividend_cut_safety_penalty_curve_caps_at_three() -> None:
    expected = {0: 1.0, 1: 0.6667, 2: 0.3333, 3: 0.0, 5: 0.0}
    for cut, safety in expected.items():
        row = score_stocks([_metric("A", cut=cut)])[0]
        assert row.breakdown["dividend_safety"] == safety


def test_all_equal_dividends_normalize_to_full_level() -> None:
    out = {s.ticker: s.breakdown["dividend_level"] for s in score_stocks(
        [_metric("A", dividend=100.0), _metric("B", dividend=100.0)]
    )}
    assert out == {"A": 1.0, "B": 1.0}


def test_min_periods_filters_single_period_tickers() -> None:
    ranked = score_stocks(
        [_metric("A", periods=1), _metric("B", periods=3)], min_periods=2
    )
    assert [s.ticker for s in ranked] == ["B"]


def test_equal_scores_break_ties_by_ticker_ascending() -> None:
    ranked = score_stocks([_metric("Z"), _metric("A")])
    assert [s.ticker for s in ranked] == ["A", "Z"]
    assert [s.rank for s in ranked] == [1, 2]
