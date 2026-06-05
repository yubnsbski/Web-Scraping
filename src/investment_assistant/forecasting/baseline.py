"""Simple local baseline forecasts for Phase 5."""

from __future__ import annotations

from collections.abc import Sequence

from investment_assistant.forecasting.models import ForecastPoint


def naive_forecast(points: Sequence[ForecastPoint], *, horizon: int) -> list[float]:
    """Forecast future values by repeating the latest observed value."""

    _validate_horizon(horizon)
    if not points:
        raise ValueError("points must not be empty")

    latest_value = points[-1].value
    return [latest_value for _ in range(horizon)]


def moving_average_forecast(
    points: Sequence[ForecastPoint],
    *,
    horizon: int,
    window: int,
) -> list[float]:
    """Forecast future values by repeating the trailing moving average."""

    _validate_horizon(horizon)
    if window <= 0:
        raise ValueError("window must be positive")
    if len(points) < window:
        raise ValueError("window must be less than or equal to the number of points")

    trailing_points = points[-window:]
    average = sum(point.value for point in trailing_points) / window
    return [average for _ in range(horizon)]


def _validate_horizon(horizon: int) -> None:
    if horizon <= 0:
        raise ValueError("horizon must be positive")
