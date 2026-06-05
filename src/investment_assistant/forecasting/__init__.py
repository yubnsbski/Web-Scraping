"""Local forecasting foundations for Phase 5.

This package intentionally avoids Gemini API calls, external market data fetching,
investment advice, trading recommendations, and auto-trading.
"""

from investment_assistant.forecasting.backtest import (
    BacktestResult,
    backtest_moving_average,
    backtest_naive,
    split_train_test,
)
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

__all__ = [
    "BacktestResult",
    "ForecastPoint",
    "ForecastValidationError",
    "backtest_moving_average",
    "backtest_naive",
    "load_forecast_csv",
    "mean_absolute_error",
    "mean_absolute_percentage_error",
    "moving_average_forecast",
    "naive_forecast",
    "root_mean_squared_error",
    "split_train_test",
]
