from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.portfolio.loader import (
    load_dividends,
    load_performance,
    summarize_dividends,
    summarize_performance,
)

ROOT = Path(__file__).resolve().parents[2]
DIVIDENDS = ROOT / "examples" / "portfolio_dividends_sample.csv"
PERFORMANCE = ROOT / "examples" / "portfolio_performance_sample.csv"


def test_load_dividends_sample() -> None:
    points = load_dividends(DIVIDENDS)

    assert len(points) == 6
    assert points[0].period == "2020"
    assert points[-1].dividend_received == 182400.0


def test_summarize_dividends_sample() -> None:
    summary = summarize_dividends(load_dividends(DIVIDENDS))

    assert summary["latest_annual"] == 182400.0
    assert summary["increase_streak"] == 6
    assert summary["avg_yield_pct"] == pytest.approx(3.13, abs=0.01)
    assert "投資助言" in str(summary["disclaimer"])


def test_load_performance_sample() -> None:
    points = load_performance(PERFORMANCE)

    assert len(points) == 6
    assert points[-1].pnl == 850000.0
    assert points[-1].pnl_pct == pytest.approx(18.6, abs=0.05)


def test_summarize_performance_sample() -> None:
    summary = summarize_performance(load_performance(PERFORMANCE))

    assert summary["market_value"] == 5420000.0
    assert summary["principal"] == 4570000.0
    assert summary["pnl"] == 850000.0
    assert summary["max_drawdown_pct"] == pytest.approx(-4.06, abs=0.05)


def test_dividend_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("period,dividend_received\n2020,100\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required CSV columns"):
        load_dividends(path)


def test_performance_rejects_negative(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "period,market_value,principal\n2025-01,-1,100\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=">= 0"):
        load_performance(path)
