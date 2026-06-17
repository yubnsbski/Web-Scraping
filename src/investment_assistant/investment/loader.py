"""CSV and JSON normalization for investment-only inputs."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from investment_assistant.investment.models import (
    FUND_PROFILE_COLUMNS,
    FUND_PROFILE_OPTIONAL_COLUMNS,
    FUND_PROFILE_TEMPLATE_COLUMNS,
    HOLDING_COLUMNS,
    HOLDING_OPTIONAL_COLUMNS,
    HOLDING_RECOMMENDED_COLUMNS,
    HOLDING_TEMPLATE_COLUMNS,
    FundProfile,
    InvestmentHolding,
)

_ROW_ERROR_RE = re.compile(r"^Row (?P<row>\d+): (?P<detail>.+)$")


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


def validate_holdings_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate holdings input without raising loader exceptions."""

    base = _validation_base(
        kind="holdings",
        columns=HOLDING_TEMPLATE_COLUMNS,
        required_columns=HOLDING_COLUMNS,
        optional_columns=HOLDING_OPTIONAL_COLUMNS,
        recommended_columns=HOLDING_RECOMMENDED_COLUMNS,
    )
    if not _has_payload_source(payload, ("holdings", "csv_text", "path")):
        base["errors"] = [
            _validation_error(
                code="input_missing",
                message="holdings, csv_text, or path is required",
            )
        ]
        return base

    try:
        holdings = holdings_from_payload(payload)
    except (ValueError, FileNotFoundError, OSError) as exc:
        base["errors"] = [_loader_error_to_validation(exc)]
        return base

    if not holdings:
        base["errors"] = [
            _validation_error(
                code="empty_payload",
                message="Holding payload must contain at least one row.",
            )
        ]
        return base

    warnings = holding_input_warnings(payload, holdings)
    return {
        **base,
        "valid": True,
        "count": len(holdings),
        "holdings": dicts(holdings),
        "warnings": warnings,
        "input_warnings": warnings,
    }


def holding_input_warnings(
    payload: Mapping[str, object],
    holdings: Iterable[InvestmentHolding],
) -> list[dict[str, object]]:
    """Return non-blocking guidance for more auditable holding inputs."""

    holding_list = list(holdings)
    warnings: list[dict[str, object]] = []
    fieldnames = _payload_holding_fieldnames(payload)
    if fieldnames is not None:
        for column in HOLDING_RECOMMENDED_COLUMNS:
            if column not in fieldnames:
                warnings.append(
                    {
                        "level": "info",
                        "code": "recommended_column_missing",
                        "column": column,
                        "message": f"Optional column '{column}' is recommended for auditability.",
                    }
                )

    for row, holding in enumerate(holding_list, start=2):
        if holding.current_price is not None and not holding.price_as_of:
            warnings.append(
                {
                    "level": "info",
                    "code": "price_as_of_recommended",
                    "row": row,
                    "security_code": holding.ticker_or_fund_code,
                    "column": "price_as_of",
                    "message": "price_as_of is recommended when current_price is provided.",
                }
            )
        if holding.current_price is not None and not holding.data_provider:
            warnings.append(
                {
                    "level": "info",
                    "code": "data_provider_recommended",
                    "row": row,
                    "security_code": holding.ticker_or_fund_code,
                    "column": "data_provider",
                    "message": "data_provider is recommended when current_price is provided.",
                }
            )
    return warnings


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


