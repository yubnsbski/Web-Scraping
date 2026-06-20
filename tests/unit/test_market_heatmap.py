"""Deterministic price heat-map aggregation from daily bars."""

from __future__ import annotations

from pathlib import Path

from investment_assistant.portfolio.market_heatmap import build_market_heatmap

DAILY_BARS = (
    "ticker,date,open,high,low,close,volume\n"
    "7203,2026-03-26,2700,2710,2680,2700,100\n"
    "7203,2026-03-27,2710,2790,2705,2776.5,120\n"
    "8306,2026-03-26,2000,2010,1990,2000,50\n"
    "8306,2026-03-27,1990,2000,1970,1980,60\n"
    "9999,2026-03-27,500,510,495,500,10\n"  # single bar -> no prev close
)


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "daily_bars.csv"
    path.write_text(DAILY_BARS, encoding="utf-8")
    return path


def test_heatmap_computes_day_over_day_change(tmp_path: Path) -> None:
    result = build_market_heatmap(_write(tmp_path), sort_by="ticker")
    cells = {cell["ticker"]: cell for cell in result["cells"]}

    assert cells["7203"]["last_close"] == 2776.5
    assert cells["7203"]["change_pct"] == 2.83  # (2776.5-2700)/2700*100
    assert cells["8306"]["change_pct"] == -1.0  # (1980-2000)/2000*100
    assert cells["9999"]["change_pct"] is None  # only one bar
    assert result["as_of"] == "2026-03-27"
    assert result["auto_trading"] is False


def test_heatmap_filters_to_watchlist_and_names(tmp_path: Path) -> None:
    result = build_market_heatmap(
        _write(tmp_path),
        tickers=["8306"],
        names={"8306": "三菱UFJ"},
    )
    assert result["count"] == 1
    cell = result["cells"][0]
    assert cell["ticker"] == "8306"
    assert cell["name"] == "三菱UFJ"


def test_heatmap_sort_change_puts_largest_move_first(tmp_path: Path) -> None:
    result = build_market_heatmap(_write(tmp_path), sort_by="change")
    # 7203 (+2.83%) has a larger absolute move than 8306 (-1.0%); 9999 (None) last.
    order = [cell["ticker"] for cell in result["cells"]]
    assert order[0] == "7203"
    assert order[-1] == "9999"
