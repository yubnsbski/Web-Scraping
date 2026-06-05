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


def directional_accuracy(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Calculate the share of matching step-to-step directions.

    The result is a ratio from 0.0 to 1.0. This is a diagnostic metric only
    and does not guarantee investment returns.
    """

    pairs = _validate_pairs(actual, predicted)
    if len(pairs) < 2:
        raise ValueError("actual and predicted must contain at least two values")

    actual_directions = [
        _direction(current_actual - previous_actual)
        for (previous_actual, _), (current_actual, _) in zip(
            pairs[:-1],
            pairs[1:],
            strict=True,
        )
    ]
    predicted_directions = [
        _direction(current_predicted - previous_predicted)
        for (_, previous_predicted), (_, current_predicted) in zip(
            pairs[:-1],
            pairs[1:],
            strict=True,
        )
    ]

    matches = sum(
        actual_direction == predicted_direction
        for actual_direction, predicted_direction in zip(
            actual_directions,
            predicted_directions,
            strict=True,
        )
    )
    return matches / len(actual_directions)


def _direction(delta: float) -> int:
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0
