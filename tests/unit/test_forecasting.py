from __future__ import annotations

import math
from pathlib import Path

import pytest

from investment_assistant.forecasting import dataset, service
from investment_assistant.forecasting.backtest import evaluate_models, walk_forward
from investment_assistant.forecasting.ensemble import EnsembleForecaster
from investment_assistant.forecasting.metrics import (
    directional_accuracy,
    mae,
    rmse,
    skill_score,
)
from investment_assistant.forecasting.ml_models import sklearn_available
from investment_assistant.forecasting.models import (
    ARForecaster,
    DriftForecaster,
    LinearTrendForecaster,
    NaiveForecaster,
    ReturnsForecaster,
)
from investment_assistant.forecasting.timeseries import TimeSeries, load_timeseries_csv

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "examples" / "sp500_monthly_sample.csv"


# --- metrics ---------------------------------------------------------------


def test_basic_metrics() -> None:
    actuals = [1.0, 2.0, 3.0]
    forecasts = [1.0, 2.0, 4.0]
    assert mae(actuals, forecasts) == pytest.approx(1 / 3)
    assert rmse(actuals, forecasts) == pytest.approx(math.sqrt(1 / 3))
    assert skill_score(2.0, 4.0) == pytest.approx(0.5)


def test_directional_accuracy_counts_correct_directions() -> None:
    previous = [10.0, 10.0]
    actuals = [11.0, 9.0]
    forecasts = [12.0, 11.0]  # up (correct), up (wrong)
    assert directional_accuracy(previous, actuals, forecasts) == pytest.approx(0.5)


# --- base models -----------------------------------------------------------


def test_naive_repeats_last_value() -> None:
    model = NaiveForecaster()
    model.fit([3.0, 5.0, 9.0])
    assert model.predict(3) == [9.0, 9.0, 9.0]


def test_drift_extrapolates_average_change() -> None:
    model = DriftForecaster()
    model.fit([10.0, 12.0, 14.0])
    assert model.predict(2) == pytest.approx([16.0, 18.0])


def test_linear_trend_fits_a_line_exactly() -> None:
    model = LinearTrendForecaster()
    model.fit([2.0, 4.0, 6.0, 8.0])
    assert model.predict(2) == pytest.approx([10.0, 12.0])


def test_ar_recovers_simple_linear_recurrence() -> None:
    series = [float(value) for value in range(1, 21)]
    model = ARForecaster(order=2)
    model.fit(series)
    forecast = model.predict(1)[0]
    assert forecast == pytest.approx(21.0, abs=1e-6)


def test_returns_forecaster_tracks_geometric_growth() -> None:
    series = [100.0 * (1.05**step) for step in range(10)]
    model = ReturnsForecaster(DriftForecaster())
    model.fit(series)
    forecast = model.predict(1)[0]
    assert forecast == pytest.approx(series[-1] * 1.05, rel=1e-6)


def test_returns_forecaster_rejects_nonpositive() -> None:
    with pytest.raises(ValueError, match="positive"):
        ReturnsForecaster(NaiveForecaster()).fit([1.0, 0.0, 2.0])


# --- ensemble --------------------------------------------------------------


def test_ensemble_mean_and_median() -> None:
    history = [1.0, 2.0, 3.0, 4.0]
    mean_ensemble = EnsembleForecaster(
        [NaiveForecaster(), DriftForecaster()], method="mean"
    )
    mean_ensemble.fit(history)
    # naive -> 4.0, drift -> 5.0; mean -> 4.5
    assert mean_ensemble.predict(1)[0] == pytest.approx(4.5)


def test_weighted_ensemble_downweights_bad_member() -> None:
    # A trend series where the constant naive member is poor and drift is good.
    history = [float(value) for value in range(1, 41)]
    ensemble = EnsembleForecaster(
        [NaiveForecaster(), DriftForecaster()],
        method="weighted",
        validation_size=8,
    )
    ensemble.fit(history)
    naive_weight, drift_weight = ensemble.weights
    assert drift_weight > naive_weight
    assert sum(ensemble.weights) == pytest.approx(1.0)


