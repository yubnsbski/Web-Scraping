"""Gap detection + daily-bars merge backfill."""

from __future__ import annotations

import json
from pathlib import Path

from investment_assistant import cli
from investment_assistant.portfolio._market_common import DEFAULT_YAHOO_RATE_LIMIT_POLICY
from investment_assistant.portfolio.market_gaps import find_market_gaps

DAILY_BARS = (
    "ticker,date,open,high,low,close,volume\n"
    "7203,2026-03-26,2700,2710,2680,2700,100\n"
    "7203,2026-03-27,2710,2790,2705,2776.5,120\n"
    "8306,2026-03-27,2000,2010,1990,1980,60\n"  # only one bar
)
FINANCIALS = (
    "ticker,name,price,per,pbr,dps,dividend_yield,dividend_yield_percent,eps,market_cap\n"
    "7203,トヨタ,2776.5,,,,,,,\n"  # has price
    "8306,三菱UFJ,,,,,,,,\n"  # no price
)


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    bars = tmp_path / "daily_bars.csv"
    bars.write_text(DAILY_BARS, encoding="utf-8")
    fin = tmp_path / "yahoo_financials.csv"
    fin.write_text(FINANCIALS, encoding="utf-8")
    return bars, fin


def test_find_market_gaps_classifies_missing(tmp_path: Path) -> None:
    bars, fin = _setup(tmp_path)
    gaps = find_market_gaps(
        ["7203", "8306", "9433"], daily_bars_csv=bars, financials_csv=fin
    )
    assert gaps["complete"] == ["7203"]
    assert set(gaps["missing_price"]) == {"8306", "9433"}
    assert set(gaps["missing_bars"]) == {"8306", "9433"}  # 8306 has 1 bar, 9433 none
    assert set(gaps["missing_any"]) == {"8306", "9433"}
    assert gaps["counts"]["complete"] == 1


def _ohlcv_payload(close: float) -> str:
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [1_700_000_000, 1_700_086_400],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [close - 5, close - 2],
                                    "high": [close, close + 3],
                                    "low": [close - 8, close - 4],
                                    "close": [close - 5, close],
                                    "volume": [1000, 1200],
                                }
                            ]
                        },
                        "meta": {"gmtoffset": 32400},
                    }
                ]
            }
        }
    )


def test_bars_backfill_merges_without_wiping_existing(tmp_path: Path) -> None:
    bars, _ = _setup(tmp_path)
    result = cli.run_market_bars_backfill(
        tickers=["9433"],
        daily_bars_path=bars,
        fetch=lambda _url: _ohlcv_payload(5000.0),
        rate_limit_policy=DEFAULT_YAHOO_RATE_LIMIT_POLICY.with_sleeper(lambda _: None),
    )
    assert result["rows_written"] == 2
    text = bars.read_text(encoding="utf-8-sig")
    # existing tickers preserved, new ticker added
    assert "7203" in text
    assert "8306" in text
    assert "9433" in text
    # 9433 now has >=2 bars -> no longer a bar gap
    gaps = find_market_gaps(["9433"], daily_bars_csv=bars, financials_csv=tmp_path / "none.csv")
    assert gaps["missing_bars"] == []
