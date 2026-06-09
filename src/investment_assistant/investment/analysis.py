"""Deterministic portfolio analysis for Japanese stocks and funds."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV, load_comparison
from investment_assistant.investment.models import DISCLAIMER, InvestmentHolding

_NISA_LIFETIME_CAP = 18_000_000.0
_NISA_GROWTH_CAP = 12_000_000.0


def analyze_portfolio(
    holdings: Sequence[InvestmentHolding],
    *,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
) -> dict[str, object]:
    """Analyze user-provided holdings without LLMs or recommendations."""

    if not holdings:
        raise ValueError("At least one holding is required.")

    generated_at = datetime.now(UTC).isoformat()
    companies = _company_index(financials_csv)
    rows: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    total_market = 0.0
    total_cost = 0.0
    total_income = 0.0
    asset_mix: dict[str, float] = {}
    tax_wrapper_mix: dict[str, float] = {}
    nisa_cost = 0.0
    nisa_growth_cost = 0.0

    for holding in holdings:
        price = holding.current_price if holding.current_price is not None else holding.avg_cost
        market_value = holding.quantity * price
        cost_basis = holding.quantity * holding.avg_cost
        company = companies.get(holding.ticker_or_fund_code)
        annual_income, income_source = _annual_income(holding, company)
        pnl = market_value - cost_basis
        row = {
            **holding.to_dict(),
            "price_used": round(price, 4),
            "price_source": "current_price" if holding.current_price is not None else "avg_cost",
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_pnl": round(pnl, 2),
            "unrealized_pnl_pct": round(pnl / cost_basis * 100.0, 2) if cost_basis else 0.0,
            "annual_income_estimate": round(annual_income, 2),
            "annual_income_source": income_source,
            "income_yield_pct": round(annual_income / market_value * 100.0, 2)
            if market_value
            else 0.0,
        }
        rows.append(row)
        total_market += market_value
        total_cost += cost_basis
        total_income += annual_income
        asset_mix[holding.asset_type] = asset_mix.get(holding.asset_type, 0.0) + market_value
        wrapper = _tax_wrapper(holding.tax_wrapper)
        tax_wrapper_mix[wrapper] = tax_wrapper_mix.get(wrapper, 0.0) + market_value
        if wrapper.startswith("nisa"):
            nisa_cost += cost_basis
            if wrapper in {"nisa_growth", "growth_nisa"}:
                nisa_growth_cost += cost_basis
        evidence.append(
            {
                "claim_key": f"holding.{holding.ticker_or_fund_code}.market_value",
                "source_type": "user_holding",
                "source_ref": holding.source,
                "metric_key": "market_value",
                "formula": "quantity * current_price; falls back to avg_cost when missing",
                "last_updated": generated_at,
                "note": "quantity × current_price（未入力時はavg_cost）",
            }
        )
        evidence.append(
            {
                "claim_key": f"holding.{holding.ticker_or_fund_code}.cost_basis",
                "source_type": "user_holding",
                "source_ref": holding.source,
                "metric_key": "cost_basis",
                "formula": "quantity * avg_cost",
                "last_updated": generated_at,
                "note": "User-provided quantity and average acquisition cost.",
            }
        )
        if income_source != "not_available":
            evidence.append(
                {
                    "claim_key": f"holding.{holding.ticker_or_fund_code}.annual_income",
                    "source_type": income_source,
                    "source_ref": str(financials_csv)
                    if income_source == "edinet_latest_dividend_per_share"
                    else holding.source,
                    "metric_key": "annual_income_estimate",
                    "formula": "quantity * dividend_or_distribution_per_unit",
                    "last_updated": generated_at,
                    "note": "Income estimate is deterministic and not a future guarantee.",
                }
            )
        if company is not None:
            evidence.append(
                {
                    "claim_key": f"holding.{holding.ticker_or_fund_code}.dividend",
                    "source_type": "edinet_financials",
                    "source_ref": str(financials_csv),
                    "metric_key": "latest_dividend_per_share",
                    "formula": "latest_dividend_per_share * quantity",
                    "last_updated": generated_at,
                    "note": "取得済みEDINET financials.csv の機械集計",
                }
            )

    largest = max(rows, key=lambda item: _number(item.get("market_value")) or 0.0)
    largest_value = _number(largest.get("market_value")) or 0.0
    portfolio_pnl = total_market - total_cost
    summary = {
        "holdings_count": len(rows),
        "market_value": round(total_market, 2),
        "cost_basis": round(total_cost, 2),
        "unrealized_pnl": round(portfolio_pnl, 2),
        "unrealized_pnl_pct": round(portfolio_pnl / total_cost * 100.0, 2) if total_cost else 0.0,
        "annual_income_estimate": round(total_income, 2),
        "income_yield_pct": round(total_income / total_market * 100.0, 2) if total_market else 0.0,
        "largest_position": {
            "code": largest["ticker_or_fund_code"],
            "name": largest["name"],
            "share_pct": round(largest_value / total_market * 100.0, 2) if total_market else 0.0,
        },
        "concentration": _concentration(rows, total_market),
        "asset_mix": _share_map(asset_mix, total_market),
        "tax_wrapper_mix": _share_map(tax_wrapper_mix, total_market),
        "nisa": {
            "used_cost_basis": round(nisa_cost, 2),
            "remaining_lifetime": round(max(_NISA_LIFETIME_CAP - nisa_cost, 0.0), 2),
            "growth_used_cost_basis": round(nisa_growth_cost, 2),
            "growth_remaining": round(max(_NISA_GROWTH_CAP - nisa_growth_cost, 0.0), 2),
        },
    }
    evidence.append(
        {
            "claim_key": "portfolio.nisa.used_cost_basis",
            "source_type": "user_holding",
            "source_ref": "holdings.tax_wrapper",
            "metric_key": "nisa_used_cost_basis",
            "formula": "sum(cost_basis where normalized tax_wrapper starts with nisa)",
            "last_updated": generated_at,
            "note": "NISA remaining capacity uses acquisition cost basis, not market value.",
        }
    )
    return {
        "available": True,
        "generated_at": generated_at,
        "summary": summary,
        "holdings": rows,
        "evidence": evidence,
        "disclaimer": DISCLAIMER,
        "auto_trading": False,
        "call_real_api": False,
    }


def _company_index(financials_csv: str | Path) -> dict[str, dict[str, object]]:
    comparison = load_comparison(financials_csv)
    if comparison is None:
        return {}
    companies = comparison.get("companies")
    if not isinstance(companies, list):
        return {}
    out: dict[str, dict[str, object]] = {}
    for company in companies:
        if isinstance(company, dict):
            ticker = str(company.get("ticker") or "").strip()
            if ticker:
                out[ticker] = company
    return out


def _annual_income(
    holding: InvestmentHolding, company: dict[str, object] | None
) -> tuple[float, str]:
    if holding.annual_income is not None:
        return max(holding.annual_income, 0.0), "user_annual_income"
    if holding.distribution_per_unit is not None:
        return max(holding.distribution_per_unit, 0.0) * holding.quantity, "user_distribution"
    if holding.asset_type == "stock" and company is not None:
        dps = _number(company.get("latest_dividend_per_share"))
        if dps is not None:
            return dps * holding.quantity, "edinet_latest_dividend_per_share"
    return 0.0, "not_available"


def _concentration(rows: list[dict[str, object]], total_market: float) -> dict[str, object]:
    if total_market <= 0:
        return {"hhi": 0.0, "top3_share_pct": 0.0}
    shares = sorted(
        ((_number(row.get("market_value")) or 0.0) / total_market for row in rows),
        reverse=True,
    )
    return {
        "hhi": round(sum(share * share for share in shares), 4),
        "top3_share_pct": round(sum(shares[:3]) * 100.0, 2),
    }


def _share_map(values: dict[str, float], total: float) -> dict[str, dict[str, float]]:
    return {
        key: {
            "value": round(value, 2),
            "share_pct": round(value / total * 100.0, 2) if total else 0.0,
        }
        for key, value in sorted(values.items())
    }


def _tax_wrapper(value: str) -> str:
    text = value.strip().lower()
    aliases = {
        "new_nisa": "nisa",
        "nisa_growth": "nisa_growth",
        "growth": "nisa_growth",
        "つみたて": "nisa_tsumitate",
        "nisa_tsumitate": "nisa_tsumitate",
        "taxable": "taxable",
        "特定": "taxable",
    }
    return aliases.get(text, text or "taxable")


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