def validate_fund_profiles_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate fund profile input without raising loader exceptions."""

    base = _validation_base(
        kind="fund_profiles",
        columns=FUND_PROFILE_TEMPLATE_COLUMNS,
        required_columns=FUND_PROFILE_COLUMNS,
        optional_columns=FUND_PROFILE_OPTIONAL_COLUMNS,
        recommended_columns=(),
    )
    if not _has_payload_source(payload, ("funds", "funds_csv_text", "funds_path")):
        base["errors"] = [
            _validation_error(
                code="input_missing",
                message="funds, funds_csv_text, or funds_path is required",
            )
        ]
        return base

    try:
        funds = fund_profiles_from_payload(payload)
    except (ValueError, FileNotFoundError, OSError) as exc:
        base["errors"] = [_loader_error_to_validation(exc)]
        return base

    if not funds:
        base["errors"] = [
            _validation_error(
                code="empty_payload",
                message="Fund profile payload must contain at least one row.",
            )
        ]
        return base

    return {
        **base,
        "valid": True,
        "count": len(funds),
        "funds": dicts(funds),
    }


def holding_csv_template(*, include_examples: bool = False) -> dict[str, object]:
    """Return an audit-ready holding CSV template."""

    rows = (
        [
            {
                "asset_type": "stock",
                "ticker_or_fund_code": "7203",
                "name": "Example Stock",
                "quantity": "100",
                "avg_cost": "1800",
                "account_type": "tokutei",
                "tax_wrapper": "nisa_growth",
                "source": "user_csv",
                "current_price": "2200",
                "annual_income": "",
                "distribution_per_unit": "",
                "data_provider": "user_csv",
                "price_as_of": "2026-06-10",
            },
            {
                "asset_type": "fund",
                "ticker_or_fund_code": "FND001",
                "name": "Example Fund",
                "quantity": "120",
                "avg_cost": "10000",
                "account_type": "nisa",
                "tax_wrapper": "nisa_tsumitate",
                "source": "user_csv",
                "current_price": "12500",
                "annual_income": "",
                "distribution_per_unit": "25",
                "data_provider": "user_csv",
                "price_as_of": "2026-06-10",
            },
        ]
        if include_examples
        else []
    )
    return {
        "kind": "holdings",
        "csv_text": _write_csv(HOLDING_TEMPLATE_COLUMNS, rows),
        "columns": list(HOLDING_TEMPLATE_COLUMNS),
        "required_columns": list(HOLDING_COLUMNS),
        "optional_columns": list(HOLDING_OPTIONAL_COLUMNS),
        "recommended_columns": list(HOLDING_RECOMMENDED_COLUMNS),
        "example_included": include_examples,
        "auto_trading": False,
        "call_real_api": False,
    }


def fund_profile_csv_template(*, include_examples: bool = False) -> dict[str, object]:
    """Return a fund profile CSV template."""

    rows = (
        [
            {
                "fund_code": "FND001",
                "name": "Example Global Equity Fund",
                "asset_class": "global_equity",
                "expense_ratio": "0.12",
                "distribution_policy": "reinvest",
                "nisa_eligible": "true",
                "provider_id": "user_csv",
                "diversification_score": "0.95",
            }
        ]
        if include_examples
        else []
    )
    return {
        "kind": "fund_profiles",
        "csv_text": _write_csv(FUND_PROFILE_TEMPLATE_COLUMNS, rows),
        "columns": list(FUND_PROFILE_TEMPLATE_COLUMNS),
        "required_columns": list(FUND_PROFILE_COLUMNS),
        "optional_columns": list(FUND_PROFILE_OPTIONAL_COLUMNS),
        "recommended_columns": [],
        "example_included": include_examples,
        "auto_trading": False,
        "call_real_api": False,
    }


def load_holdings_csv(path: str | Path) -> list[InvestmentHolding]:
    return load_holdings_csv_text(Path(path).read_text(encoding="utf-8-sig"))


def load_holdings_csv_text(text: str) -> list[InvestmentHolding]:
    rows = _read_rows(text, required=HOLDING_COLUMNS)
    holdings = [_holding_from_mapping(row, row=index) for index, row in enumerate(rows, start=2)]
    if not holdings:
        raise ValueError("Holding CSV must contain at least one row.")
    return holdings


def load_funds_csv(path: str | Path) -> list[FundProfile]:
    return load_funds_csv_text(Path(path).read_text(encoding="utf-8-sig"))


def load_funds_csv_text(text: str) -> list[FundProfile]:
    rows = _read_rows(text, required=FUND_PROFILE_COLUMNS)
    funds = [_fund_from_mapping(row, row=index) for index, row in enumerate(rows, start=2)]
    if not funds:
        raise ValueError("Fund profile CSV must contain at least one row.")
    return funds


def _csv_body(text: str) -> str:
    """Trim whitespace and a leading UTF-8 BOM (common in Excel/Windows CSVs).

    ``str.strip`` does not remove the BOM (U+FEFF), so without this the first
    header cell parses as ``"﻿asset_type"`` and the required-column check
    fails with a misleading "missing column" error.
    """

    return text.strip().lstrip("﻿")


def _read_rows(text: str, *, required: tuple[str, ...]) -> list[dict[str, str]]:
    # newline="" lets csv handle CRLF / lone-CR (Excel exports) without raising
    # "new-line character seen in unquoted field".
    reader = csv.DictReader(io.StringIO(_csv_body(text), newline=""))
    fieldnames = set(reader.fieldnames or [])
    missing = [column for column in required if column not in fieldnames]
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}")
    return [dict(row) for row in reader]


def _payload_holding_fieldnames(payload: Mapping[str, object]) -> set[str] | None:
    csv_text = payload.get("csv_text")
    if isinstance(csv_text, str) and csv_text.strip():
        return _csv_fieldnames(csv_text)

    path = payload.get("path")
    if isinstance(path, str) and path.strip():
        csv_path = Path(path)
        if csv_path.is_file():
            return _csv_fieldnames(csv_path.read_text(encoding="utf-8-sig"))

    raw_holdings = payload.get("holdings")
    if isinstance(raw_holdings, list) and raw_holdings:
        keys: set[str] = set()
        for item in raw_holdings:
            if isinstance(item, Mapping):
                keys.update(str(key) for key in item)
        return keys
    return None


def _csv_fieldnames(text: str) -> set[str]:
    reader = csv.DictReader(io.StringIO(_csv_body(text), newline=""))
    return {str(field) for field in (reader.fieldnames or [])}


def _write_csv(columns: tuple[str, ...], rows: Sequence[Mapping[str, object]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return output.getvalue()


def _validation_base(
    *,
    kind: str,
    columns: tuple[str, ...],
    required_columns: tuple[str, ...],
    optional_columns: tuple[str, ...],
    recommended_columns: tuple[str, ...],
) -> dict[str, object]:
    return {
        "kind": kind,
        "valid": False,
        "count": 0,
        "errors": [],
        "warnings": [],
        "columns": list(columns),
        "required_columns": list(required_columns),
        "optional_columns": list(optional_columns),
        "recommended_columns": list(recommended_columns),
        "auto_trading": False,
        "call_real_api": False,
    }


def _has_payload_source(payload: Mapping[str, object], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            if value.strip():
                return True
        elif isinstance(value, list):
            return True
    return False


def _loader_error_to_validation(exc: Exception) -> dict[str, object]:
    message = str(exc)
    if message.startswith("Missing required CSV columns: "):
        columns = [
            column.strip()
            for column in message.removeprefix("Missing required CSV columns: ").split(",")
            if column.strip()
        ]
        return _validation_error(
            code="required_column_missing",
            message=message,
            columns=columns,
        )
    if message in {
        "holdings, csv_text, or path is required",
        "funds, funds_csv_text, or funds_path is required",
    }:
        return _validation_error(code="input_missing", message=message)
    if "must contain at least one row" in message:
        return _validation_error(code="empty_csv", message=message)

    row_match = _ROW_ERROR_RE.match(message)
    if row_match:
        detail = row_match.group("detail").rstrip(".")
        column = detail.split(" ", maxsplit=1)[0] if detail else ""
        return _validation_error(
            code="row_invalid",
            message=message,
            row=int(row_match.group("row")),
            column=column,
        )
    return _validation_error(code="invalid_input", message=message)


def _validation_error(
    *,
    code: str,
    message: str,
    row: int | None = None,
    column: str | None = None,
    columns: Sequence[str] | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {
        "level": "error",
        "code": code,
        "message": message,
    }
    if row is not None:
        error["row"] = row
    if column:
        error["column"] = column
    if columns is not None:
        error["columns"] = list(columns)
    return error


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
        data_provider=_optional_text(mapping.get("data_provider")),
        price_as_of=_optional_text(mapping.get("price_as_of")),
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


def _optional_text(value: object) -> str | None:
    text = _text(value, default="")
    return text or None


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
