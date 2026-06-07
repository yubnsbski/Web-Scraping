from __future__ import annotations

from datetime import datetime

from investment_assistant.scheduling import next_weekly_run

# 2026-06-08 is a Monday.


def test_same_monday_before_target_time_returns_today() -> None:
    now = datetime(2026, 6, 8, 5, 0)
    assert next_weekly_run(now, weekday=0, hour=6) == datetime(2026, 6, 8, 6, 0)


def test_same_monday_after_target_time_rolls_to_next_week() -> None:
    now = datetime(2026, 6, 8, 7, 0)
    assert next_weekly_run(now, weekday=0, hour=6) == datetime(2026, 6, 15, 6, 0)


def test_midweek_returns_following_monday() -> None:
    now = datetime(2026, 6, 10, 9, 30)  # Wednesday
    assert next_weekly_run(now, weekday=0, hour=6) == datetime(2026, 6, 15, 6, 0)


def test_sunday_returns_next_day_monday() -> None:
    now = datetime(2026, 6, 7, 23, 0)  # Sunday
    assert next_weekly_run(now, weekday=0, hour=6) == datetime(2026, 6, 8, 6, 0)


def test_result_is_always_target_weekday_and_time_in_future() -> None:
    for day in range(8, 15):
        now = datetime(2026, 6, day, 12, 0)
        nxt = next_weekly_run(now, weekday=0, hour=6)
        assert nxt.weekday() == 0
        assert (nxt.hour, nxt.minute) == (6, 0)
        assert nxt > now
        assert (nxt - now).days < 7
