"""Unit coverage for per-ticker forecasting from the daily-bars CSV."""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.portfolio.market_forecast import (
    forecast_ticker,
    timeseries_from_daily_bars,
)

_HEADER = "ticker,date,open,high,low,close,volume\n"


def _bars(tmp_path: Path, ticker: str, closes: list[float], *, noise: bool = True) -> Path:
    lines = [_HEADER.rstrip("\n")]
    for i, close in enumerate(closes, start=1):
        lines.append(f"{ticker},2026-05-{i:02d},{close},{close + 5},{close - 5},{close},1000")
    if noise:
        lines.append("9999,2026-05-01,1,1,1,1,1")  # other ticker must be ignored
    path = tmp_path / "daily_bars.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_timeseries_filters_ticker_and_orders_by_date(tmp_path: Path) -> None:
    path = tmp_path / "db.csv"
    path.write_text(
        _HEADER
        + "7203,2026-05-02,1,1,1,1010,1\n"
        + "7203,2026-05-01,1,1,1,1000,1\n"
        + "9999,2026-05-01,1,1,1,99,1\n",
        encoding="utf-8",
    )
    series = timeseries_from_daily_bars(path, "7203")
    assert series.values == (1000.0, 1010.0)  # chronological, 9999 excluded
    assert series.dates == ("2026-05-01", "2026-05-02")
    assert series.name == "7203"


def test_forecast_ticker_continues_trend_and_backtests(tmp_path: Path) -> None:
    path = _bars(tmp_path, "7203", [1000.0 + i * 10 for i in range(20)])
    result = forecast_ticker(daily_bars_csv=path, ticker="7203", horizon=3, include_ml=False)

    assert result["ticker"] == "7203"
    assert result["observations"] == 20
    assert result["last_close"] == 1190.0
    assert len(result["forecast"]) == 3
    # A steadily rising series should keep rising.
    assert result["forecast"][0] > result["last_close"]
    # 20 points >= eval threshold -> backtest populated.
    assert result["backtest_best_model"]
    assert isinstance(result["backtest_rmse"], float)
    assert result["auto_trading"] is False


def test_forecast_skips_backtest_for_short_series(tmp_path: Path) -> None:
    path = _bars(tmp_path, "7203", [1000.0 + i for i in range(10)])
    result = forecast_ticker(daily_bars_csv=path, ticker="7203", horizon=2, include_ml=False)
    assert len(result["forecast"]) == 2
    # 10 points < eval threshold -> no backtest keys, but the forecast still works.
    assert "backtest_best_model" not in result


def test_forecast_raises_for_too_few_points(tmp_path: Path) -> None:
    path = _bars(tmp_path, "7203", [1000.0, 1001.0, 1002.0])
    with pytest.raises(ValueError, match="not enough observations"):
        forecast_ticker(daily_bars_csv=path, ticker="7203", include_ml=False)
