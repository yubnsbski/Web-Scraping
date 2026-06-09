"""Dividend-portfolio simulator (non-advisory prototype).

Turn a budget + a list of stocks (ticker + price) into a finished portfolio:
allocate whole 100-share lots by weight, compute annual dividend income and
yield, estimate a dividend-cut haircut from EDINET financials, and project the
income forward (nominal / cut-adjusted / reinvested snowball). Also returns a
years × yield surface for a "3D-style" heatmap.

Pure arithmetic on user-supplied prices and EDINET dividends. No market data, no
LLM, no buy/sell recommendation — projections are illustrative only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV, load_comparison

DISCLAIMER = (
    "これは投資助言ではありません。ユーザー入力の株価とEDINET由来の配当を用いた"
    "機械的な試算であり、将来の配当・減配・価格を保証しません。参考値です。"
)

# Expected dividend haircut by signal (illustrative — not a probability model).
_TREND_HAIRCUT: dict[str, float] = {
    "increasing": 0.0,
    "flat": 0.03,
    "mixed": 0.08,
    "declining": 0.15,
    "insufficient": 0.05,
}
_AUTO_WEIGHT_MODES = ("manual", "equal", "yield", "safety")


@dataclass
class _Prepared:
    ticker: str
    name: str
    price: float
    dividend_per_share: float
    lot: int
    haircut: float
    weight_hint: float
    dividend_yield: float
    safety: float


def estimate_haircut(company: dict[str, object] | None) -> float:
    """Estimate an expected dividend haircut (0..0.5) from financials signals."""

    if not company:
        return 0.05
    trend = str(company.get("dividend_trend") or "insufficient")
    haircut = _TREND_HAIRCUT.get(trend, 0.05)
    cuts = company.get("dividend_cut_years")
    haircut += min(len(cuts), 3) * 0.05 if isinstance(cuts, list) else 0.0
    equity = company.get("latest_equity_ratio")
    if isinstance(equity, (int, float)) and not isinstance(equity, bool) and equity < 20:
        haircut += 0.05
    if str(company.get("operating_cf_trend") or "") == "declining":
        haircut += 0.05
    return round(min(max(haircut, 0.0), 0.5), 4)


def simulate_portfolio(
    *,
    budget: float,
    holdings: list[dict[str, object]],
    years: int = 10,
    reinvest: bool = True,
    growth_rate: float = 0.0,
    auto_weight: str = "manual",
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    lot_default: int = 100,
) -> dict[str, object]:
    """Build a portfolio from a budget and produce income projections."""

    budget = max(0.0, float(budget))
    years = max(1, min(int(years), 50))
    mode = auto_weight if auto_weight in _AUTO_WEIGHT_MODES else "manual"
    by_ticker = _index_companies(load_comparison(financials_csv))

    prepared = [_prepare_holding(h, by_ticker, lot_default) for h in holdings]
    prepared = [h for h in prepared if h.price > 0]
    if not prepared:
        return {
            "available": False,
            "hint": "有効な銘柄（ticker と price>0）を1件以上入力してください。",
            "disclaimer": DISCLAIMER,
        }

    weights = _resolve_weights(prepared, mode)
    allocations = _allocate(prepared, weights, budget)

    invested = sum(_num(a["invested"]) for a in allocations)
    annual = sum(_num(a["annual_dividend"]) for a in allocations)
    annual_adj = sum(_num(a["annual_dividend_adjusted"]) for a in allocations)
    portfolio_yield = annual / invested if invested > 0 else 0.0
    yield_adj = annual_adj / invested if invested > 0 else 0.0

    summary: dict[str, object] = {
        "budget": round(budget),
        "invested": round(invested),
        "cash_left": round(budget - invested),
        "annual_dividend": round(annual),
        "annual_dividend_adjusted": round(annual_adj),
        "portfolio_yield": round(portfolio_yield, 4),
        "portfolio_yield_adjusted": round(yield_adj, 4),
        "holdings": len(allocations),
    }
    return {
        "available": True,
        "weight_mode": mode,
        "allocations": allocations,
        "summary": summary,
        "projection": _project(
            annual=annual,
            annual_adj=annual_adj,
            invested=invested,
            years=years,
            growth_rate=float(growth_rate),
            reinvest=reinvest,
        ),
        "surface": _surface(budget, years),
        "disclaimer": DISCLAIMER,
    }


def _index_companies(comparison: dict[str, object] | None) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    if not comparison:
        return out
    companies = comparison.get("companies")
    if isinstance(companies, list):
        for company in companies:
            if isinstance(company, dict):
                ticker = str(company.get("ticker") or "").strip()
                if ticker:
                    out[ticker] = company
    return out


def _prepare_holding(
    holding: dict[str, object], by_ticker: dict[str, dict[str, object]], lot_default: int
) -> _Prepared:
    ticker = str(holding.get("ticker") or "").strip()
    company = by_ticker.get(ticker)
    price = _num(holding.get("price"))
    dps_raw = holding.get("dividend_per_share")
    if dps_raw is not None:
        dps = _num(dps_raw)
    else:
        dps = _num((company or {}).get("latest_dividend_per_share"))
    name = str(holding.get("name") or (company or {}).get("name") or "")
    lot = int(_num(holding.get("lot"))) or lot_default
    return _Prepared(
        ticker=ticker,
        name=name,
        price=price,
        dividend_per_share=dps,
        lot=lot,
        haircut=estimate_haircut(company),
        weight_hint=_num(holding.get("weight")),
        dividend_yield=(dps / price) if price > 0 else 0.0,
        safety=1.0 - estimate_haircut(company),
    )


def _resolve_weights(prepared: list[_Prepared], mode: str) -> list[float]:
    if mode == "equal":
        raw = [1.0 for _ in prepared]
    elif mode == "yield":
        raw = [max(h.dividend_yield, 0.0) for h in prepared]
    elif mode == "safety":
        raw = [max(h.safety, 0.0) for h in prepared]
    else:  # manual (fall back to equal if no hints provided)
        raw = [max(h.weight_hint, 0.0) for h in prepared]
    total = sum(raw)
    if total <= 0:
        return [1.0 / len(prepared) for _ in prepared]
    return [value / total for value in raw]


def _allocate(
    prepared: list[_Prepared], weights: list[float], budget: float
) -> list[dict[str, object]]:
    allocations: list[dict[str, object]] = []
    for holding, weight in zip(prepared, weights, strict=True):
        lot_cost = holding.price * holding.lot
        lots = math.floor((budget * weight) / lot_cost) if lot_cost > 0 else 0
        shares = lots * holding.lot
        invested = shares * holding.price
        annual = shares * holding.dividend_per_share
        annual_adj = annual * (1.0 - holding.haircut)
        allocations.append(
            {
                "ticker": holding.ticker,
                "name": holding.name,
                "price": round(holding.price),
                "weight": round(weight, 4),
                "shares": shares,
                "invested": round(invested),
                "dividend_per_share": holding.dividend_per_share,
                "annual_dividend": round(annual),
                "annual_dividend_adjusted": round(annual_adj),
                "yield": round((annual / invested) if invested > 0 else 0.0, 4),
                "haircut": round(holding.haircut, 4),
            }
        )
    return allocations


def _project(
    *,
    annual: float,
    annual_adj: float,
    invested: float,
    years: int,
    growth_rate: float,
    reinvest: bool,
) -> dict[str, object]:
    yield_adj = (annual_adj / invested) if invested > 0 else 0.0
    nominal: list[int] = []
    adjusted: list[int] = []
    reinvested: list[int] = []
    cumulative: list[int] = []
    cum = 0.0
    income = annual_adj
    for year in range(0, years + 1):
        nominal.append(round(annual * (1 + growth_rate) ** year))
        adjusted.append(round(annual_adj * (1 + growth_rate) ** year))
        reinvested.append(round(income))
        cum += income
        cumulative.append(round(cum))
        # Reinvest dividends -> next year's income compounds (snowball).
        income = income * (1 + (yield_adj if reinvest else 0.0) + growth_rate)
    return {
        "years": list(range(0, years + 1)),
        "nominal": nominal,
        "adjusted": adjusted,
        "reinvested": reinvested,
        "cumulative_reinvested": cumulative,
        "reinvest": reinvest,
        "growth_rate": round(growth_rate, 4),
    }


def _surface(budget: float, years: int) -> dict[str, object]:
    """years × yield grid of cumulative reinvested dividends (for a heatmap)."""

    yields = [round(0.01 * step, 2) for step in range(1, 9)]  # 1%..8%
    year_axis = list(range(1, years + 1))
    grid: list[list[int]] = []
    for y in yields:
        grid.append([round(budget * ((1 + y) ** year - 1)) for year in year_axis])
    return {"yields": yields, "years": year_axis, "z": grid}


def _num(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return 0.0
    return 0.0
