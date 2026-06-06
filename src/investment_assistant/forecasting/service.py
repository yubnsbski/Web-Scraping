"""High-level forecasting service: model registry, evaluation, and prediction."""

from __future__ import annotations

from collections.abc import Sequence

from investment_assistant.forecasting.backtest import ModelBuilder, evaluate_models
from investment_assistant.forecasting.ensemble import EnsembleForecaster
from investment_assistant.forecasting.ml_models import (
    GradientBoostingForecaster,
    RandomForestForecaster,
    sklearn_available,
)
from investment_assistant.forecasting.models import (
    ARForecaster,
    DriftForecaster,
    Forecaster,
    HoltLinearForecaster,
    LinearTrendForecaster,
    MovingAverageForecaster,
    NaiveForecaster,
    ReturnsForecaster,
)
from investment_assistant.forecasting.timeseries import TimeSeries

DISCLAIMER = (
    "本予測は教育・調査目的の統計的推定であり、投資助言ではありません。"
    "自動売買は行わず、最終的な投資判断はユーザー本人が行ってください。"
)


def classical_builders(*, ar_order: int = 3) -> dict[str, ModelBuilder]:
    """Return the dependency-free base forecasters."""

    return {
        "naive": NaiveForecaster,
        "drift": DriftForecaster,
        "linear_trend": LinearTrendForecaster,
        "holt_linear": HoltLinearForecaster,
        f"ar{ar_order}": lambda: ARForecaster(ar_order),
    }


def ml_builders(*, n_estimators: int = 200) -> dict[str, ModelBuilder]:
    """Return optional scikit-learn ensemble forecasters, or empty if unavailable."""

    if not sklearn_available():
        return {}
    return {
        "random_forest": lambda: RandomForestForecaster(n_estimators=n_estimators),
        "gradient_boosting": lambda: GradientBoostingForecaster(n_estimators=n_estimators),
    }


def moving_average_builders(windows: Sequence[int]) -> dict[str, ModelBuilder]:
    """Build moving-average forecasters for each requested window."""

    builders: dict[str, ModelBuilder] = {}
    for window in windows:
        builders[f"ma{window}"] = (lambda w=window: MovingAverageForecaster(window=w))  # type: ignore[misc]
    return builders


def member_builders(
    *,
    ar_order: int = 3,
    include_ml: bool = True,
    space: str = "level",
    ma_windows: Sequence[int] = (),
) -> dict[str, ModelBuilder]:
    """Return the member forecasters that make up the ensemble.

    When ``space == "returns"`` every member except the naive random-walk
    baseline is wrapped to model log returns and reconstruct the price level.
    """

    if space not in ("level", "returns"):
        msg = f"space must be 'level' or 'returns', got {space!r}"
        raise ValueError(msg)
    builders = classical_builders(ar_order=ar_order)
    builders.update(moving_average_builders(ma_windows))
    if include_ml:
        builders.update(ml_builders())
    if space == "level":
        return builders
    wrapped: dict[str, ModelBuilder] = {}
    for name, builder in builders.items():
        if name == "naive":
            wrapped[name] = builder  # Keep the level random-walk baseline.
        else:
            wrapped[name] = _wrap_returns(builder)
    return wrapped


def _wrap_returns(builder: ModelBuilder) -> ModelBuilder:
    def build() -> Forecaster:
        return ReturnsForecaster(builder())

    return build


def ensemble_builder(
    *,
    method: str = "weighted",
    ar_order: int = 3,
    include_ml: bool = True,
    space: str = "level",
    ma_windows: Sequence[int] = (),
) -> ModelBuilder:
    """Return a builder that constructs a fresh ensemble each call."""

    members = member_builders(
        ar_order=ar_order, include_ml=include_ml, space=space, ma_windows=ma_windows
    )

    def build() -> EnsembleForecaster:
        return EnsembleForecaster([builder() for builder in members.values()], method=method)

    return build


def run_evaluation(
    series: TimeSeries,
    *,
    horizon: int = 1,
    step: int = 1,
    initial_train: int | None = None,
    ar_order: int = 3,
    include_ml: bool = True,
    ensemble_method: str = "weighted",
    space: str = "returns",
    ma_windows: Sequence[int] = (),
) -> dict[str, object]:
    """Backtest base models and the ensemble, ranked by RMSE (best first)."""

    builders = member_builders(
        ar_order=ar_order, include_ml=include_ml, space=space, ma_windows=ma_windows
    )
    ensemble_name = f"ensemble_{ensemble_method}"
    builders[ensemble_name] = ensemble_builder(
        method=ensemble_method,
        ar_order=ar_order,
        include_ml=include_ml,
        space=space,
        ma_windows=ma_windows,
    )

    evaluations = evaluate_models(
        series,
        builders,
        initial_train=initial_train,
        horizon=horizon,
        step=step,
    )
    best = evaluations[0]
    return {
        "series": series.name,
        "observations": len(series),
        "horizon": horizon,
        "step": step,
        "space": space,
        "ma_windows": list(ma_windows),
        "ml_enabled": include_ml and sklearn_available(),
        "ensemble_method": ensemble_method,
        "best_model": best.name,
        "models": [evaluation.to_dict() for evaluation in evaluations],
        "disclaimer": DISCLAIMER,
    }


def run_forecast(
    series: TimeSeries,
    *,
    horizon: int = 1,
    ar_order: int = 3,
    include_ml: bool = True,
    ensemble_method: str = "weighted",
    space: str = "returns",
    ma_windows: Sequence[int] = (),
) -> dict[str, object]:
    """Fit the ensemble on the full series and forecast the next ``horizon`` steps."""

    members = member_builders(
        ar_order=ar_order, include_ml=include_ml, space=space, ma_windows=ma_windows
    )
    member_instances = {name: builder() for name, builder in members.items()}
    member_forecasts: dict[str, list[float]] = {}
    for name, model in member_instances.items():
        model.fit(series.values)
        member_forecasts[name] = model.predict(horizon)

    ensemble = EnsembleForecaster(
        [builder() for builder in members.values()], method=ensemble_method
    )
    ensemble.fit(series.values)
    ensemble_forecast = ensemble.predict(horizon)

    return {
        "series": series.name,
        "observations": len(series),
        "last_observed": series.values[-1],
        "last_date": series.dates[-1],
        "horizon": horizon,
        "ensemble_method": ensemble_method,
        "space": space,
        "ml_enabled": include_ml and sklearn_available(),
        "ensemble_forecast": ensemble_forecast,
        "member_forecasts": member_forecasts,
        "ensemble_weights": dict(zip(members.keys(), ensemble.weights, strict=True)),
        "disclaimer": DISCLAIMER,
    }
