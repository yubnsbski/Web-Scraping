"""Small, dependency-free scheduling helpers.

Kept in the package (rather than inline in the scripts/ scheduler) so the timing
logic is unit-testable without spinning up the long-running scheduler loop.
"""

from __future__ import annotations

from datetime import datetime, timedelta

MONDAY = 0


def next_weekly_run(
    now: datetime,
    *,
    weekday: int = MONDAY,
    hour: int = 6,
    minute: int = 0,
) -> datetime:
    """Return the next occurrence of ``weekday`` at ``hour:minute`` after ``now``.

    ``weekday`` follows :meth:`datetime.weekday` (Monday=0 … Sunday=6). When
    ``now`` is exactly on the target weekday but the time has already passed, the
    result rolls forward a full week.
    """

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (weekday - now.weekday()) % 7
    target += timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return target
