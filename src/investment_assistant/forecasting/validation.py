"""CSV validation for local forecasting inputs."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from investment_assistant.forecasting.models import ForecastPoint

REQUIRED_COLUMNS = frozenset({"date", "value"})


class ForecastValidationError(ValueError):
    """Raised when a forecasting CSV cannot be safely used."""


def load_forecast_csv(path: str | Path) -> list[ForecastPoint]:
    """Load and validate a local forecasting CSV.

    Required columns:
    - date: ISO 8601 date, for example 2026-01-31
    - value: positive numeric target value

    Optional columns:
    - symbol: user-provided label such as a ticker or fund name
    """

    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_COLUMNS - fieldnames)
        if missing_columns:
            missing = ", ".join(missing_columns)
            raise ForecastValidationError(f"missing required columns: {missing}")

        errors: list[str] = []
        points: list[ForecastPoint] = []
        seen_dates: set[date] = set()

        for row_number, row in enumerate(reader, start=2):
            parsed_date = _parse_date(row.get("date"), row_number, errors)
            parsed_value = _parse_value(row.get("value"), row_number, errors)
            symbol = _parse_symbol(row.get("symbol"))

            if parsed_date is None or parsed_value is None:
                continue

            if parsed_date in seen_dates:
                errors.append(f"row {row_number}: duplicate date {parsed_date.isoformat()}")
                continue

            seen_dates.add(parsed_date)
            points.append(ForecastPoint(date=parsed_date, value=parsed_value, symbol=symbol))

    if errors:
        raise ForecastValidationError("; ".join(errors))
    if not points:
        raise ForecastValidationError("forecasting CSV must contain at least one data row")

    return sorted(points, key=lambda point: point.date)


def _parse_date(raw_value: str | None, row_number: int, errors: list[str]) -> date | None:
    value = (raw_value or "").strip()
    if not value:
        errors.append(f"row {row_number}: date is required")
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"row {row_number}: date must be ISO 8601 format")
        return None


def _parse_value(raw_value: str | None, row_number: int, errors: list[str]) -> float | None:
    value = (raw_value or "").strip()
    if not value:
        errors.append(f"row {row_number}: value is required")
        return None

    try:
        parsed_value = float(value)
    except ValueError:
        errors.append(f"row {row_number}: value must be numeric")
        return None

    if parsed_value <= 0:
        errors.append(f"row {row_number}: value must be positive")
        return None

    return parsed_value


def _parse_symbol(raw_value: str | None) -> str | None:
    value = (raw_value or "").strip()
    return value or None
