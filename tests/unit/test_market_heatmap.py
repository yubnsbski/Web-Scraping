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


def test_heatmap_uses_builtin_name_when_csv_has_none(tmp_path: Path) -> None:
    bars = tmp_path / "daily_bars.csv"
    bars.write_text(
        "ticker,date,close\n6758,2026-03-26,3200\n6758,2026-03-27,3140\n",
        encoding="utf-8",
    )
    # No names provided from CSVs -> falls back to the built-in dictionary.
    result = build_market_heatmap(bars, tickers=["6758"])
    assert result["cells"][0]["name"] == "ソニーグループ"

    # An explicit CSV name still wins over the built-in fallback.
    result2 = build_market_heatmap(bars, tickers=["6758"], names={"6758": "SONY (CSV)"})
    assert result2["cells"][0]["name"] == "SONY (CSV)"

    # A CSV "name" equal to the bare code is ignored -> built-in name wins.
    result3 = build_market_heatmap(bars, tickers=["6758"], names={"6758": "6758"})
    assert result3["cells"][0]["name"] == "ソニーグループ"


def test_heatmap_uses_current_price_for_today_move(tmp_path: Path) -> None:
    # With an intraday current price, the cell shows it and the change is
    # measured against the latest daily close (today's move), not the prior day.
    result = build_market_heatmap(
        _write(tmp_path),
        tickers=["7203"],
        current_prices={"7203": 2850.0},
    )
    cell = result["cells"][0]
    assert cell["price_source"] == "intraday"
    assert cell["last_close"] == 2850.0
    assert cell["prev_close"] == 2776.5  # latest daily close is the reference
    assert cell["change_pct"] == 2.65  # (2850-2776.5)/2776.5*100


def test_heatmap_falls_back_to_daily_close_without_current_price(tmp_path: Path) -> None:
    result = build_market_heatmap(_write(tmp_path), tickers=["7203"])
    cell = result["cells"][0]
    assert cell["price_source"] == "daily_close"
    assert cell["last_close"] == 2776.5
    assert cell["change_pct"] == 2.83
    # sparkline = recent closes (chronological)
    assert cell["spark"] == [2700.0, 2776.5]


def test_heatmap_spark_appends_intraday_price(tmp_path: Path) -> None:
    cell = build_market_heatmap(
        _write(tmp_path), tickers=["7203"], current_prices={"7203": 2850.0}
    )["cells"][0]
    assert cell["spark"] == [2700.0, 2776.5, 2850.0]  # current appended


def test_heatmap_current_price_equal_to_close_uses_daily_move(tmp_path: Path) -> None:
    # When the "current" price equals the latest close (market closed / price
    # derived from the close), show the last completed day's move, not a flat 0%.
    result = build_market_heatmap(
        _write(tmp_path),
        tickers=["7203"],
        current_prices={"7203": 2776.5},  # == latest daily close
    )
    cell = result["cells"][0]
    assert cell["price_source"] == "daily_close"
    assert cell["change_pct"] == 2.83  # 7203's prior-day move, not 0.0


def test_heatmap_sort_change_puts_largest_move_first(tmp_path: Path) -> None:
    result = build_market_heatmap(_write(tmp_path), sort_by="change")
    # 7203 (+2.83%) has a larger absolute move than 8306 (-1.0%); 9999 (None) last.
    order = [cell["ticker"] for cell in result["cells"]]
    assert order[0] == "7203"
    assert order[-1] == "9999"
