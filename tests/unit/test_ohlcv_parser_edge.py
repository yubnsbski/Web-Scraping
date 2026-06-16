"""Edge-case robustness coverage for the Yahoo v8 chart OHLCV parser.

Additive / conflict-light: locks behaviors the main test file does not assert —
gmtoffset date shifting, ragged (length-mismatched) quote arrays, and volume 0
preservation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from investment_assistant.portfolio.ohlcv import parse_yahoo_ohlcv


def _epoch(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp())


def _chart(timestamps: list[int], quote: dict[str, list], *, gmtoffset: int = 0) -> str:
    return json.dumps(
        {"chart": {"result": [{"meta": {"gmtoffset": gmtoffset},
                               "timestamp": timestamps,
                               "indicators": {"quote": [quote]}}], "error": None}}
    )


def _full_quote(n: int) -> dict[str, list]:
    return {
        "open": [10.0 + i for i in range(n)],
        "high": [11.0 + i for i in range(n)],
        "low": [9.0 + i for i in range(n)],
        "close": [10.5 + i for i in range(n)],
        "volume": [100 + i for i in range(n)],
    }


def test_gmtoffset_shifts_bar_date_to_local_trading_day() -> None:
    ts = [_epoch(2024, 6, 10, 20)]  # 20:00 UTC

    # No offset -> the UTC date.
    assert parse_yahoo_ohlcv(_chart(ts, _full_quote(1), gmtoffset=0))[0].date == "2024-06-10"
    # JST (+9h) -> 05:00 the next local day.
    assert parse_yahoo_ohlcv(_chart(ts, _full_quote(1), gmtoffset=32400))[0].date == "2024-06-11"


def test_ragged_quote_arrays_do_not_crash_and_fill_none() -> None:
    # 2 timestamps but `open` only has 1 element -> the second open is None,
    # other fields still read; no IndexError.
    ts = [_epoch(2024, 6, 10), _epoch(2024, 6, 11)]
    quote = {
        "open": [10.0],
        "high": [11.0, 12.0],
        "low": [9.0, 9.5],
        "close": [10.5, 11.5],
        "volume": [100, 200],
    }
    bars = parse_yahoo_ohlcv(_chart(ts, quote))
    assert len(bars) == 2
    assert bars[0].open == 10.0
    assert bars[1].open is None and bars[1].close == 11.5


def test_zero_volume_is_preserved_not_dropped() -> None:
    quote = {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [0]}
    assert parse_yahoo_ohlcv(_chart([_epoch(2024, 6, 10)], quote))[0].volume == 0


def test_fully_null_rows_dropped_keeping_neighbours() -> None:
    ts = [_epoch(2024, 6, 10), _epoch(2024, 6, 11), _epoch(2024, 6, 12)]
    quote = {
        "open": [10.0, None, 12.0],
        "high": [11.0, None, 13.0],
        "low": [9.0, None, 11.0],
        "close": [10.5, None, 12.5],
        "volume": [100, None, 300],
    }
    bars = parse_yahoo_ohlcv(_chart(ts, quote))
    assert [b.date for b in bars] == ["2024-06-10", "2024-06-12"]
