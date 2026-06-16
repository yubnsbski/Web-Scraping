"""Portfolio summary, simulation, target, and universe JSON API handlers."""

from __future__ import annotations

from typing import Any

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
from investment_assistant.portfolio.loader import (
    load_dividends,
    load_performance,
    summarize_dividends,
    summarize_performance,
)

JsonDict = dict[str, Any]


def portfolio_dividends(body: JsonDict) -> JsonDict:
    path = str(body.get("path") or "examples/portfolio_dividends_sample.csv")
    return summarize_dividends(load_dividends(path))


def portfolio_simulate(body: JsonDict) -> JsonDict:
    from investment_assistant.portfolio.simulator import simulate_portfolio

    holdings, common = _portfolio_inputs(body)
    budget = _as_float(body.get("budget"), 0.0)
    return simulate_portfolio(budget=budget, holdings=holdings, **common)


def portfolio_target(body: JsonDict) -> JsonDict:
    from investment_assistant.portfolio.simulator import plan_for_target_dividend

    holdings, common = _portfolio_inputs(body)
    return plan_for_target_dividend(
        target_annual_dividend=_as_float(body.get("target_annual_dividend"), 0.0),
        net_target=_as_bool(body.get("net_target"), False),
        holdings=holdings,
        **common,
    )


def portfolio_universe(body: JsonDict) -> JsonDict:
    from investment_assistant.portfolio.simulator import build_universe

    raw_prices = body.get("prices")
    prices = (
        {str(k): _as_float(v, 0.0) for k, v in raw_prices.items()}
        if isinstance(raw_prices, dict)
        else None
    )
    universe = build_universe(
        str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV), prices=prices
    )
    return {"universe": universe, "count": len(universe)}


def portfolio_performance(body: JsonDict) -> JsonDict:
    path = str(body.get("path") or "examples/portfolio_performance_sample.csv")
    return summarize_performance(load_performance(path))


def _portfolio_inputs(body: JsonDict) -> tuple[list[JsonDict], JsonDict]:
    """Parse the holdings list and the strategy kwargs shared by simulate/target."""

    raw = body.get("holdings")
    holdings = [h for h in raw if isinstance(h, dict)] if isinstance(raw, list) else []
    common: JsonDict = {
        "years": _as_int(body.get("years"), 10),
        "reinvest": _as_bool(body.get("reinvest"), True),
        "growth_rate": _as_float(body.get("growth_rate"), 0.0),
        "auto_weight": str(body.get("auto_weight") or "equal"),
        "optimization": str(body.get("optimization") or "none"),
        "dividend_basis": str(body.get("dividend_basis") or "conservative"),
        "financials_csv": str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
    }
    return holdings, common


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
