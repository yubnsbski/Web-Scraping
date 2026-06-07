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
