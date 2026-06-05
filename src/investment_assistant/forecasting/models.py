"""Data models for local forecasting workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """One validated time-series observation for local forecasting."""

    date: date
    value: float
    symbol: str | None = None
