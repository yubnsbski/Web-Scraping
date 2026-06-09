"""Ensemble forecaster that combines several base forecasters.

Supported combination methods:

* ``mean`` / ``median`` -- simple unweighted combinations, robust and hard to
  beat when members are diverse and individually decent.
* ``weighted`` -- inverse-error weighting. Members are scored on a chronological
  validation tail (RMSE), and weights are proportional to ``1 / RMSE`` so more
  accurate members contribute more. Members are then refit on the full history.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median

from investment_assistant.forecasting.metrics import rmse
from investment_assistant.forecasting.models import Forecaster

_METHODS = ("mean", "median", "weighted")


class EnsembleForecaster:
    """Combine member forecasters into a single forecast."""

    def __init__(
        self,
        members: Sequence[Forecaster],
        *,
        method: str = "mean",
        validation_size: int = 12,
        weight_power: float = 2.0,
    ) -> None:
        if not members:
            msg = "ensemble needs at least one member"
            raise ValueError(msg)
        if method not in _METHODS:
            msg = f"method must be one of {_METHODS}, got {method!r}"
            raise ValueError(msg)
        if weight_power < 0:
            msg = "weight_power must be non-negative"
            raise ValueError(msg)
        self.members = list(members)
        self.method = method
        self.validation_size = validation_size
        self.weight_power = weight_power
        self.name = f"ensemble_{method}"
        self.weights: list[float] = [1.0 / len(members)] * len(members)

    def fit(self, history: Sequence[float]) -> None:
        if self.method == "weighted":
            self.weights = self._fit_weights(history)
        for member in self.members:
            member.fit(history)

    def predict(self, horizon: int) -> list[float]:
        member_predictions = [member.predict(horizon) for member in self.members]
        combined: list[float] = []
        for step in range(horizon):
            step_values = [predictions[step] for predictions in member_predictions]
            combined.append(self._combine(step_values))
        return combined

    def _combine(self, values: list[float]) -> float:
        if self.method == "median":
            return float(median(values))
        if self.method == "weighted":
            return sum(weight * value for weight, value in zip(self.weights, values, strict=True))
        return sum(values) / len(values)

    def _fit_weights(self, history: Sequence[float]) -> list[float]:
        usable = min(self.validation_size, max(1, len(history) // 5))
        if len(history) - usable < 2:
            return [1.0 / len(self.members)] * len(self.members)
        train = history[:-usable]
        validation = history[-usable:]

        errors: list[float] = []
        for member in self.members:
            try:
                member.fit(train)
                predictions = member.predict(len(validation))
                error = rmse(validation, predictions)
            except (ValueError, RuntimeError):
                error = float("inf")
            errors.append(error if error > 0 else 1e-9)

        # Raise inverse error to ``weight_power`` so badly misspecified members
        # (e.g. a linear trend on a non-stationary price level) are driven to
        # near-zero weight instead of quietly biasing the combination.
        inverse = [
            0.0 if error == float("inf") else (1.0 / error) ** self.weight_power
            for error in errors
        ]
        total = sum(inverse)
        if total <= 0:
            return [1.0 / len(self.members)] * len(self.members)
        return [value / total for value in inverse]
