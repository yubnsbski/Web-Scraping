"""Base forecasting models implemented with the Python standard library.

Each model implements the :class:`Forecaster` protocol: ``fit`` on a history of
float values, then ``predict`` a number of future steps. Multi-step forecasts
are produced recursively (feeding predictions back in) where applicable.

These models have no third-party dependencies so the classical ensemble and its
backtest evaluation always run, including in CI without optional ML extras.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Forecaster(Protocol):
    """Common interface for all forecasters and the ensemble."""

    name: str

    def fit(self, history: Sequence[float]) -> None:
        """Fit the model to an ordered history of observations."""

    def predict(self, horizon: int) -> list[float]:
        """Return ``horizon`` future point forecasts."""


class NaiveForecaster:
    """Persistence baseline: every future value equals the last observation."""

    name = "naive"

    def __init__(self) -> None:
        self._last = 0.0

    def fit(self, history: Sequence[float]) -> None:
        _require_history(history, 1)
        self._last = float(history[-1])

    def predict(self, horizon: int) -> list[float]:
        _require_horizon(horizon)
        return [self._last] * horizon


class DriftForecaster:
    """Linear drift: extrapolate the average per-step change from the history."""

    name = "drift"

    def __init__(self) -> None:
        self._last = 0.0
        self._drift = 0.0

    def fit(self, history: Sequence[float]) -> None:
        _require_history(history, 2)
        self._last = float(history[-1])
        self._drift = (float(history[-1]) - float(history[0])) / (len(history) - 1)

    def predict(self, horizon: int) -> list[float]:
        _require_horizon(horizon)
        return [self._last + self._drift * step for step in range(1, horizon + 1)]


class LinearTrendForecaster:
    """Ordinary-least-squares fit of value against a time index."""

    name = "linear_trend"

    def __init__(self) -> None:
        self._intercept = 0.0
        self._slope = 0.0
        self._n = 0

    def fit(self, history: Sequence[float]) -> None:
        _require_history(history, 2)
        n = len(history)
        xs = range(n)
        mean_x = (n - 1) / 2.0
        mean_y = sum(history) / n
        var_x = sum((x - mean_x) ** 2 for x in xs)
        cov_xy = sum((x - mean_x) * (history[x] - mean_y) for x in xs)
        self._slope = cov_xy / var_x if var_x else 0.0
        self._intercept = mean_y - self._slope * mean_x
        self._n = n

    def predict(self, horizon: int) -> list[float]:
        _require_horizon(horizon)
        return [
            self._intercept + self._slope * (self._n - 1 + step)
            for step in range(1, horizon + 1)
        ]


class HoltLinearForecaster:
    """Holt's linear (double exponential) smoothing with level and trend."""

    name = "holt_linear"

    def __init__(self, *, alpha: float = 0.5, beta: float = 0.1) -> None:
        if not 0.0 < alpha <= 1.0 or not 0.0 <= beta <= 1.0:
            msg = "alpha must be in (0,1] and beta in [0,1]"
            raise ValueError(msg)
        self.alpha = alpha
        self.beta = beta
        self._level = 0.0
        self._trend = 0.0

    def fit(self, history: Sequence[float]) -> None:
        _require_history(history, 2)
        level = float(history[0])
        trend = float(history[1]) - float(history[0])
        for value in history[1:]:
            previous_level = level
            level = self.alpha * value + (1 - self.alpha) * (level + trend)
            trend = self.beta * (level - previous_level) + (1 - self.beta) * trend
        self._level = level
        self._trend = trend

    def predict(self, horizon: int) -> list[float]:
        _require_horizon(horizon)
        return [self._level + self._trend * step for step in range(1, horizon + 1)]


