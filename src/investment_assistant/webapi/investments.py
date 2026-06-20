"""Investment input, analysis, detail, and screening JSON API handlers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV

JsonDict = dict[str, Any]


def holdings_import(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.loader import (
        holding_input_warnings,
        holdings_from_payload,
    )
    from investment_assistant.investment.models import (
        DISCLAIMER,
        HOLDING_COLUMNS,
        HOLDING_RECOMMENDED_COLUMNS,
    )

    holdings = holdings_from_payload(body)
    return {
        "count": len(holdings),
        "holdings": [holding.to_dict() for holding in holdings],
        "required_columns": list(HOLDING_COLUMNS),
        "recommended_columns": list(HOLDING_RECOMMENDED_COLUMNS),
        "input_warnings": holding_input_warnings(body, holdings),
        "disclaimer": DISCLAIMER,
        "auto_trading": False,
        "call_real_api": False,
    }


def holdings_validate(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import validate_holdings_payload

    return validate_holdings_payload(body)


def holdings_template(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import holding_csv_template

    return holding_csv_template(include_examples=_as_bool(body.get("include_examples"), False))


def funds_validate(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import validate_fund_profiles_payload

    return validate_fund_profiles_payload(body)


def funds_template(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import fund_profile_csv_template

    return fund_profile_csv_template(
        include_examples=_as_bool(body.get("include_examples"), False)
    )


def portfolio_analyze(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import analyze_portfolio, holdings_from_payload

    return analyze_portfolio(
        holdings_from_payload(body),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        market_financials_csv=_market_financials_path(body),
        runtime_mode=str(body.get("runtime_mode") or "development"),
    )


def _market_financials_path(body: JsonDict) -> str | None:
    """Yahoo financials CSV to enrich price/dividend; default if it exists."""

    raw = body.get("market_financials_csv")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    default = "local_docs/market/yahoo_financials.csv"
    return default if Path(default).is_file() else None


def investment_detail(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import (
        build_investment_detail,
        fund_profiles_from_payload,
        holdings_from_payload,
    )

    holdings = (
        _ignore_empty_rows(lambda: holdings_from_payload(body))
        if _has_any(body, "holdings", "csv_text", "path")
        else []
    )
    return build_investment_detail(
        code=str(body.get("code") or body.get("ticker_or_fund_code") or ""),
        asset_type=str(body.get("asset_type") or ""),
        holdings=holdings,
        funds=_ignore_empty_rows(lambda: fund_profiles_from_payload(body)),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        market_financials_csv=_market_financials_path(body),
    )


def _ignore_empty_rows(load: Callable[[], list[Any]]) -> list[Any]:
    """Treat a header-only (rows-less) holdings/funds CSV as "no rows".

    The dashboard ships header-only sample CSVs, so the detail and candidate
    screens send a CSV with columns but no data rows. Holdings and fund
    profiles are optional context for those screens, so an empty CSV should
    yield an empty list instead of a hard error. Genuine malformed-data errors
    (missing columns, bad values) still propagate.
    """

    try:
        return load()
    except ValueError as exc:
        if "must contain at least one row" in str(exc):
            return []
        raise


def candidates_screen(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import fund_profiles_from_payload, screen_candidates
    from investment_assistant.investment.candidates import screen_from_values

    raw_asset_types = body.get("asset_types")
    asset_types = (
        [str(item) for item in raw_asset_types]
        if isinstance(raw_asset_types, list)
        else ["stock", "fund"]
    )
    limit_value = body.get("limit")
    screen = screen_from_values(
        asset_types=asset_types,
        exclude_dividend_cut=_as_bool(body.get("exclude_dividend_cut"), False),
        min_equity_ratio=_optional_float(body.get("min_equity_ratio")),
        max_expense_ratio=_optional_float(body.get("max_expense_ratio")),
        nisa_eligible_only=_as_bool(body.get("nisa_eligible_only"), False),
        min_diversification_score=_optional_float(body.get("min_diversification_score")),
        sort_by=str(body.get("sort_by") or "score"),
        limit=None if limit_value is None else _as_int(limit_value, 0),
    )
    return screen_candidates(
        screen=screen,
        funds=_ignore_empty_rows(lambda: fund_profiles_from_payload(body)),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        runtime_mode=str(body.get("runtime_mode") or "development"),
    )


def _has_any(body: JsonDict, *keys: str) -> bool:
    return any(key in body and body.get(key) not in (None, "") for key in keys)


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _as_float(value, 0.0)
