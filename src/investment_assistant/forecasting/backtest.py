"""Local backtesting helpers for Phase 5 forecasting workflows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from investment_assistant.forecasting.baseline import (
    moving_average_forecast,
    naive_forecast,
)
from investment_assistant.forecasting.metrics import (
    directional_accuracy,
    mean_absolute_error,
    mean_absolute_percentage_error,
    root_mean_squared_error,
)
from investment_assistant.forecasting.models import ForecastPoint

BACKTEST_DISCLAIMER = (
    "このバックテスト結果は、ユーザー提供データに基づく過去期間の検証です。"
    "投資助言、売買推奨、将来リターンの保証ではありません。"
    "最終的な投資判断はユーザー本人が行います。自動売買は行いません。"
)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Result of a local baseline backtest."""

    method: str
    train_rows: int
    test_rows: int
    actual: list[float]
    predicted: list[float]
    mae: float
    rmse: float
    mape: float
    directional_accuracy: float
    disclaimer: str = BACKTEST_DISCLAIMER


def split_train_test(
    points: Sequence[ForecastPoint],
    *,
    test_size: int,
) -> tuple[list[ForecastPoint], list[ForecastPoint]]:
    """Split points into chronological train and test sets."""

    if test_size <= 0:
        raise ValueError("test_size must be positive")
    if test_size >= len(points):
        raise ValueError(
            "test_size must be less than the number of points; "
            f"got test_size={test_size} and rows={len(points)}"
        )

    sorted_points = sorted(points, key=lambda point: point.date)
    split_index = len(sorted_points) - test_size
    return sorted_points[:split_index], sorted_points[split_index:]


def backtest_naive(
    points: Sequence[ForecastPoint],
    *,
    test_size: int,
) -> BacktestResult:
    """Backtest a naive forecast by repeating the last training value."""

    train_points, test_points = split_train_test(points, test_size=test_size)
    predicted = naive_forecast(train_points, horizon=len(test_points))
    return _build_result(
        method="naive",
        train_points=train_points,
        test_points=test_points,
        predicted=predicted,
    )


def backtest_moving_average(
    points: Sequence[ForecastPoint],
    *,
    test_size: int,
    window: int,
) -> BacktestResult:
    """Backtest a moving-average forecast using the training period."""

    train_points, test_points = split_train_test(points, test_size=test_size)
    if window > len(train_points):
        raise ValueError(
            "window must be less than or equal to the training rows; "
            f"got window={window} and train_rows={len(train_points)}"
        )
    predicted = moving_average_forecast(
        train_points,
        horizon=len(test_points),
        window=window,
    )
    return _build_result(
        method="moving-average",
        train_points=train_points,
        test_points=test_points,
        predicted=predicted,
    )


def _build_result(
    *,
    method: str,
    train_points: Sequence[ForecastPoint],
    test_points: Sequence[ForecastPoint],
    predicted: list[float],
) -> BacktestResult:
    actual = [point.value for point in test_points]
    return BacktestResult(
        method=method,
        train_rows=len(train_points),
        test_rows=len(test_points),
        actual=actual,
        predicted=predicted,
        mae=mean_absolute_error(actual, predicted),
        rmse=root_mean_squared_error(actual, predicted),
        mape=mean_absolute_percentage_error(actual, predicted),
        directional_accuracy=directional_accuracy(actual, predicted),
    )