class ARForecaster:
    """Autoregressive model of order ``p`` fit by ordinary least squares."""

    def __init__(self, order: int = 3) -> None:
        if order < 1:
            msg = "order must be at least 1"
            raise ValueError(msg)
        self.order = order
        self.name = f"ar{order}"
        self._coefficients: list[float] = []
        self._history: list[float] = []

    def fit(self, history: Sequence[float]) -> None:
        _require_history(history, self.order + 1)
        rows: list[list[float]] = []
        targets: list[float] = []
        for index in range(self.order, len(history)):
            lags = [1.0] + [float(history[index - lag]) for lag in range(1, self.order + 1)]
            rows.append(lags)
            targets.append(float(history[index]))
        self._coefficients = _ols_solve(rows, targets)
        self._history = [float(value) for value in history]

    def predict(self, horizon: int) -> list[float]:
        _require_horizon(horizon)
        if not self._coefficients:
            msg = "model must be fit before predict"
            raise RuntimeError(msg)
        window = list(self._history)
        forecasts: list[float] = []
        for _ in range(horizon):
            features = [1.0] + [window[-lag] for lag in range(1, self.order + 1)]
            prediction = sum(c * x for c, x in zip(self._coefficients, features, strict=True))
            forecasts.append(prediction)
            window.append(prediction)
        return forecasts


class ReturnsForecaster:
    """Forecast a non-stationary level series in log-return space.

    Wraps any base forecaster: it is fit on log returns ``ln(p_t / p_{t-1})``
    (which are roughly stationary for prices), then forecasts returns and
    reconstructs the price level. This lets trend and tree models, which cannot
    extrapolate a rising price level directly, model the stationary returns
    instead.
    """

    def __init__(self, base: Forecaster) -> None:
        self.base = base
        self.name = f"ret_{base.name}"
        self._last_level = 0.0

    def fit(self, history: Sequence[float]) -> None:
        _require_history(history, 2)
        if any(value <= 0 for value in history):
            msg = "ReturnsForecaster requires strictly positive values"
            raise ValueError(msg)
        returns = [
            math.log(float(history[i]) / float(history[i - 1]))
            for i in range(1, len(history))
        ]
        self._last_level = float(history[-1])
        self.base.fit(returns)

    def predict(self, horizon: int) -> list[float]:
        _require_horizon(horizon)
        predicted_returns = self.base.predict(horizon)
        levels: list[float] = []
        level = self._last_level
        for log_return in predicted_returns:
            level = level * math.exp(log_return)
            levels.append(level)
        return levels


def _ols_solve(rows: list[list[float]], targets: list[float]) -> list[float]:
    """Solve least squares via the normal equations using Gaussian elimination."""

    columns = len(rows[0])
    # Build X^T X (columns x columns) and X^T y (columns).
    ata = [[0.0] * columns for _ in range(columns)]
    aty = [0.0] * columns
    for row, target in zip(rows, targets, strict=True):
        for i in range(columns):
            aty[i] += row[i] * target
            for j in range(columns):
                ata[i][j] += row[i] * row[j]
    return _gaussian_solve(ata, aty)


def _gaussian_solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve ``matrix x = vector`` with partial pivoting (small systems)."""

    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for pivot in range(size):
        max_row = max(range(pivot, size), key=lambda r: abs(augmented[r][pivot]))
        if abs(augmented[max_row][pivot]) < 1e-12:
            augmented[pivot][pivot] += 1e-9  # Ridge nudge for singular systems.
            max_row = pivot
        augmented[pivot], augmented[max_row] = augmented[max_row], augmented[pivot]
        pivot_value = augmented[pivot][pivot]
        for row in range(size):
            if row == pivot:
                continue
            factor = augmented[row][pivot] / pivot_value
            for col in range(pivot, size + 1):
                augmented[row][col] -= factor * augmented[pivot][col]
    return [augmented[i][size] / augmented[i][i] for i in range(size)]


def _require_history(history: Sequence[float], minimum: int) -> None:
    if len(history) < minimum:
        msg = f"history needs at least {minimum} observations, got {len(history)}"
        raise ValueError(msg)


def _require_horizon(horizon: int) -> None:
    if horizon < 1:
        msg = "horizon must be at least 1"
        raise ValueError(msg)
