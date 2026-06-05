"""Evaluation metrics for local forecasting workflows."""

from __future__ import annotations

import math
from collections.abc import Sequence


def _validate_pairs(
    actual: Sequence[float],
    predicted: Sequence[float],
) -> list[tuple[float, float]]:
    """Validate metric inputs and return numeric pairs."""

    if len(actual) != len(predicted):
        raise ValueError("actual and predicted must have the same length")
    if not actual:
        raise ValueError("actual and predicted must not be empty")

    return [
        (float(actual_value), float(predicted_value))
        for actual_value, predicted_value in zip(actual, predicted, strict=True)
    ]


def mean_absolute_error(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Calculate mean absolute error."""

    pairs = _validate_pairs(actual, predicted)
    total_error = sum(
        abs(actual_value - predicted_value) for actual_value, predicted_value in pairs
    )
    return total_error / len(pairs)


def root_mean_squared_error(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Calculate root mean squared error."""

    pairs = _validate_pairs(actual, predicted)
    mean_squared_error = sum(
        (actual_value - predicted_value) ** 2 for actual_value, predicted_value in pairs
    ) / len(pairs)
    return math.sqrt(mean_squared_error)


def mean_absolute_percentage_error(
    actual: Sequence[float],
    predicted: Sequence[float],
) -> float:
    """Calculate mean absolute percentage error as a ratio.

    For example, ``0.075`` means 7.5%.
    """

    pairs = _validate_pairs(actual, predicted)
    if any(actual_value == 0 for actual_value, _ in pairs):
        raise ValueError("actual values must not contain zero when calculating MAPE")

    total_percentage_error = sum(
        abs((actual_value - predicted_value) / actual_value)
        for actual_value, predicted_value in pairs
    )
    return total_percentage_error / len(pairs)
