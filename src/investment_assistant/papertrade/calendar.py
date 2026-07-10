"""Trading-day calendar derived from observed bar dates.

There is no external market-holiday calendar in this repo (offline-first --
see ``AGENTS.md``), so the walk-forward simulation's notion of "trading day"
is simply *a date on which the daily-bars dataset actually has a row*. This
sidesteps having to hardcode Japanese market holidays and stays correct as
long as ``daily_bars.csv`` itself only contains real trading dates (which
``papertrade.universe.load_daily_bars`` already guarantees by construction).

Two related-but-distinct lookups are exposed on purpose:

- :meth:`TradingCalendar.nth_after` is a general "N trading days after"
  lookup that returns ``None`` when the answer would fall outside the known
  calendar (e.g. past the last loaded bar date). Safe to probe.
- :meth:`TradingCalendar.add_business_days` is the same lookup used
  specifically for T+2 (受渡日) settlement-date recording, and *raises*
  instead of returning ``None``. A settlement date is a required field on a
  :class:`~investment_assistant.papertrade.account.Fill` record; silently
  returning ``None`` there would either crash later with a less useful error
  or (worse) get coerced into a wrong-looking string. Failing loudly at the
  point where the calendar ran out of known dates is more useful for a
  paper-trading engine that must never fabricate a trading date.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Iterator


class TradingCalendar:
    """Sorted, deduplicated set of ISO ``YYYY-MM-DD`` trading dates."""

    def __init__(self, dates: Iterable[str]) -> None:
        self._dates: tuple[str, ...] = tuple(sorted(set(dates)))

    def __len__(self) -> int:
        return len(self._dates)

    def __iter__(self) -> Iterator[str]:
        return iter(self._dates)

    @property
    def dates(self) -> tuple[str, ...]:
        """All known trading dates, ascending."""

        return self._dates

    def _index(self, date: str) -> int | None:
        idx = bisect.bisect_left(self._dates, date)
        if idx < len(self._dates) and self._dates[idx] == date:
            return idx
        return None

    def next_day(self, date: str) -> str | None:
        """The next known trading date after ``date``, or ``None`` at the end."""

        return self.nth_after(date, 1)

    def days_between(self, start: str, end: str) -> list[str]:
        """Known trading dates with ``start <= date <= end`` (both inclusive).

        ``start``/``end`` need not themselves be trading dates -- comparison
        is purely lexicographic, which is valid for ISO ``YYYY-MM-DD``
        strings.
        """

        lo = bisect.bisect_left(self._dates, start)
        hi = bisect.bisect_right(self._dates, end)
        return list(self._dates[lo:hi])

    def nth_after(self, date: str, n: int) -> str | None:
        """The trading date ``n`` positions after ``date`` (negative ``n`` allowed).

        Returns ``None`` if ``date`` is not itself a known trading date, or if
        the resulting position falls outside the known calendar.
        """

        idx = self._index(date)
        if idx is None:
            return None
        target = idx + n
        if target < 0 or target >= len(self._dates):
            return None
        return self._dates[target]

    def add_business_days(self, date: str, n: int) -> str:
        """T+``n`` settlement-date lookup. Raises if the answer is unknown.

        Unlike :meth:`nth_after`, this never returns ``None``: a settlement
        date is a required, non-optional field on a recorded fill, and this
        calendar has no way to extrapolate trading dates past the last
        observed bar, so guessing would be worse than failing loudly.
        """

        result = self.nth_after(date, n)
        if result is None:
            raise ValueError(
                f"cannot compute settlement date: {date!r} + {n} business day(s) "
                "falls outside the known trading calendar (date not found or "
                "past the last loaded bar date)"
            )
        return result

    def windows(self, cycle_length: int, warmup: int) -> list[tuple[str, str, str]]:
        """Split the calendar into consecutive walk-forward cycles.

        Returns a list of ``(decision_date, first_trade_date, last_date)``
        tuples. ``decision_date`` is the trading date immediately *before*
        ``first_trade_date`` -- the design doc's cycle loop makes its
        decision using only data through the prior day's close, then trades
        at the next day's open, so the decision date and the first trade
        date are never the same day (no look-ahead).

        The first ``warmup`` known trading dates are skipped entirely (not
        enough history to decide yet), then the remainder is chopped into
        consecutive blocks of ``cycle_length`` dates. A short trailing block
        (fewer than ``cycle_length`` dates left at the end of the calendar)
        is dropped rather than emitted as a partial cycle -- documented
        deviation: callers that want to use the tail should call
        :meth:`days_between` directly.

        ``warmup`` counts the decision date inclusively: ``warmup=1`` means
        the first date can be the decision date for a cycle whose first trade
        date is the second known date. This differs from
        ``papertrade.universe.build_universe(min_history=...)``, which counts
        only bars strictly before ``as_of``. The P2 engine must therefore pass
        ``as_of=first_trade_date`` when checking cycle-entry history, or add
        one to ``min_history`` if it passes the decision date instead.

        ``warmup`` must be >= 1 so every cycle has a valid prior decision
        date; ``cycle_length`` must be positive.
        """

        if cycle_length <= 0:
            raise ValueError("cycle_length must be positive")
        if warmup < 1:
            raise ValueError("warmup must be >= 1 (each cycle needs a prior decision date)")

        result: list[tuple[str, str, str]] = []
        start = warmup
        while start + cycle_length <= len(self._dates):
            first_trade_date = self._dates[start]
            last_date = self._dates[start + cycle_length - 1]
            decision_date = self._dates[start - 1]
            result.append((decision_date, first_trade_date, last_date))
            start += cycle_length
        return result
