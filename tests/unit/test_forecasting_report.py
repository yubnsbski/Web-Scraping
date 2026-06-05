"""Tests for forecasting report builders."""

from __future__ import annotations

from investment_assistant.forecasting.backtest import BacktestResult
from investment_assistant.forecasting.report import build_backtest_report


def test_build_backtest_report_includes_metrics_safety_and_disclaimer():
    result = BacktestResult(
        method="naive",
        train_rows=3,
        test_rows=2,
        actual=[103.0, 105.0],
        predicted=[104.0, 104.0],
        mae=1.0,
        rmse=1.0,
        mape=0.01,
    )

    report = build_backtest_report(result)

    assert report["summary"] == {
        "method": "naive",
        "train_rows": 3,
        "test_rows": 2,
        "purpose": "local_backtest_reference",
    }
    assert report["metrics"] == {
        "mae": 1.0,
        "rmse": 1.0,
        "mape": 0.01,
    }
    assert report["series"] == {
        "actual": [103.0, 105.0],
        "predicted": [104.0, 104.0],
    }
    assert report["call_real_api"] is False
    assert report["auto_trading"] is False
    assert "投資助言" in str(report["disclaimer"])
    assert "自動売買" in str(report["disclaimer"])
    assert report["uncertainty_notes"]
    assert any("将来" in note for note in report["uncertainty_notes"])
