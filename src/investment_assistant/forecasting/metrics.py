"""Forecast error metrics implemented with the Python standard library."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastMetrics:
    """Standard error metrics for a set of point forecasts."""

    count: int
    mae: float
    rmse: float
    mape: float
    directional_accuracy: float

    def to_dict(self) -> dict[str, float | int]:
        """Return a JSON-friendly representation."""

        return {
            "count": self.count,
            "mae": self.mae,
            "rmse": self.rmse,
            "mape": self.mape,
            "directional_accuracy": self.directional_accuracy,
        }


def mae(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    """Mean absolute error."""

    _check_pair(actuals, forecasts)
    return sum(abs(a - f) for a, f in zip(actuals, forecasts, strict=True)) / len(actuals)


def rmse(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    """Root mean squared error."""

    _check_pair(actuals, forecasts)
    squared = sum((a - f) ** 2 for a, f in zip(actuals, forecasts, strict=True))
    return math.sqrt(squared / len(actuals))


def mape(actuals: Sequence[float], forecasts: Sequence[float]) -> float:
    """Mean absolute percentage error (%), skipping zero actuals."""

    _check_pair(actuals, forecasts)
    terms = [
        abs((a - f) / a) for a, f in zip(actuals, forecasts, strict=True) if a != 0
    ]
    if not terms:
        return float("nan")
    return 100.0 * sum(terms) / len(terms)


def directional_accuracy(
    previous: Sequence[float],
    actuals: Sequence[float],
    forecasts: Sequence[float],
) -> float:
    """Fraction of steps where the forecast got the direction of change right.

    ``previous`` is the last observed value before each forecast step, so the
    sign of ``actual - previous`` is compared to the sign of ``forecast -
    previous``.
    """

    if not (len(previous) == len(actuals) == len(forecasts)):
        msg = "previous, actuals, and forecasts must have equal length"
        raise ValueError(msg)
    if not actuals:
        return float("nan")
    hits = 0
    for prev, actual, forecast in zip(previous, actuals, forecasts, strict=True):
        if _sign(actual - prev) == _sign(forecast - prev):
            hits += 1
    return hits / len(actuals)


def skill_score(model_rmse: float, baseline_rmse: float) -> float:
    """Skill score vs a baseline: 1 means perfect, 0 means equal, <0 worse."""

    if baseline_rmse == 0:
        return float("nan")
    return 1.0 - (model_rmse / baseline_rmse)


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _check_pair(actuals: Sequence[float], forecasts: Sequence[float]) -> None:
    if len(actuals) != len(forecasts):
        msg = "actuals and forecasts must have equal length"
        raise ValueError(msg)
    if not actuals:
        msg = "at least one observation is required"
        raise ValueError(msg)
