"""Deterministic investment-only MVP helpers."""

from investment_assistant.investment.analysis import analyze_portfolio
from investment_assistant.investment.candidates import screen_candidates
from investment_assistant.investment.loader import (
    fund_profiles_from_payload,
    holdings_from_payload,
)
from investment_assistant.investment.reporting import build_investment_monthly_report

__all__ = [
    "analyze_portfolio",
    "build_investment_monthly_report",
    "fund_profiles_from_payload",
    "holdings_from_payload",
    "screen_candidates",
]
