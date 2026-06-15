"""Deterministic portfolio analysis for Japanese stocks and funds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.financials.current_yield import (
    DEFAULT_CURRENT_YIELDS_CSV,
    CurrentYieldFact,
    load_current_yields,
    reconcile_current_yield,
)
from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV, load_comparison
from investment_assistant.investment.edinet import build_edinet_summary
from investment_assistant.investment.models import DISCLAIMER, InvestmentHolding
from investment_assistant.investment.provider_policy import ProviderPolicy, provider_policy

_NISA_LIFETIME_CAP = 18_000_000.0
_NISA_GROWTH_CAP = 12_000_000.0
_NISA_NEAR_LIMIT_PCT = 90.0
_PRICE_STALE_AFTER_DAYS = 7
_FINANCIALS_STALE_AFTER_DAYS = 120
_HIGH_INCOME_YIELD_PCT = 12.0


def analyze_portfolio(
    holdings: Sequence[InvestmentHolding],
    *,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    current_yields_csv: str | Path | None = DEFAULT_CURRENT_YIELDS_CSV,
    runtime_mode: str = "development",
) -> dict[str, object]:
    """Analyze user-provided holdings without LLMs or recommendations."""

    if not holdings:
        raise ValueError("At least one holding is required.")

    generated_at_dt = datetime.now(UTC)
    generated_at = generated_at_dt.isoformat()
    companies = _company_index(financials_csv)
    current_yields = load_current_yields(current_yields_csv)
    financials_metadata = _financials_metadata(financials_csv, generated_at_dt)
    rows: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    data_alerts = _financials_alerts(
        holdings=holdings,
        metadata=financials_metadata,
    )
    total_market = 0.0
    total_cost = 0.0
    total_income = 0.0
    asset_mix: dict[str, float] = {}
    tax_wrapper_mix: dict[str, float] = {}
    nisa_cost = 0.0
    nisa_growth_cost = 0.0
    income_alerts: list[dict[str, object]] = []

    for holding in holdings:
        price = holding.current_price if holding.current_price is not None else holding.avg_cost
        market_value = holding.quantity * price
        cost_basis = holding.quantity * holding.avg_cost
        company = companies.get(holding.ticker_or_fund_code)
        current_yield_fact = current_yields.get(holding.ticker_or_fund_code)
        edinet_dps = _number((company or {}).get("latest_dividend_per_share"))
        yield_reconciliation = reconcile_current_yield(
            ticker=holding.ticker_or_fund_code,
            name=holding.name,
            edinet_dividend_per_share=edinet_dps,
            current_price=price,
            fact=current_yield_fact,
        )
        annual_income, income_source = _annual_income(
            holding,
            company,
            current_yield=current_yield_fact,
        )
        provider_id = _holding_provider_id(holding)
        policy = provider_policy(provider_id, runtime_mode=runtime_mode)
        pnl = market_value - cost_basis
        row = {
            **holding.to_dict(),
            "data_provider": provider_id,
            "provider_policy": policy.to_dict(),
            "price_used": round(price, 4),
            "price_source": "current_price" if holding.current_price is not None else "avg_cost",
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_pnl": round(pnl, 2),
            "unrealized_pnl_pct": round(pnl / cost_basis * 100.0, 2) if cost_basis else 0.0,
            "annual_income_estimate": round(annual_income, 2),
            "annual_income_source": income_source,
            "current_yield_reconciliation": yield_reconciliation.to_dict(),
            "income_yield_pct": round(annual_income / market_value * 100.0, 2)
            if market_value
            else 0.0,
        }
        if company is not None:
            row["edinet_summary"] = build_edinet_summary(
                company,
                financials_csv=financials_csv,
                generated_at=generated_at,
            )
        row_data_alerts = _holding_data_alerts(
            holding=holding,
            generated_at=generated_at_dt,
            provider_id=provider_id,
            policy=policy,
        )
        row["data_alerts"] = row_data_alerts
        row_income_alerts = _income_alerts(
            holding=holding,
            row=row,
            market_value=market_value,
            income_source=income_source,
            yield_reconciliation=yield_reconciliation.to_dict(),
        )
        row["data_alerts"] = row_data_alerts
        row["income_alerts"] = row_income_alerts
        rows.append(row)
        data_alerts.extend(row_data_alerts)
        income_alerts.extend(row_income_alerts)
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
                    "source_ref": _income_source_ref(
                        income_source=income_source,
                        holding=holding,
                        financials_csv=financials_csv,
                        current_yield=current_yield_fact,
                    ),
                    "metric_key": "annual_income_estimate",
                    "formula": _income_formula(income_source),
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
    nisa = _nisa_summary(nisa_cost=nisa_cost, nisa_growth_cost=nisa_growth_cost)
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
        "nisa": nisa,
        "edinet_covered_holdings": sum(1 for row in rows if row.get("edinet_summary")),
        "edinet_source_ref": str(financials_csv),
        "current_yields_source_ref": str(current_yields_csv)
        if current_yields_csv is not None
        else None,
        "current_yield_overlay_count": len(current_yields),
        "data_quality": _data_quality_summary(data_alerts),
        "income_quality": _income_quality_summary(income_alerts),
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
    evidence.append(
        {
            "claim_key": "portfolio.data_quality",
            "source_type": "data_policy",
            "source_ref": "holdings.data_provider, holdings.price_as_of, financials_csv",
            "metric_key": "data_quality",
            "formula": (
                "provider policy check + price timestamp check + financials CSV mtime check"
            ),
            "last_updated": generated_at,
            "note": "Data quality alerts are source-review prompts, not trading recommendations.",
        }
    )
    evidence.append(
        {
            "claim_key": "portfolio.income_quality",
            "source_type": "user_holding",
            "source_ref": "holdings income fields and EDINET dividend facts",
            "metric_key": "income_quality",
            "formula": (
                "flag missing income sources, negative user income inputs, "
                f"or income_yield_pct >= {_HIGH_INCOME_YIELD_PCT}%"
            ),
            "last_updated": generated_at,
            "note": "Income quality alerts are data review prompts, not trading recommendations.",
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
    holding: InvestmentHolding,
    company: dict[str, object] | None,
    *,
    current_yield: CurrentYieldFact | None = None,
) -> tuple[float, str]:
    if holding.annual_income is not None:
        return max(holding.annual_income, 0.0), "user_annual_income"
    if holding.distribution_per_unit is not None:
        return max(holding.distribution_per_unit, 0.0) * holding.quantity, "user_distribution"
    if (
        holding.asset_type == "stock"
        and current_yield is not None
        and current_yield.current_dividend_per_share is not None
    ):
        return (
            current_yield.current_dividend_per_share * holding.quantity,
            "current_dividend_per_share",
        )
    if holding.asset_type == "stock" and company is not None:
        dps = _number(company.get("latest_dividend_per_share"))
        if dps is not None:
            return dps * holding.quantity, "edinet_latest_dividend_per_share"
    return 0.0, "not_available"


def _income_source_ref(
    *,
    income_source: str,
    holding: InvestmentHolding,
    financials_csv: str | Path,
    current_yield: CurrentYieldFact | None,
) -> str:
    if income_source == "edinet_latest_dividend_per_share":
        return str(financials_csv)
    if income_source == "current_dividend_per_share" and current_yield is not None:
        return current_yield.source_ref or current_yield.provider_id
    return holding.source


def _income_formula(income_source: str) -> str:
    if income_source == "current_dividend_per_share":
        return "quantity * current_dividend_per_share"
    if income_source == "edinet_latest_dividend_per_share":
        return "quantity * edinet_latest_dividend_per_share"
    return "quantity * dividend_or_distribution_per_unit"


def _holding_data_alerts(
    *,
    holding: InvestmentHolding,
    generated_at: datetime,
    provider_id: str,
    policy: ProviderPolicy,
) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    base: dict[str, object] = {
        "security_code": holding.ticker_or_fund_code,
        "name": holding.name,
        "asset_type": holding.asset_type,
        "provider_id": provider_id,
    }
    if not policy.production_allowed:
        alerts.append(
            {
                **base,
                "level": "error",
                "code": "provider_not_production_allowed",
                "field": "data_provider",
                "message": policy.license_note,
            }
        )
    if holding.current_price is None:
        alerts.append(
            {
                **base,
                "level": "warn",
                "code": "price_missing_fallback_avg_cost",
                "field": "current_price",
                "message": "Current price is missing; valuation falls back to avg_cost.",
            }
        )
        return alerts

    if not holding.price_as_of:
        alerts.append(
            {
                **base,
                "level": "info",
                "code": "price_as_of_missing",
                "field": "price_as_of",
                "message": "Current price timestamp is missing; freshness cannot be verified.",
            }
        )
        return alerts

    parsed = _parse_timestamp(holding.price_as_of)
    if parsed is None:
        alerts.append(
            {
                **base,
                "level": "warn",
                "code": "price_as_of_invalid",
                "field": "price_as_of",
                "value": holding.price_as_of,
                "message": "Current price timestamp could not be parsed.",
            }
        )
        return alerts

    age_days = (generated_at - parsed).total_seconds() / 86_400
    if age_days < 0:
        alerts.append(
            {
                **base,
                "level": "warn",
                "code": "price_as_of_future",
                "field": "price_as_of",
                "value": holding.price_as_of,
                "message": "Current price timestamp is in the future.",
            }
        )
    elif age_days > _PRICE_STALE_AFTER_DAYS:
        alerts.append(
            {
                **base,
                "level": "warn",
                "code": "price_stale",
                "field": "price_as_of",
                "value": holding.price_as_of,
                "age_days": round(age_days, 1),
                "threshold_days": _PRICE_STALE_AFTER_DAYS,
                "message": "Current price timestamp is older than the freshness threshold.",
            }
        )
    return alerts


def _income_alerts(
    *,
    holding: InvestmentHolding,
    row: Mapping[str, object],
    market_value: float,
    income_source: str,
    yield_reconciliation: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    base: dict[str, object] = {
        "security_code": holding.ticker_or_fund_code,
        "name": holding.name,
        "asset_type": holding.asset_type,
    }
    if holding.annual_income is not None and holding.annual_income < 0:
        alerts.append(
            {
                **base,
                "level": "error",
                "code": "income_negative_input",
                "field": "annual_income",
                "value": round(holding.annual_income, 2),
                "message": "Annual income input is negative and was floored at 0 for calculations.",
            }
        )
    if holding.distribution_per_unit is not None and holding.distribution_per_unit < 0:
        alerts.append(
            {
                **base,
                "level": "error",
                "code": "distribution_negative_input",
                "field": "distribution_per_unit",
                "value": round(holding.distribution_per_unit, 4),
                "message": (
                    "Distribution per unit input is negative and was floored at 0 for calculations."
                ),
            }
        )
    if income_source == "not_available":
        alerts.append(
            {
                **base,
                "level": "info",
                "code": "income_missing",
                "field": "annual_income_estimate",
                "value": 0.0,
                "message": (
                    "No dividend or distribution source was available; income estimate is 0."
                ),
            }
        )
    warnings = yield_reconciliation.get("warnings") if yield_reconciliation is not None else None
    if isinstance(warnings, (tuple, list)) and "edinet_current_basis_review" in warnings:
        alerts.append(
            {
                **base,
                "level": "warn",
                "code": "current_yield_basis_review",
                "field": "annual_income_estimate",
                "value": row.get("annual_income_estimate"),
                "message": (
                    "EDINET dividend is a historical filing value and implies a high "
                    "current yield; add a current dividend/forecast CSV fact before "
                    "using it as current yield."
                ),
            }
        )
    income_yield_pct = _number(row.get("income_yield_pct")) or 0.0
    if market_value > 0 and income_yield_pct >= _HIGH_INCOME_YIELD_PCT:
        alerts.append(
            {
                **base,
                "level": "warn",
                "code": "income_yield_high",
                "field": "income_yield_pct",
                "value": round(income_yield_pct, 2),
                "threshold_pct": _HIGH_INCOME_YIELD_PCT,
                "annual_income_estimate": row.get("annual_income_estimate"),
                "market_value": round(market_value, 2),
                "message": (
                    "Income yield exceeds the review threshold; "
                    "verify source data before relying on it."
                ),
            }
        )
    return alerts


def _financials_metadata(path: str | Path, generated_at: datetime) -> dict[str, object]:
    csv_path = Path(path)
    if not csv_path.exists():
        return {
            "path": str(path),
            "exists": False,
            "last_modified": None,
            "age_days": None,
            "threshold_days": _FINANCIALS_STALE_AFTER_DAYS,
        }
    modified = datetime.fromtimestamp(csv_path.stat().st_mtime, tz=UTC)
    age_days = (generated_at - modified).total_seconds() / 86_400
    return {
        "path": str(path),
        "exists": True,
        "last_modified": modified.isoformat(),
        "age_days": round(age_days, 1),
        "threshold_days": _FINANCIALS_STALE_AFTER_DAYS,
    }


def _financials_alerts(
    *,
    holdings: Sequence[InvestmentHolding],
    metadata: Mapping[str, object],
) -> list[dict[str, object]]:
    if not any(holding.asset_type == "stock" for holding in holdings):
        return []
    if metadata.get("exists") is False:
        return [
            {
                "level": "warn",
                "code": "financials_csv_missing",
                "field": "financials_csv",
                "source_ref": metadata.get("path"),
                "message": "Financials CSV is missing; stock dividend facts may be unavailable.",
            }
        ]
    age_days = _number(metadata.get("age_days"))
    threshold_days = _number(metadata.get("threshold_days")) or _FINANCIALS_STALE_AFTER_DAYS
    if age_days is not None and age_days > threshold_days:
        return [
            {
                "level": "warn",
                "code": "financials_csv_stale",
                "field": "financials_csv",
                "source_ref": metadata.get("path"),
                "last_modified": metadata.get("last_modified"),
                "age_days": age_days,
                "threshold_days": threshold_days,
                "message": "Financials CSV is older than the freshness threshold.",
            }
        ]
    return []


def _data_quality_summary(alerts: Sequence[dict[str, object]]) -> dict[str, object]:
    alert_list = list(alerts)
    codes = [str(alert.get("code") or "") for alert in alert_list]
    levels = {str(alert.get("level") or "") for alert in alert_list}
    status = "ok"
    if "error" in levels:
        status = "error"
    elif "warn" in levels:
        status = "warn"
    elif alert_list:
        status = "info"
    return {
        "status": status,
        "alert_count": len(alert_list),
        "provider_blocked_count": codes.count("provider_not_production_allowed"),
        "missing_price_count": codes.count("price_missing_fallback_avg_cost"),
        "missing_timestamp_count": codes.count("price_as_of_missing"),
        "stale_price_count": codes.count("price_stale"),
        "stale_financials_count": codes.count("financials_csv_stale"),
        "price_stale_after_days": _PRICE_STALE_AFTER_DAYS,
        "financials_stale_after_days": _FINANCIALS_STALE_AFTER_DAYS,
        "alerts": alert_list,
    }


def _income_quality_summary(alerts: Sequence[dict[str, object]]) -> dict[str, object]:
    alert_list = list(alerts)
    codes = [str(alert.get("code") or "") for alert in alert_list]
    levels = {str(alert.get("level") or "") for alert in alert_list}
    status = "ok"
    if "error" in levels:
        status = "error"
    elif "warn" in levels:
        status = "warn"
    elif alert_list:
        status = "info"
    return {
        "status": status,
        "alert_count": len(alert_list),
        "missing_income_count": codes.count("income_missing"),
        "high_yield_count": codes.count("income_yield_high"),
        "negative_input_count": codes.count("income_negative_input")
        + codes.count("distribution_negative_input"),
        "high_yield_threshold_pct": _HIGH_INCOME_YIELD_PCT,
        "alerts": alert_list,
    }


def _holding_provider_id(holding: InvestmentHolding) -> str:
    if holding.data_provider and holding.data_provider.strip():
        return holding.data_provider.strip().lower()
    source = holding.source.strip().lower()
    if not source or _looks_like_path(source):
        return "user_csv"
    return source


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value or value.endswith(".csv") or value.endswith(".json")


def _parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _concentration(rows: list[dict[str, object]], total_market: float) -> dict[str, object]:
    if total_market <= 0:
        return {
            "hhi": 0.0,
            "top3_share_pct": 0.0,
            "top_weight": 0.0,
            "top_code": None,
            "effective_names": 0.0,
        }
    weighted_rows = sorted(
        (
            (
                (_number(row.get("market_value")) or 0.0) / total_market,
                str(row.get("ticker_or_fund_code") or ""),
            )
            for row in rows
        ),
        reverse=True,
    )
    shares = [share for share, _ in weighted_rows]
    hhi = sum(share * share for share in shares)
    return {
        "hhi": round(hhi, 4),
        "top3_share_pct": round(sum(shares[:3]) * 100.0, 2),
        "top_weight": round(shares[0], 4) if shares else 0.0,
        "top_code": weighted_rows[0][1] if weighted_rows else None,
        "effective_names": round(1.0 / hhi, 2) if hhi > 0 else 0.0,
    }


def _share_map(values: dict[str, float], total: float) -> dict[str, dict[str, float]]:
    return {
        key: {
            "value": round(value, 2),
            "share_pct": round(value / total * 100.0, 2) if total else 0.0,
        }
        for key, value in sorted(values.items())
    }


def _nisa_summary(*, nisa_cost: float, nisa_growth_cost: float) -> dict[str, object]:
    lifetime_remaining = max(_NISA_LIFETIME_CAP - nisa_cost, 0.0)
    growth_remaining = max(_NISA_GROWTH_CAP - nisa_growth_cost, 0.0)
    lifetime_usage_pct = nisa_cost / _NISA_LIFETIME_CAP * 100.0
    growth_usage_pct = nisa_growth_cost / _NISA_GROWTH_CAP * 100.0
    alerts = [
        *_nisa_alerts(
            bucket="lifetime",
            used=nisa_cost,
            cap=_NISA_LIFETIME_CAP,
            remaining=lifetime_remaining,
            usage_pct=lifetime_usage_pct,
        ),
        *_nisa_alerts(
            bucket="growth",
            used=nisa_growth_cost,
            cap=_NISA_GROWTH_CAP,
            remaining=growth_remaining,
            usage_pct=growth_usage_pct,
        ),
    ]
    return {
        "used_cost_basis": round(nisa_cost, 2),
        "remaining_lifetime": round(lifetime_remaining, 2),
        "growth_used_cost_basis": round(nisa_growth_cost, 2),
        "growth_remaining": round(growth_remaining, 2),
        "lifetime_cap": _NISA_LIFETIME_CAP,
        "growth_cap": _NISA_GROWTH_CAP,
        "usage_pct": round(lifetime_usage_pct, 2),
        "growth_usage_pct": round(growth_usage_pct, 2),
        "excess_lifetime": round(max(nisa_cost - _NISA_LIFETIME_CAP, 0.0), 2),
        "growth_excess": round(max(nisa_growth_cost - _NISA_GROWTH_CAP, 0.0), 2),
        "status": _nisa_status(lifetime_usage_pct),
        "growth_status": _nisa_status(growth_usage_pct),
        "alerts": alerts,
    }


def _nisa_alerts(
    *,
    bucket: str,
    used: float,
    cap: float,
    remaining: float,
    usage_pct: float,
) -> list[dict[str, object]]:
    if used > cap:
        return [
            {
                "level": "error",
                "code": f"nisa_{bucket}_cap_exceeded",
                "bucket": bucket,
                "used_cost_basis": round(used, 2),
                "cap": cap,
                "remaining": 0.0,
                "excess": round(used - cap, 2),
                "usage_pct": round(usage_pct, 2),
                "message": f"NISA {bucket} cost basis exceeds the configured cap.",
            }
        ]
    if usage_pct >= _NISA_NEAR_LIMIT_PCT:
        return [
            {
                "level": "warn",
                "code": f"nisa_{bucket}_near_limit",
                "bucket": bucket,
                "used_cost_basis": round(used, 2),
                "cap": cap,
                "remaining": round(remaining, 2),
                "excess": 0.0,
                "usage_pct": round(usage_pct, 2),
                "message": f"NISA {bucket} remaining capacity is below 10%.",
            }
        ]
    return []


def _nisa_status(usage_pct: float) -> str:
    if usage_pct > 100.0:
        return "exceeded"
    if usage_pct >= _NISA_NEAR_LIMIT_PCT:
        return "near_limit"
    return "ok"


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
