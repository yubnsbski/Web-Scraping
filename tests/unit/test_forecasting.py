"""Tests for local forecasting foundations."""

from __future__ import annotations

import math
from datetime import date

import pytest

from investment_assistant.forecasting.baseline import (
    moving_average_forecast,
    naive_forecast,
)
from investment_assistant.forecasting.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    root_mean_squared_error,
)
from investment_assistant.forecasting.models import ForecastPoint
from investment_assistant.forecasting.validation import (
    ForecastValidationError,
    load_forecast_csv,
)


def test_load_forecast_csv_accepts_valid_csv(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "date,value,symbol\n"
        "2026-01-03,100.8,SAMPLE\n"
        "2026-01-01,100.0,SAMPLE\n"
        "2026-01-02,101.5,SAMPLE\n",
        encoding="utf-8",
    )

    points = load_forecast_csv(csv_path)

    assert [point.date for point in points] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert [point.value for point in points] == [100.0, 101.5, 100.8]
    assert points[0].symbol == "SAMPLE"


def test_load_forecast_csv_accepts_missing_optional_symbol(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "date,value\n"
        "2026-01-01,100.0\n",
        encoding="utf-8",
    )

    points = load_forecast_csv(csv_path)

    assert len(points) == 1
    assert points[0].symbol is None


def test_load_forecast_csv_rejects_missing_date_column(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "value,symbol\n"
        "100.0,SAMPLE\n",
        encoding="utf-8",
    )

    with pytest.raises(ForecastValidationError, match="missing required columns: date"):
        load_forecast_csv(csv_path)


def test_load_forecast_csv_rejects_missing_value_column(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "date,symbol\n"
        "2026-01-01,SAMPLE\n",
        encoding="utf-8",
    )

    with pytest.raises(ForecastValidationError, match="missing required columns: value"):
        load_forecast_csv(csv_path)


def test_load_forecast_csv_rejects_invalid_value(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "date,value,symbol\n"
        "2026-01-01,not-a-number,SAMPLE\n",
        encoding="utf-8",
    )

    with pytest.raises(ForecastValidationError, match="row 2: value must be numeric"):
        load_forecast_csv(csv_path)


def test_load_forecast_csv_rejects_non_positive_value(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "date,value,symbol\n"
        "2026-01-01,0,SAMPLE\n",
        encoding="utf-8",
    )

    with pytest.raises(ForecastValidationError, match="row 2: value must be positive"):
        load_forecast_csv(csv_path)


def test_load_forecast_csv_rejects_duplicate_date(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "date,value,symbol\n"
        "2026-01-01,100.0,SAMPLE\n"
        "2026-01-01,101.0,SAMPLE\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ForecastValidationError,
        match="row 3: duplicate date 2026-01-01",
    ):
        load_forecast_csv(csv_path)


def test_metrics_calculate_expected_values():
    actual = [100.0, 110.0, 90.0]
    predicted = [98.0, 112.0, 87.0]

    assert mean_absolute_error(actual, predicted) == pytest.approx(7 / 3)
    assert root_mean_squared_error(actual, predicted) == pytest.approx(math.sqrt(17 / 3))
    assert mean_absolute_percentage_error(actual, predicted) == pytest.approx(
        (0.02 + (2 / 110) + (3 / 90)) / 3
    )


def test_metrics_reject_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        mean_absolute_error([1.0], [1.0, 2.0])


def test_metrics_reject_empty_inputs():
    with pytest.raises(ValueError, match="must not be empty"):
        root_mean_squared_error([], [])


def test_mape_rejects_zero_actual():
    with pytest.raises(ValueError, match="must not contain zero"):
        mean_absolute_percentage_error([0.0, 1.0], [0.0, 1.0])


def test_naive_forecast_repeats_latest_value():
    points = [
        ForecastPoint(date=date(2026, 1, 1), value=100.0),
        ForecastPoint(date=date(2026, 1, 2), value=101.5),
        ForecastPoint(date=date(2026, 1, 3), value=100.8),
    ]

    assert naive_forecast(points, horizon=3) == [100.8, 100.8, 100.8]


def test_naive_forecast_rejects_empty_points():
    with pytest.raises(ValueError, match="points must not be empty"):
        naive_forecast([], horizon=1)


def test_naive_forecast_rejects_non_positive_horizon():
    points = [ForecastPoint(date=date(2026, 1, 1), value=100.0)]

    with pytest.raises(ValueError, match="horizon must be positive"):
        naive_forecast(points, horizon=0)


def test_moving_average_forecast_repeats_trailing_average():
    points = [
        ForecastPoint(date=date(2026, 1, 1), value=100.0),
        ForecastPoint(date=date(2026, 1, 2), value=102.0),
        ForecastPoint(date=date(2026, 1, 3), value=104.0),
    ]

    assert moving_average_forecast(points, horizon=3, window=2) == [
        103.0,
        103.0,
        103.0,
    ]


def test_moving_average_forecast_rejects_non_positive_window():
    points = [ForecastPoint(date=date(2026, 1, 1), value=100.0)]

    with pytest.raises(ValueError, match="window must be positive"):
        moving_average_forecast(points, horizon=1, window=0)


def test_moving_average_forecast_rejects_window_larger_than_points():
    points = [ForecastPoint(date=date(2026, 1, 1), value=100.0)]

    with pytest.raises(ValueError, match="window must be less than or equal"):
        moving_average_forecast(points, horizon=1, window=2)
