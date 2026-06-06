"""Optional ML ensemble forecasters (scikit-learn).

These are the canonical *ensemble learning* members: a random forest (bagging)
and gradient boosting (boosting). They are kept behind a lazy import so the core
package and its tests run without the optional ``[forecast]`` extra installed.

Install with::

    pip install -e '.[forecast]'
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Sequence
from typing import Any


def sklearn_available() -> bool:
    """Return whether scikit-learn can be imported."""

    return importlib.util.find_spec("sklearn") is not None


class _LagFeatureForecaster:
    """Shared lag-feature regression scaffold for tree ensembles."""

    name = "ml_base"

    def __init__(self, *, lags: int = 6) -> None:
        if lags < 1:
            msg = "lags must be at least 1"
            raise ValueError(msg)
        self.lags = lags
        self._model: Any | None = None
        self._history: list[float] = []

    def _build_estimator(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def fit(self, history: Sequence[float]) -> None:
        if len(history) < self.lags + 1:
            msg = f"history needs at least {self.lags + 1} observations"
            raise ValueError(msg)
        features: list[list[float]] = []
        targets: list[float] = []
        for index in range(self.lags, len(history)):
            features.append([float(history[index - lag]) for lag in range(1, self.lags + 1)])
            targets.append(float(history[index]))
        model = self._build_estimator()
        model.fit(features, targets)
        self._model = model
        self._history = [float(value) for value in history]

    def predict(self, horizon: int) -> list[float]:
        if horizon < 1:
            msg = "horizon must be at least 1"
            raise ValueError(msg)
        if self._model is None:
            msg = "model must be fit before predict"
            raise RuntimeError(msg)
        window = list(self._history)
        forecasts: list[float] = []
        for _ in range(horizon):
            features = [[window[-lag] for lag in range(1, self.lags + 1)]]
            prediction = float(self._model.predict(features)[0])
            forecasts.append(prediction)
            window.append(prediction)
        return forecasts


class RandomForestForecaster(_LagFeatureForecaster):
    """Random forest (bagging ensemble) over lag features."""

    def __init__(self, *, lags: int = 6, n_estimators: int = 200, random_state: int = 0) -> None:
        super().__init__(lags=lags)
        self.name = "random_forest"
        self.n_estimators = n_estimators
        self.random_state = random_state

    def _build_estimator(self) -> Any:
        ensemble = importlib.import_module("sklearn.ensemble")
        return ensemble.RandomForestRegressor(
            n_estimators=self.n_estimators,
            random_state=self.random_state,
            n_jobs=1,
        )


class GradientBoostingForecaster(_LagFeatureForecaster):
    """Gradient boosting (boosting ensemble) over lag features."""

    def __init__(self, *, lags: int = 6, n_estimators: int = 200, random_state: int = 0) -> None:
        super().__init__(lags=lags)
        self.name = "gradient_boosting"
        self.n_estimators = n_estimators
        self.random_state = random_state

    def _build_estimator(self) -> Any:
        ensemble = importlib.import_module("sklearn.ensemble")
        return ensemble.GradientBoostingRegressor(
            n_estimators=self.n_estimators,
            random_state=self.random_state,
        )
