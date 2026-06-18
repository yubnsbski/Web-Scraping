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
    return _forecast_from_series(
        series, horizon=horizon, include_ml=include_ml, evaluate=evaluate
    )


def _forecast_from_series(
    series: TimeSeries, *, horizon: int, include_ml: bool, evaluate: bool
) -> JsonDict:
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


def _series_map_from_daily_bars(daily_bars_csv: str | Path) -> dict[str, TimeSeries]:
    """Read the daily-bars CSV once and return a close-price series per ticker."""

    groups: dict[str, list[tuple[str, float]]] = {}
    for row in _read_rows(daily_bars_csv):
        ticker = _normalize_ticker(_ticker_of(row))
        date = str(row.get("date") or "").strip()
        close_text = str(row.get("close") or "").strip()
        if not ticker or not date or not close_text:
            continue
        try:
            close = float(close_text.replace(",", ""))
        except ValueError:
            continue
        if close > 0:
            groups.setdefault(ticker, []).append((date, close))
    out: dict[str, TimeSeries] = {}
    for ticker, points in groups.items():
        points.sort(key=lambda item: item[0])
        out[ticker] = TimeSeries(
            dates=tuple(d for d, _ in points),
            values=tuple(c for _, c in points),
            name=ticker,
        )
    return out


def forecast_all_tickers(
    daily_bars_csv: str | Path,
    *,
    horizon: int = 5,
    include_ml: bool = True,
    evaluate: bool = False,
) -> dict[str, JsonDict]:
    """Forecast every ticker in the daily-bars CSV that has enough history.

    Reads the CSV once. Tickers with too few observations (or that raise during
    fitting) are skipped rather than aborting the batch.
    """

    out: dict[str, JsonDict] = {}
    for ticker, series in _series_map_from_daily_bars(daily_bars_csv).items():
        if len(series) < _MIN_OBSERVATIONS:
            continue
        try:
            out[ticker] = _forecast_from_series(
                series, horizon=horizon, include_ml=include_ml, evaluate=evaluate
            )
        except (ValueError, ZeroDivisionError):
            continue
    return out


def screen_by_forecast(
    daily_bars_csv: str | Path,
    *,
    horizon: int = 5,
    include_ml: bool = False,
    top: int = 0,
    max_abs_return_pct: float = 30.0,
) -> list[JsonDict]:
    """Rank tickers by forecast expected return over ``horizon`` (descending).

    ``expected_return_pct`` is ``(forecast_close / last_close - 1) * 100`` using
    the final forecast step. Forecasts whose magnitude exceeds
    ``max_abs_return_pct`` are dropped as implausible extrapolation artifacts (a
    short, volatile series can make a linear/drift model explode over several
    steps); pass ``0`` to disable the guard. ``rmse_pct`` (backtest RMSE as a
    share of last close) is added as a reliability hint. Ties break by ticker.
    ``top`` caps the list (``0`` = all). Non-advisory statistical screen.
    """

    forecasts = forecast_all_tickers(
        daily_bars_csv, horizon=horizon, include_ml=include_ml, evaluate=True
    )
    rows: list[JsonDict] = []
    for ticker, forecast in forecasts.items():
        values = forecast.get("forecast")
        last_close = forecast.get("last_close")
        if not isinstance(values, list) or not values:
            continue
        if not isinstance(last_close, int | float) or last_close <= 0:
            continue
        forecast_close = float(values[-1])
        expected_return_pct = round((forecast_close / float(last_close) - 1.0) * 100.0, 4)
        if max_abs_return_pct and abs(expected_return_pct) > max_abs_return_pct:
            # Implausible over a short horizon -> a model artifact, not a signal.
            continue
        rmse = forecast.get("backtest_rmse")
        rmse_pct = (
            round(float(rmse) / float(last_close) * 100.0, 4)
            if isinstance(rmse, int | float)
            else None
        )
        rows.append(
            {
                "ticker": ticker,
                "last_close": float(last_close),
                "forecast_close": round(forecast_close, 4),
                "expected_return_pct": expected_return_pct,
                "horizon": forecast.get("horizon"),
                "backtest_best_model": forecast.get("backtest_best_model"),
                "backtest_rmse": forecast.get("backtest_rmse"),
                "rmse_pct": rmse_pct,
                "observations": forecast.get("observations"),
            }
        )
    rows.sort(key=lambda item: (-float(item["expected_return_pct"]), str(item["ticker"])))
    return rows[: top] if top and top > 0 else rows
