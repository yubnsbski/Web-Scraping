"""CSV and JSON normalization for investment-only inputs."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from pathlib import Path

from investment_assistant.investment.models import (
    FUND_PROFILE_COLUMNS,
    HOLDING_COLUMNS,
    FundProfile,
    InvestmentHolding,
)


def holdings_from_payload(payload: Mapping[str, object]) -> list[InvestmentHolding]:
    """Load holdings from ``holdings``, ``csv_text``, or ``path`` payload fields."""

    raw_holdings = payload.get("holdings")
    if isinstance(raw_holdings, list):
        return [
            _holding_from_mapping(item, row=index)
            for index, item in enumerate(raw_holdings, start=1)
            if isinstance(item, Mapping)
        ]

    csv_text = payload.get("csv_text")
    if isinstance(csv_text, str) and csv_text.strip():
        return load_holdings_csv_text(csv_text)

    path = payload.get("path")
    if isinstance(path, str) and path.strip():
        return load_holdings_csv(Path(path))

    raise ValueError("holdings, csv_text, or path is required")


def fund_profiles_from_payload(payload: Mapping[str, object]) -> list[FundProfile]:
    """Load fund profiles from ``funds``, ``funds_csv_text``, or ``funds_path``."""

    raw_funds = payload.get("funds")
    if isinstance(raw_funds, list):
        return [
            _fund_from_mapping(item, row=index)
            for index, item in enumerate(raw_funds, start=1)
            if isinstance(item, Mapping)
        ]

    csv_text = payload.get("funds_csv_text")
    if isinstance(csv_text, str) and csv_text.strip():
        return load_funds_csv_text(csv_text)

    path = payload.get("funds_path")
    if isinstance(path, str) and path.strip():
        return load_funds_csv(Path(path))

    return []


def load_holdings_csv(path: str | Path) -> list[InvestmentHolding]:
    return load_holdings_csv_text(Path(path).read_text(encoding="utf-8"))


def load_holdings_csv_text(text: str) -> list[InvestmentHolding]:
    rows = _read_rows(text, required=HOLDING_COLUMNS)
    holdings = [_holding_from_mapping(row, row=index) for index, row in enumerate(rows, start=2)]
    if not holdings:
        raise ValueError("Holding CSV must contain at least one row.")
    return holdings


def validate_holdings_csv_text(text: str) -> dict[str, object]:
    """Validate holding CSV input without raising on row-level data errors."""

    optional_columns = ("current_price", "annual_income", "distribution_per_unit")
    expected_columns = (*HOLDING_COLUMNS, *optional_columns)
    reader = csv.DictReader(io.StringIO(text.strip()))
    fieldnames = list(reader.fieldnames or [])
    rows = [dict(row) for row in reader]
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    valid_holdings: list[InvestmentHolding] = []

    if not fieldnames:
        errors.append({"row": 1, "column": None, "message": "CSV header is required."})
    duplicate_columns = sorted({name for name in fieldnames if fieldnames.count(name) > 1})
    for column in duplicate_columns:
        errors.append({"row": 1, "column": column, "message": "Duplicate CSV column."})
    missing = [column for column in HOLDING_COLUMNS if column not in set(fieldnames)]
    for column in missing:
        errors.append({"row": 1, "column": column, "message": "Missing required CSV column."})
    extra = [column for column in fieldnames if column not in set(expected_columns)]
    for column in extra:
        warnings.append({"row": 1, "column": column, "message": "Unknown column will be ignored."})
    if not rows:
        errors.append(
            {"row": 1, "column": None, "message": "Holding CSV must contain at least one row."}
        )

    if not missing:
        for row_number, row in enumerate(rows, start=2):
            try:
                holding = _holding_from_mapping(row, row=row_number)
            except ValueError as exc:
                message = str(exc)
                errors.append(
                    {
                        "row": row_number,
                        "column": _column_from_error(message),
                        "message": message,
                    }
                )
                continue
            valid_holdings.append(holding)
            warnings.extend(_holding_warnings(holding, row=row_number))

    return {
        "valid": not errors,
        "row_count": len(rows),
        "valid_row_count": len(valid_holdings),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "required_columns": list(HOLDING_COLUMNS),
        "optional_columns": list(optional_columns),
        "auto_trading": False,
        "call_real_api": False,
    }


def load_funds_csv(path: str | Path) -> list[FundProfile]:
    return load_funds_csv_text(Path(path).read_text(encoding="utf-8"))


def load_funds_csv_text(text: str) -> list[FundProfile]:
    rows = _read_rows(text, required=FUND_PROFILE_COLUMNS)
    funds = [_fund_from_mapping(row, row=index) for index, row in enumerate(rows, start=2)]
    if not funds:
        raise ValueError("Fund profile CSV must contain at least one row.")
    return funds


def validate_funds_csv_text(text: str) -> dict[str, object]:
    """Validate fund profile CSV input without raising on row-level data errors."""

    optional_columns = ("diversification_score",)
    expected_columns = (*FUND_PROFILE_COLUMNS, *optional_columns)
    reader = csv.DictReader(io.StringIO(text.strip()))
    fieldnames = list(reader.fieldnames or [])
    rows = [dict(row) for row in reader]
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    valid_funds: list[FundProfile] = []

    if not fieldnames:
        errors.append({"row": 1, "column": None, "message": "CSV header is required."})
    duplicate_columns = sorted({name for name in fieldnames if fieldnames.count(name) > 1})
    for column in duplicate_columns:
        errors.append({"row": 1, "column": column, "message": "Duplicate CSV column."})
    missing = [column for column in FUND_PROFILE_COLUMNS if column not in set(fieldnames)]
    for column in missing:
        errors.append({"row": 1, "column": column, "message": "Missing required CSV column."})
    extra = [column for column in fieldnames if column not in set(expected_columns)]
    for column in extra:
        warnings.append({"row": 1, "column": column, "message": "Unknown column will be ignored."})
    if not rows:
        errors.append(
            {
                "row": 1,
                "column": None,
                "message": "Fund profile CSV must contain at least one row.",
            }
        )

    if not missing:
        for row_number, row in enumerate(rows, start=2):
            try:
                fund = _fund_from_mapping(row, row=row_number)
            except ValueError as exc:
                message = str(exc)
                errors.append(
                    {
                        "row": row_number,
                        "column": _column_from_error(message),
                        "message": message,
                    }
                )
                continue
            valid_funds.append(fund)
            warnings.extend(_fund_warnings(fund, row=row_number))

    return {
        "valid": not errors,
        "row_count": len(rows),
        "valid_row_count": len(valid_funds),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "required_columns": list(FUND_PROFILE_COLUMNS),
        "optional_columns": list(optional_columns),
        "auto_trading": False,
        "call_real_api": False,
    }


def _read_rows(text: str, *, required: tuple[str, ...]) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.strip()))
    fieldnames = set(reader.fieldnames or [])
    missing = [column for column in required if column not in fieldnames]
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}")
    return [dict(row) for row in reader]


def _holding_from_mapping(mapping: Mapping[str, object], *, row: int) -> InvestmentHolding:
    return InvestmentHolding(
        asset_type=_asset_type(_required_text(mapping, "asset_type", row=row)),
        ticker_or_fund_code=_required_text(mapping, "ticker_or_fund_code", row=row),
        name=_required_text(mapping, "name", row=row),
        quantity=_required_float(mapping, "quantity", row=row, min_value=0.0),
        avg_cost=_required_float(mapping, "avg_cost", row=row, min_value=0.0),
        account_type=_text(mapping.get("account_type"), default="manual"),
        tax_wrapper=_text(mapping.get("tax_wrapper"), default="taxable"),
        source=_text(mapping.get("source"), default="user_input"),
        current_price=_optional_float(
            mapping.get("current_price"), row=row, column="current_price"
        ),
        annual_income=_optional_float(
            mapping.get("annual_income"), row=row, column="annual_income"
        ),
        distribution_per_unit=_optional_float(
            mapping.get("distribution_per_unit"), row=row, column="distribution_per_unit"
        ),
    )


def _fund_from_mapping(mapping: Mapping[str, object], *, row: int) -> FundProfile:
    diversification = _optional_float(
        mapping.get("diversification_score"), row=row, column="diversification_score"
    )
    if diversification is not None and not 0.0 <= diversification <= 1.0:
        raise ValueError(f"Row {row}: diversification_score must be between 0 and 1.")
    return FundProfile(
        fund_code=_required_text(mapping, "fund_code", row=row),
        name=_required_text(mapping, "name", row=row),
        asset_class=_text(mapping.get("asset_class"), default="unknown"),
        expense_ratio=_required_float(mapping, "expense_ratio", row=row, min_value=0.0),
        distribution_policy=_text(mapping.get("distribution_policy"), default="unknown"),
        nisa_eligible=_bool(mapping.get("nisa_eligible")),
        provider_id=_text(mapping.get("provider_id"), default="user_csv"),
        diversification_score=diversification,
    )


def _asset_type(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "jp_stock": "stock",
        "japan_stock": "stock",
        "equity": "stock",
        "mutual_fund": "fund",
        "investment_trust": "fund",
        "投信": "fund",
        "日本株": "stock",
    }
    return aliases.get(normalized, normalized)


def _required_text(mapping: Mapping[str, object], column: str, *, row: int) -> str:
    value = _text(mapping.get(column), default="")
    if not value:
        raise ValueError(f"Row {row}: {column} is required.")
    return value


def _required_float(
    mapping: Mapping[str, object], column: str, *, row: int, min_value: float | None = None
) -> float:
    parsed = _optional_float(mapping.get(column), row=row, column=column)
    if parsed is None:
        raise ValueError(f"Row {row}: {column} is required.")
    if min_value is not None and parsed < min_value:
        raise ValueError(f"Row {row}: {column} must be >= {min_value:g}.")
    return parsed


def _optional_float(value: object, *, row: int, column: str) -> float | None:
    text = _text(value, default="")
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Row {row}: {column} must be numeric.") from exc


def _text(value: object, *, default: str) -> str:
    if value is None:
        return default
    return str(value).strip()


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on", "対象", "eligible"}


def dicts(items: Iterable[InvestmentHolding | FundProfile]) -> list[dict[str, object]]:
    return [item.to_dict() for item in items]


def _holding_warnings(holding: InvestmentHolding, *, row: int) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    if holding.asset_type not in {"stock", "fund"}:
        warnings.append(
            {
                "row": row,
                "column": "asset_type",
                "message": "asset_type is not one of stock or fund.",
            }
        )
    if holding.quantity == 0:
        warnings.append({"row": row, "column": "quantity", "message": "quantity is zero."})
    if holding.avg_cost == 0:
        warnings.append({"row": row, "column": "avg_cost", "message": "avg_cost is zero."})
    if holding.current_price is None:
        warnings.append(
            {
                "row": row,
                "column": "current_price",
                "message": "current_price is missing; avg_cost will be used for valuation.",
            }
        )
    return warnings


def _fund_warnings(fund: FundProfile, *, row: int) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    if fund.expense_ratio > 1.0:
        warnings.append(
            {
                "row": row,
                "column": "expense_ratio",
                "message": "expense_ratio is above 1.0; confirm whether the unit is percent.",
            }
        )
    if fund.diversification_score is None:
        warnings.append(
            {
                "row": row,
                "column": "diversification_score",
                "message": (
                    "diversification_score is missing; "
                    "diversification filter may exclude this fund."
                ),
            }
        )
    if not fund.nisa_eligible:
        warnings.append(
            {
                "row": row,
                "column": "nisa_eligible",
                "message": "fund is not marked as NISA eligible.",
            }
        )
    return warnings


def _column_from_error(message: str) -> str | None:
    marker = ": "
    if marker not in message:
        return None
    tail = message.split(marker, 1)[1]
    for suffix in (" is required.", " must be numeric.", " must be >="):
        if suffix in tail:
            return tail.split(suffix, 1)[0]
    return None
