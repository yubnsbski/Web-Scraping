"""Load portfolio CSVs and build local, non-advisory summaries."""

from __future__ import annotations

import csv
from pathlib import Path

from investment_assistant.portfolio.models import (
    DIVIDEND_COLUMNS,
    PERFORMANCE_COLUMNS,
    DividendPoint,
    PerformancePoint,
)

DISCLAIMER = (
    "これはユーザー提供データに基づく機械的な集計であり、"
    "投資助言・売買推奨・将来リターンの保証ではありません。"
    "最終的な投資判断はユーザー本人が行います。自動売買は行いません。"
)


def _require_columns(fieldnames: set[str], required: tuple[str, ...]) -> None:
    missing = [column for column in required if column not in fieldnames]
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}")


def _parse_float(value: str | None, *, row: int, column: str) -> float:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"Row {row}: {column} is required.")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Row {row}: {column} must be numeric.") from exc


def load_dividends(path: str | Path) -> list[DividendPoint]:
    csv_path = Path(path)
    points: list[DividendPoint] = []

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(set(reader.fieldnames or []), DIVIDEND_COLUMNS)

        for index, row in enumerate(reader, start=2):
            period = (row.get("period") or "").strip()
            if not period:
                raise ValueError(f"Row {index}: period is required.")

            dividend_received = _parse_float(
                row.get("dividend_received"),
                row=index,
                column="dividend_received",
            )
            yield_pct = _parse_float(
                row.get("yield_pct"),
                row=index,
                column="yield_pct",
            )

            if dividend_received < 0:
                raise ValueError(f"Row {index}: dividend_received must be >= 0.")

            points.append(
                DividendPoint(
                    period=period,
                    dividend_received=dividend_received,
                    yield_pct=yield_pct,
                )
            )

    if not points:
        raise ValueError("Dividend CSV must contain at least one row.")

    return points


def load_performance(path: str | Path) -> list[PerformancePoint]:
    csv_path = Path(path)
    points: list[PerformancePoint] = []

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(set(reader.fieldnames or []), PERFORMANCE_COLUMNS)

        for index, row in enumerate(reader, start=2):
            period = (row.get("period") or "").strip()
            if not period:
                raise ValueError(f"Row {index}: period is required.")

            market_value = _parse_float(
                row.get("market_value"),
                row=index,
                column="market_value",
            )
            principal = _parse_float(
                row.get("principal"),
                row=index,
                column="principal",
            )

            if market_value < 0 or principal < 0:
                raise ValueError(
                    f"Row {index}: market_value and principal must be >= 0."
                )

            points.append(
                PerformancePoint(
                    period=period,
                    market_value=market_value,
                    principal=principal,
                )
            )

    if not points:
        raise ValueError("Performance CSV must contain at least one row.")

    return points


def _max_drawdown_pct(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0

    for value in values:
        peak = max(peak, value)
        if peak > 0:
            drawdown = (value - peak) / peak * 100.0
            worst = min(worst, drawdown)

    return round(worst, 2)


def summarize_dividends(points: list[DividendPoint]) -> dict[str, object]:
    received = [point.dividend_received for point in points]
    yields = [point.yield_pct for point in points]

    streak = 1
    for previous, current in zip(points, points[1:], strict=False):
        if current.dividend_received > previous.dividend_received:
            streak += 1
        else:
            streak = 1

    return {
        "latest_annual": round(received[-1], 2),
        "avg_yield_pct": round(sum(yields) / len(yields), 2),
        "increase_streak": streak,
        "periods": len(points),
        "series": [
            {
                "period": point.period,
                "dividend_received": point.dividend_received,
                "yield_pct": point.yield_pct,
            }
            for point in points
        ],
        "disclaimer": DISCLAIMER,
    }


def summarize_performance(points: list[PerformancePoint]) -> dict[str, object]:
    latest = points[-1]

    return {
        "market_value": round(latest.market_value, 2),
        "principal": round(latest.principal, 2),
        "pnl": latest.pnl,
        "pnl_pct": latest.pnl_pct,
        "max_drawdown_pct": _max_drawdown_pct(
            [point.market_value for point in points]
        ),
        "periods": len(points),
        "series": [
            {
                "period": point.period,
                "market_value": point.market_value,
                "principal": point.principal,
                "pnl": point.pnl,
                "pnl_pct": point.pnl_pct,
            }
            for point in points
        ],
        "disclaimer": DISCLAIMER,
    }