# --- backtest --------------------------------------------------------------


def test_walk_forward_lengths_and_naive_zero_skill() -> None:
    values = [float(value) for value in range(1, 31)]
    run = walk_forward(values, NaiveForecaster, initial_train=10, horizon=1, step=1)
    assert len(run.actuals) == len(values) - 10
    assert len(run.forecasts) == len(run.actuals) == len(run.previous)

    evaluations = evaluate_models(
        TimeSeries(tuple(str(i) for i in range(30)), tuple(values)),
        {"naive": NaiveForecaster, "drift": DriftForecaster},
        initial_train=10,
    )
    names = {item.name for item in evaluations}
    assert names == {"naive", "drift"}
    naive_eval = next(item for item in evaluations if item.name == "naive")
    assert naive_eval.skill_vs_naive == pytest.approx(0.0)


# --- timeseries + service (classical, offline) -----------------------------


def test_load_sample_csv_drops_incomplete_rows() -> None:
    series = load_timeseries_csv(SAMPLE_CSV, value_column="SP500")
    assert len(series) >= 100
    assert all(value > 0 for value in series.values)
    train, test = series.split(len(series) - 5)
    assert len(test) == 5


def test_run_evaluation_classical_includes_ensemble_and_ranks() -> None:
    series = load_timeseries_csv(SAMPLE_CSV, value_column="SP500")
    report = service.run_evaluation(
        series, horizon=1, step=1, include_ml=False, ensemble_method="weighted"
    )
    model_names = {model["name"] for model in report["models"]}
    assert "naive" in model_names
    assert "ensemble_weighted" in model_names
    rmses = [model["metrics"]["rmse"] for model in report["models"]]
    assert rmses == sorted(rmses)  # ranked best (lowest RMSE) first
    assert "投資助言ではありません" in report["disclaimer"]


def test_run_forecast_returns_horizon_length() -> None:
    series = load_timeseries_csv(SAMPLE_CSV, value_column="SP500")
    result = service.run_forecast(series, horizon=3, include_ml=False)
    assert len(result["ensemble_forecast"]) == 3
    assert result["last_observed"] == series.values[-1]
    assert sum(result["ensemble_weights"].values()) == pytest.approx(1.0)


# --- dataset acquisition (offline via fake transport) ----------------------


def test_resolve_dataset_url_maps_known_name() -> None:
    url = dataset.resolve_dataset_url("sp500_shiller")
    assert url.startswith("https://raw.githubusercontent.com/")
    assert dataset.resolve_dataset_url("https://x/y.csv") == "https://x/y.csv"


def test_download_dataset_writes_file(tmp_path, monkeypatch) -> None:
    from investment_assistant.ingestion.transport import HttpResponse

    monkeypatch.setattr(dataset, "validate_public_http_url", lambda url: None)

    class _FakeTransport:
        def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
            body = b"Date,SP500\n2020-01-01,3000\n"
            return HttpResponse(url=url, status_code=200, headers={}, body=body)

    dest = tmp_path / "data.csv"
    summary = dataset.download_dataset("sp500_shiller", dest=dest, transport=_FakeTransport())
    assert dest.exists()
    assert summary["approx_rows"] == 1


def test_download_dataset_rejects_untrusted_host(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dataset, "validate_public_http_url", lambda url: None)
    with pytest.raises(ValueError, match="untrusted host"):
        dataset.download_dataset("https://evil.example.com/x.csv", dest=tmp_path / "x.csv")


# --- optional ML members ---------------------------------------------------


@pytest.mark.skipif(not sklearn_available(), reason="scikit-learn not installed")
def test_random_forest_member_fits_and_predicts() -> None:
    from investment_assistant.forecasting.ml_models import RandomForestForecaster

    series = [float(value) for value in range(1, 41)]
    model = RandomForestForecaster(lags=4, n_estimators=20)
    model.fit(series)
    forecast = model.predict(2)
    assert len(forecast) == 2
    assert all(math.isfinite(value) for value in forecast)
