"""Unit coverage for per-ticker forecasting from the daily-bars CSV."""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.portfolio.market_forecast import (
    forecast_all_tickers,
    forecast_ticker,
    screen_by_forecast,
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


def test_forecast_raises_clear_message_when_ticker_absent(tmp_path: Path) -> None:
    # 7203 has bars; 8306 has none -> a distinct "fetch its OHLCV first" message.
    path = _bars(tmp_path, "7203", [1000.0 + i for i in range(10)])
    with pytest.raises(ValueError, match="no daily-bars data for 8306"):
        forecast_ticker(daily_bars_csv=path, ticker="8306", include_ml=False)


def test_ticker_with_dot_t_suffix_matches_bare_code(tmp_path: Path) -> None:
    path = _bars(tmp_path, "7203", [1000.0 + i for i in range(10)])
    series = timeseries_from_daily_bars(path, "7203.T")
    assert len(series) == 10
    assert series.name == "7203"


def test_forecast_all_tickers_reads_once_and_skips_short(tmp_path: Path) -> None:
    lines = ["ticker,date,open,high,low,close,volume"]
    for i in range(20):  # 7203 has enough history
        c = 1000 + i * 10
        lines.append(f"7203,2026-05-{i + 1:02d},{c},{c},{c},{c},1")
    for i in range(3):  # 8306 is too short -> skipped
        lines.append(f"8306,2026-05-{i + 1:02d},500,500,500,500,1")
    path = tmp_path / "daily_bars.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = forecast_all_tickers(path, horizon=3, include_ml=False)
    assert set(out) == {"7203"}
    assert len(out["7203"]["forecast"]) == 3


def test_screen_ranks_by_expected_return_descending(tmp_path: Path) -> None:
    lines = ["ticker,date,open,high,low,close,volume"]
    for i in range(20):
        up = 1000 + i * 20  # rising
        flat = 2000  # flat
        down = 3000 - i * 15  # falling
        lines.append(f"7203,2026-05-{i + 1:02d},{up},{up},{up},{up},1")
        lines.append(f"8306,2026-05-{i + 1:02d},{flat},{flat},{flat},{flat},1")
        lines.append(f"9999,2026-05-{i + 1:02d},{down},{down},{down},{down},1")
    path = tmp_path / "daily_bars.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ranked = screen_by_forecast(path, horizon=5, include_ml=False, max_abs_return_pct=0.0)
    tickers = [row["ticker"] for row in ranked]
    assert tickers == ["7203", "8306", "9999"]  # high -> low expected return
    assert ranked[0]["expected_return_pct"] > 0
    assert ranked[-1]["expected_return_pct"] < 0
    assert all("backtest_rmse" in row and "rmse_pct" in row for row in ranked)


def test_screen_drops_implausible_extrapolation(tmp_path: Path) -> None:
    # A late price explosion makes the drift/ensemble forecast blow up; the
    # implausibility guard must keep that artifact out of the ranking.
    lines = ["ticker,date,open,high,low,close,volume"]
    for i in range(20):  # 1301 calm ~1% drift
        c = 1000 + i
        lines.append(f"1301,2026-05-{i + 1:02d},{c},{c},{c},{c},1")
    spike = [100, 105, 110, 115, 120, 130, 140, 150, 170, 200, 260, 360, 520, 760, 1100]
    for i, c in enumerate(spike):  # 9999 parabolic -> explosive forecast
        lines.append(f"9999,2026-05-{i + 1:02d},{c},{c},{c},{c},1")
    path = tmp_path / "daily_bars.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    guarded = {r["ticker"] for r in screen_by_forecast(path, include_ml=False)}
    unguarded = {
        r["ticker"]
        for r in screen_by_forecast(path, include_ml=False, max_abs_return_pct=0.0)
    }
    assert "9999" not in guarded  # artifact filtered (default 30% guard)
    assert "9999" in unguarded  # present without the guard
    assert "1301" in guarded  # plausible name retained


def test_screen_top_caps_results(tmp_path: Path) -> None:
    lines = ["ticker,date,open,high,low,close,volume"]
    for t in ("7203", "8306", "9999"):
        for i in range(20):
            c = 1000 + i * 5
            lines.append(f"{t},2026-05-{i + 1:02d},{c},{c},{c},{c},1")
    path = tmp_path / "daily_bars.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert len(screen_by_forecast(path, top=2, include_ml=False)) == 2
