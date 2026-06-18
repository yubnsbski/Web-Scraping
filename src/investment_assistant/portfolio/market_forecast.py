"""Per-ticker price forecasting from the scraped daily-bars CSV.

Bridges the collected OHLCV data to the dependency-light forecasting ensemble:
build a close-price series for one ticker from ``daily_bars.csv`` and produce a
next-horizon forecast (optionally with a walk-forward RMSE backtest). This is a
statistical estimate for research, not investment advice.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from investment_assistant.forecasting.service import run_evaluation, run_forecast
from investment_assistant.forecasting.timeseries import TimeSeries

JsonDict = dict[str, Any]

_TICKER_KEYS = ("ticker", "code")
# Returns-space models need a handful of points; below this a forecast is noise.
_MIN_OBSERVATIONS = 8
# Walk-forward backtesting needs enough history to hold out folds.
_MIN_EVAL_OBSERVATIONS = 14


def _read_rows(path: str | Path) -> list[dict[str, str]]:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿"), newline=""))
    return [dict(row) for row in reader]


def _normalize_ticker(value: str) -> str:
    """Bare Tokyo code in upper case, tolerating a stray ``.T`` suffix."""

    text = value.strip().upper()
    return text[:-2] if text.endswith(".T") else text


def _ticker_of(row: dict[str, str]) -> str:
    for key in _TICKER_KEYS:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def timeseries_from_daily_bars(daily_bars_csv: str | Path, ticker: str) -> TimeSeries:
    """Build a chronological close-price series for one ticker from daily bars."""

    wanted = _normalize_ticker(ticker)
    points: list[tuple[str, float]] = []
    for row in _read_rows(daily_bars_csv):
        if _normalize_ticker(_ticker_of(row)) != wanted:
            continue
        date = str(row.get("date") or "").strip()
        close_text = str(row.get("close") or "").strip()
        if not date or not close_text:
            continue
        try:
            close = float(close_text.replace(",", ""))
        except ValueError:
            continue
        if close > 0:
            points.append((date, close))
    points.sort(key=lambda item: item[0])
    dates = tuple(date for date, _ in points)
    values = tuple(close for _, close in points)
    return TimeSeries(dates=dates, values=values, name=wanted)


def forecast_ticker(
    *,
    daily_bars_csv: str | Path,
    ticker: str,
    horizon: int = 5,
    include_ml: bool = True,
    evaluate: bool = True,
) -> JsonDict:
    """Forecast the next ``horizon`` closes for ``ticker`` from the daily-bars CSV.

    Raises ``ValueError`` if the ticker has too few usable observations.
    """

    series = timeseries_from_daily_bars(daily_bars_csv, ticker)
    if len(series) < _MIN_OBSERVATIONS:
        msg = (
            f"not enough observations for {ticker}: {len(series)} "
            f"(need >= {_MIN_OBSERVATIONS}); fetch a longer OHLCV range"
        )
        raise ValueError(msg)

    forecast = run_forecast(series, horizon=max(int(horizon), 1), include_ml=include_ml)
    result: JsonDict = {
        "ticker": series.name,
        "observations": len(series),
        "last_date": series.dates[-1],
        "last_close": series.values[-1],
        "horizon": forecast["horizon"],
        "forecast": forecast["ensemble_forecast"],
        "ensemble_method": forecast["ensemble_method"],
        "ml_enabled": forecast["ml_enabled"],
        "disclaimer": forecast["disclaimer"],
        "auto_trading": False,
        "call_real_api": False,
    }
    if evaluate and len(series) >= _MIN_EVAL_OBSERVATIONS:
        # The default initial-train span (>=24) is too large for ~1mo of bars, so
        # hold out roughly the last 40% of the series instead.
        initial_train = max(int(len(series) * 0.6), 8)
        try:
            evaluation = run_evaluation(
                series, horizon=1, include_ml=include_ml, initial_train=initial_train
            )
            models = evaluation.get("models")
            if isinstance(models, list) and models:
                best = models[0]
                result["backtest_best_model"] = best.get("name")
                metrics = best.get("metrics")
                if isinstance(metrics, dict):
                    result["backtest_rmse"] = metrics.get("rmse")
        except (ValueError, ZeroDivisionError):
            result["backtest_rmse"] = None
    return result
