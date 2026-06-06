"""Walk-forward backtesting and model comparison for forecasters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from investment_assistant.forecasting.metrics import (
    ForecastMetrics,
    directional_accuracy,
    mae,
    mape,
    rmse,
    skill_score,
)
from investment_assistant.forecasting.models import Forecaster
from investment_assistant.forecasting.timeseries import TimeSeries

ModelBuilder = Callable[[], Forecaster]


@dataclass(frozen=True)
class BacktestForecasts:
    """Aligned arrays produced by a walk-forward run."""

    previous: list[float]
    actuals: list[float]
    forecasts: list[float]


@dataclass(frozen=True)
class ModelEvaluation:
    """Backtest result for a single model."""

    name: str
    metrics: ForecastMetrics
    skill_vs_naive: float

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""

        return {
            "name": self.name,
            "metrics": self.metrics.to_dict(),
            "skill_vs_naive": self.skill_vs_naive,
        }


def walk_forward(
    values: Sequence[float],
    build_model: ModelBuilder,
    *,
    initial_train: int,
    horizon: int = 1,
    step: int = 1,
) -> BacktestForecasts:
    """Run an expanding-window walk-forward backtest for one model.

    At each origin the model is refit on all data seen so far and asked for an
    ``horizon``-step forecast; the final forecast point is compared with the
    matching actual. This mirrors honest out-of-sample use: no future data ever
    leaks into a fit.
    """

    if initial_train < 2:
        msg = "initial_train must be at least 2"
        raise ValueError(msg)
    if horizon < 1 or step < 1:
        msg = "horizon and step must be at least 1"
        raise ValueError(msg)
    if initial_train + horizon - 1 >= len(values):
        msg = "series is too short for the requested initial_train and horizon"
        raise ValueError(msg)

    previous: list[float] = []
    actuals: list[float] = []
    forecasts: list[float] = []
    origin = initial_train
    while origin + horizon - 1 < len(values):
        model = build_model()
        model.fit(values[:origin])
        prediction = model.predict(horizon)[horizon - 1]
        forecasts.append(prediction)
        actuals.append(float(values[origin + horizon - 1]))
        previous.append(float(values[origin - 1]))
        origin += step
    return BacktestForecasts(previous=previous, actuals=actuals, forecasts=forecasts)


def evaluate_models(
    series: TimeSeries,
    builders: dict[str, ModelBuilder],
    *,
    initial_train: int | None = None,
    horizon: int = 1,
    step: int = 1,
    baseline: str = "naive",
) -> list[ModelEvaluation]:
    """Backtest every builder and rank them by RMSE (best first).

    Skill scores are computed against ``baseline`` (the naive persistence model
    by default), so a positive skill means the model beats simply repeating the
    last observed value.
    """

    if baseline not in builders:
        msg = f"baseline {baseline!r} must be one of the provided builders"
        raise ValueError(msg)
    values = series.values
    train_size = initial_train if initial_train is not None else _default_initial_train(len(values))

    runs: dict[str, BacktestForecasts] = {
        name: walk_forward(
            values, builder, initial_train=train_size, horizon=horizon, step=step
        )
        for name, builder in builders.items()
    }
    baseline_rmse = rmse(runs[baseline].actuals, runs[baseline].forecasts)

    evaluations = [
        ModelEvaluation(
            name=name,
            metrics=_metrics_from_run(run),
            skill_vs_naive=skill_score(rmse(run.actuals, run.forecasts), baseline_rmse),
        )
        for name, run in runs.items()
    ]
    return sorted(evaluations, key=lambda evaluation: evaluation.metrics.rmse)


def _metrics_from_run(run: BacktestForecasts) -> ForecastMetrics:
    return ForecastMetrics(
        count=len(run.actuals),
        mae=mae(run.actuals, run.forecasts),
        rmse=rmse(run.actuals, run.forecasts),
        mape=mape(run.actuals, run.forecasts),
        directional_accuracy=directional_accuracy(run.previous, run.actuals, run.forecasts),
    )


def _default_initial_train(length: int) -> int:
    """Use the first ~70% (or at least 24 points) as the initial training span."""

    return max(24, int(length * 0.7))
