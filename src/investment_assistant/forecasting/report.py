"""Report builders for local forecasting workflows."""

from __future__ import annotations

from investment_assistant.forecasting.backtest import BacktestResult

DEFAULT_UNCERTAINTY_NOTES = [
    "バックテストは過去データに基づく検証であり、将来の市場環境を保証しません。",
    "評価期間が短い場合、指標の信頼性は低くなる可能性があります。",
    "入力CSVの欠損、外れ値、制度変更、市場環境の変化によって結果は変わります。",
]


def build_backtest_report(result: BacktestResult) -> dict[str, object]:
    """Build a JSON-ready, non-advisory backtest report."""

    return {
        "summary": {
            "method": result.method,
            "train_rows": result.train_rows,
            "test_rows": result.test_rows,
            "purpose": "local_backtest_reference",
        },
        "metrics": {
            "mae": result.mae,
            "rmse": result.rmse,
            "mape": result.mape,
        },
        "series": {
            "actual": result.actual,
            "predicted": result.predicted,
        },
        "raw_result": {
            "method": result.method,
            "train_rows": result.train_rows,
            "test_rows": result.test_rows,
            "actual": result.actual,
            "predicted": result.predicted,
            "mae": result.mae,
            "rmse": result.rmse,
            "mape": result.mape,
            "disclaimer": result.disclaimer,
        },
        "uncertainty_notes": list(DEFAULT_UNCERTAINTY_NOTES),
        "call_real_api": False,
        "auto_trading": False,
        "disclaimer": result.disclaimer,
    }
