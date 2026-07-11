"""Compute consecutive dividend raise (or hold) years from dividend history.

Accepts both dict records (as returned by InvestmentDataStore.dividend_history)
and DividendHistory dataclass instances — both have .fiscal_year and .dps.

Definition used here:
  - A year "qualifies" if DPS >= previous year's DPS (raise or hold)
  - A cut (DPS < prev) resets the streak to 0
  - The streak is counted from the most recent year backwards

Returns 0 if there is insufficient history (< 2 years).
"""

from __future__ import annotations


def _fy(record) -> int:
    return record["fiscal_year"] if isinstance(record, dict) else record.fiscal_year


def _dps(record) -> float:
    return float(record["dps"] if isinstance(record, dict) else record.dps)


def consecutive_raises(history: list) -> int:
    """Return number of consecutive years of DPS raise-or-hold ending at most recent year."""
    if len(history) < 2:
        return 0

    sorted_h = sorted(history, key=_fy, reverse=True)  # newest first
    streak = 0
    for curr, prev in zip(sorted_h, sorted_h[1:]):
        if _dps(curr) >= _dps(prev):
            streak += 1
        else:
            break
    return streak


def did_raise(history: list) -> bool:
    """Return True if the most recent year had a DPS increase over the prior year."""
    if len(history) < 2:
        return False
    sorted_h = sorted(history, key=_fy, reverse=True)
    return _dps(sorted_h[0]) > _dps(sorted_h[1])
