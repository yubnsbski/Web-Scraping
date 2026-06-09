"""Dividend and portfolio performance analytics."""

from investment_assistant.portfolio.loader import (
    load_dividends,
    load_performance,
    summarize_dividends,
    summarize_performance,
)

__all__ = [
    "load_dividends",
    "load_performance",
    "summarize_dividends",
    "summarize_performance",
]
