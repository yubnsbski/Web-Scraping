"""Tests for local forecasting backtests."""

from __future__ import annotations

import math
from datetime import date

import pytest

from investment_assistant.forecasting.backtest import (
    BacktestResult,
    backtest_moving_average,
    backtest_naive,
    split_train_test,
)
from investment_assistant.forecasting.models import ForecastPoint


def _points() -> list[ForecastPoint]:
    return [
        ForecastPoint(date=date(2026, 1, 1), value=100.0, symbol="SAMPLE"),
        ForecastPoint(date=date(2026, 1, 2), value=102.0, symbol="SAMPLE"),
        ForecastPoint(date=date(2026, 1, 3), value=104.0, symbol="SAMPLE"),
        ForecastPoint(date=date(2026, 1, 4), value=103.0, symbol="SAMPLE"),
        ForecastPoint(date=date(2026, 1, 5), value=105.0, symbol="SAMPLE"),
    ]


def test_split_train_test_splits_points_chronologically():
    unsorted_points = [
        _points()[2],
        _points()[0],
        _points()[4],
        _points()[1],
        _points()[3],
    ]

    train, test = split_train_test(unsorted_points, test_size=2)

    assert [point.date for point in train] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert [point.date for point in test] == [
        date(2026, 1, 4),
        date(2026, 1, 5),
    ]


def test_split_train_test_rejects_non_positive_test_size():
    with pytest.raises(ValueError, match="test_size must be positive"):
        split_train_test(_points(), test_size=0)


def test_split_train_test_rejects_test_size_too_large():
    with pytest.raises(ValueError, match="test_size must be less than"):
        split_train_test(_points(), test_size=5)


def test_backtest_naive_calculates_metrics():
    result = backtest_naive(_points(), test_size=2)

    assert isinstance(result, BacktestResult)
    assert result.method == "naive"
    assert result.train_rows == 3
    assert result.test_rows == 2
    assert result.actual == [103.0, 105.0]
    assert result.predicted == [104.0, 104.0]
    assert result.mae == pytest.approx(1.0)
    assert result.rmse == pytest.approx(1.0)
    assert result.mape == pytest.approx(((1 / 103) + (1 / 105)) / 2)
    assert "投資助言" in result.disclaimer
    assert "自動売買" in result.disclaimer


def test_backtest_moving_average_calculates_metrics():
    result = backtest_moving_average(_points(), test_size=2, window=2)

    assert result.method == "moving-average"
    assert result.train_rows == 3
    assert result.test_rows == 2
    assert result.actual == [103.0, 105.0]
    assert result.predicted == [103.0, 103.0]
    assert result.mae == pytest.approx(1.0)
    assert result.rmse == pytest.approx(math.sqrt(2.0))
    assert result.mape == pytest.approx(1 / 105)


def test_backtest_moving_average_rejects_window_larger_than_train():
    with pytest.raises(ValueError, match="window must be less than or equal"):
        backtest_moving_average(_points(), test_size=3, window=3)
