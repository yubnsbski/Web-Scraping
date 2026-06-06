"""Non-blocking diagnostics for local forecasting inputs."""

SHORT_FORECAST_CSV_WARNING = (
    "forecasting CSV has fewer than 5 rows; baseline forecasts and backtests may be unstable"
)
MULTI_SYMBOL_FORECAST_CSV_WARNING = (
    "forecasting CSV contains multiple symbols; "
    "initial forecasting workflows assume a single time series"
)


def forecast_input_warnings(*, rows: int, symbols: list[str]) -> list[str]:
    """Return non-blocking warnings for local forecasting CSV inputs."""

    warnings: list[str] = []
    if rows < 5:
        warnings.append(SHORT_FORECAST_CSV_WARNING)
    if len(symbols) > 1:
        warnings.append(MULTI_SYMBOL_FORECAST_CSV_WARNING)
    return warnings
