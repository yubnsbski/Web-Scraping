"""Unit tests for :mod:`investment_assistant.papertrade.calendar`."""

from __future__ import annotations

import pytest

from investment_assistant.papertrade.calendar import TradingCalendar

DATES = [
    "2026-01-05",
    "2026-01-06",
    "2026-01-07",
    "2026-01-08",
    "2026-01-09",
]


def test_calendar_dedupes_and_sorts() -> None:
    cal = TradingCalendar(["2026-01-07", "2026-01-05", "2026-01-05", "2026-01-06"])
    assert cal.dates == ("2026-01-05", "2026-01-06", "2026-01-07")
    assert len(cal) == 3
    assert list(cal) == ["2026-01-05", "2026-01-06", "2026-01-07"]


def test_next_day_returns_following_date() -> None:
    cal = TradingCalendar(DATES)
    assert cal.next_day("2026-01-05") == "2026-01-06"
    assert cal.next_day("2026-01-08") == "2026-01-09"


def test_next_day_at_end_returns_none() -> None:
    cal = TradingCalendar(DATES)
    assert cal.next_day("2026-01-09") is None


def test_next_day_unknown_date_returns_none() -> None:
    cal = TradingCalendar(DATES)
    assert cal.next_day("2099-01-01") is None


def test_days_between_is_inclusive() -> None:
    cal = TradingCalendar(DATES)
    assert cal.days_between("2026-01-06", "2026-01-08") == [
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
    ]


def test_days_between_tolerates_non_calendar_bounds() -> None:
    cal = TradingCalendar(DATES)
    # start/end need not themselves be trading dates.
    assert cal.days_between("2026-01-04", "2026-01-10") == DATES


def test_nth_after_positive_and_negative() -> None:
    cal = TradingCalendar(DATES)
    assert cal.nth_after("2026-01-06", 2) == "2026-01-08"
    assert cal.nth_after("2026-01-08", -2) == "2026-01-06"
    assert cal.nth_after("2026-01-06", 0) == "2026-01-06"


def test_nth_after_out_of_range_returns_none() -> None:
    cal = TradingCalendar(DATES)
    assert cal.nth_after("2026-01-09", 1) is None
    assert cal.nth_after("2026-01-05", -1) is None


def test_add_business_days_t_plus_2() -> None:
    cal = TradingCalendar(DATES)
    assert cal.add_business_days("2026-01-05", 2) == "2026-01-07"


def test_add_business_days_past_calendar_end_raises() -> None:
    """Documented choice: settlement dates must be known, never fabricated."""

    cal = TradingCalendar(DATES)
    with pytest.raises(ValueError, match="settlement date"):
        cal.add_business_days("2026-01-08", 2)


def test_add_business_days_unknown_date_raises() -> None:
    cal = TradingCalendar(DATES)
    with pytest.raises(ValueError):
        cal.add_business_days("2099-01-01", 2)


def test_windows_splits_into_consecutive_cycles_with_prior_decision_date() -> None:
    # 12 trading dates, warmup=2, cycle_length=3 -> cycles start at idx 2, 5, 8
    # (idx 11 has only 1 day left, dropped as a partial trailing cycle).
    dates = [f"2026-01-{d:02d}" for d in range(1, 13)]
    cal = TradingCalendar(dates)
    windows = cal.windows(cycle_length=3, warmup=2)
    assert windows == [
        ("2026-01-02", "2026-01-03", "2026-01-05"),
        ("2026-01-05", "2026-01-06", "2026-01-08"),
        ("2026-01-08", "2026-01-09", "2026-01-11"),
    ]


def test_windows_drops_short_trailing_cycle() -> None:
    dates = [f"2026-01-{d:02d}" for d in range(1, 8)]  # 7 dates
    cal = TradingCalendar(dates)
    # warmup=1 -> 6 dates left, cycle_length=4 -> only one full cycle fits.
    windows = cal.windows(cycle_length=4, warmup=1)
    assert len(windows) == 1
    assert windows[0] == ("2026-01-01", "2026-01-02", "2026-01-05")


def test_windows_requires_warmup_at_least_one() -> None:
    cal = TradingCalendar(DATES)
    with pytest.raises(ValueError):
        cal.windows(cycle_length=2, warmup=0)


def test_windows_requires_positive_cycle_length() -> None:
    cal = TradingCalendar(DATES)
    with pytest.raises(ValueError):
        cal.windows(cycle_length=0, warmup=1)
