"""Metric normalization helpers for local scoring."""

from __future__ import annotations


def normalize_higher_is_better(value: float, values: list[float]) -> float:
    """Normalize a metric where larger values are preferable."""

    return _normalize(value=value, values=values, higher_is_better=True)


def normalize_lower_is_better(value: float, values: list[float]) -> float:
    """Normalize a metric where smaller values are preferable."""

    return _normalize(value=value, values=values, higher_is_better=False)


def _normalize(*, value: float, values: list[float], higher_is_better: bool) -> float:
    if not values:
        msg = "Cannot normalize an empty value set."
        raise ValueError(msg)

    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return 1.0

    score = (value - minimum) / (maximum - minimum)
    if not higher_is_better:
        score = 1.0 - score
    return round(score, 6)
