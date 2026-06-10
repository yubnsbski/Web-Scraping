"""Data models for cross-company financial comparison."""

from __future__ import annotations

from dataclasses import dataclass

FINANCIAL_COLUMNS: tuple[str, ...] = (
    "ticker",
    "name",
    "fiscal_year",
    "operating_cf",
    "equity_ratio",
    "dividend_per_share",
    "payout_policy",
)


def equity_ratio_to_percent(value: float | None) -> float | None:
    """Normalise a 自己資本比率 to a 0–100 percentage.

    EDINET reports the equity ratio as a 0–1 fraction (e.g. ``0.766``), while
    user-supplied CSVs and internal thresholds (safety haircuts, scoring
    filters) expect a percentage (``76.6``). Convert the 0–1 form to percent and
    leave already-percent values untouched so the helper is idempotent. ``None``
    and non-positive values pass through unchanged.
    """

    if value is None:
        return None
    if 0.0 < value <= 1.0:
        return value * 100.0
    return value


@dataclass(frozen=True)
class FinancialPoint:
    """One fiscal year of a single company financial record."""

    ticker: str
    name: str
    fiscal_year: int
    operating_cf: float
    equity_ratio: float
    dividend_per_share: float
    payout_policy: str
