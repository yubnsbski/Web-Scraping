from investment_assistant.forecasting.diagnostics import forecast_input_warnings


def test_forecast_input_warnings_returns_empty_list_for_sufficient_single_symbol_input():
    warnings = forecast_input_warnings(rows=5, symbols=["SAMPLE"])

    assert warnings == []


def test_forecast_input_warnings_warns_for_short_csv():
    warnings = forecast_input_warnings(rows=2, symbols=["SAMPLE"])

    assert warnings == [
        "forecasting CSV has fewer than 5 rows; baseline forecasts and backtests may be unstable"
    ]


def test_forecast_input_warnings_warns_for_multiple_symbols():
    warnings = forecast_input_warnings(rows=5, symbols=["AAA", "BBB"])

    assert warnings == [
        "forecasting CSV contains multiple symbols; "
        "initial forecasting workflows assume a single time series"
    ]
