"""Dividend-portfolio simulator (non-advisory prototype).

Build a portfolio from a budget (or fixed shares / amounts) and project the
annual dividend income forward. To stay on the safe side, the dividend per share
is estimated **conservatively** from each ticker's EDINET dividend history using
a Bollinger-style band (mean - k·σ, lower band), so the income is reverse-derived
from a defensible lower estimate rather than the latest (possibly peak) payout.

Inputs:
- budget + weighting (equal / safety / amount / shares), or
- per-holding fixed ``shares`` or ``amount``.
Prices come from the market-price provider (user input or fetched); dividends
come from EDINET ``financials.csv``. Pure arithmetic — no LLM, no recommendation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV, load_comparison

DISCLAIMER = (
    "これは投資助言ではありません。EDINET由来の配当履歴と市場/入力株価を用いた"
    "機械的な試算で、配当はボリンジャー下限で安全側に見積もっています。将来を"
    "保証しない参考値です。"
)

_AUTO_WEIGHT_MODES = ("equal", "safety", "amount", "shares")
_BAND_K = 2.0

_TREND_HAIRCUT: dict[str, float] = {
    "increasing": 0.0,
    "flat": 0.03,
    "mixed": 0.08,
    "declining": 0.15,
    "insufficient": 0.05,
}


def dividend_band(series: list[float], *, k: float = _BAND_K) -> dict[str, float] | None:
    """Bollinger-style band over a dividend-per-share history (population σ)."""

    values = [float(v) for v in series if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not values:
        return None
    mean = sum(values) / len(values)
    if len(values) < 2:
        flat = round(mean, 2)
        return {"mean": flat, "std": 0.0, "upper": flat, "lower": flat}
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = variance**0.5
    return {
        "mean": round(mean, 2),
        "std": round(std, 2),
        "upper": round(mean + k * std, 2),
        "lower": round(max(mean - k * std, 0.0), 2),
    }


def estimate_safety(company: dict[str, object] | None) -> float:
    """Return a 0..1 dividend-safety score from EDINET signals (1 = safest)."""

    if not company:
        return 0.6
    haircut = _TREND_HAIRCUT.get(str(company.get("dividend_trend") or "insufficient"), 0.05)
    cuts = company.get("dividend_cut_years")
    haircut += min(len(cuts), 3) * 0.05 if isinstance(cuts, list) else 0.0
    equity = company.get("latest_equity_ratio")
    if isinstance(equity, (int, float)) and not isinstance(equity, bool) and equity < 20:
        haircut += 0.05
    if str(company.get("operating_cf_trend") or "") == "declining":
        haircut += 0.05
    return round(1.0 - min(max(haircut, 0.0), 0.5), 4)


@dataclass
class _Prepared:
    ticker: str
    name: str
    price: float
    dps_latest: float
    dps_conservative: float
    band: dict[str, float] | None
    lot: int
    safety: float
    weight_hint: float
    shares_fixed: float
    amount_fixed: float


def build_universe(
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    *,
    prices: dict[str, float] | None = None,
) -> list[dict[str, object]]:
    """List the EDINET universe with current/conservative dividend + safety.

    For the selectable stock list. ``prices`` (ticker -> price) lets yields be
    computed; without prices the yield fields are null.
    """

    prices = prices or {}
    companies = _index_companies(load_comparison(financials_csv))
    rows: list[dict[str, object]] = []
    for ticker, company in sorted(companies.items()):
        series = company.get("dividend_series")
        band = dividend_band(series if isinstance(series, list) else [])
        latest = _num(company.get("latest_dividend_per_share"))
        conservative = band["lower"] if band else latest
        price = _num(prices.get(ticker))
        rows.append(
            {
                "ticker": ticker,
                "name": company.get("name"),
                "price": round(price) if price > 0 else None,
                "dividend_latest": latest,
                "dividend_conservative": conservative,
                "yield_latest": round(latest / price, 4) if price > 0 else None,
                "yield_conservative": round(conservative / price, 4) if price > 0 else None,
                "safety": estimate_safety(company),
                "band": band,
                "periods": len(series) if isinstance(series, list) else 0,
            }
        )
    rows.sort(key=lambda r: (-float(r["safety"]), str(r["ticker"])))  # type: ignore[arg-type]
    return rows


def simulate_portfolio(
    *,
    budget: float,
    holdings: list[dict[str, object]],
    years: int = 10,
    reinvest: bool = True,
    growth_rate: float = 0.0,
    auto_weight: str = "equal",
    dividend_basis: str = "conservative",
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    lot_default: int = 100,
) -> dict[str, object]:
    """Build a portfolio and project dividend income (conservative by default)."""

    budget = max(0.0, float(budget))
    years = max(1, min(int(years), 50))
    mode = auto_weight if auto_weight in _AUTO_WEIGHT_MODES else "equal"
    basis = "latest" if dividend_basis == "latest" else "conservative"
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
    allocations = _allocate(prepared, weights, budget, mode, basis)

    invested = sum(_num(a["invested"]) for a in allocations)
    annual = sum(_num(a["annual_dividend"]) for a in allocations)
    annual_latest = sum(_num(a["annual_dividend_latest"]) for a in allocations)
    band_lower = sum(_num(a["annual_band_lower"]) for a in allocations)
    band_upper = sum(_num(a["annual_band_upper"]) for a in allocations)

    summary: dict[str, object] = {
        "budget": round(budget),
        "invested": round(invested),
        "cash_left": round(budget - invested),
        "annual_dividend": round(annual),
        "annual_dividend_latest": round(annual_latest),
        "annual_band_lower": round(band_lower),
        "annual_band_upper": round(band_upper),
        "portfolio_yield": round(annual / invested, 4) if invested > 0 else 0.0,
        "portfolio_yield_latest": round(annual_latest / invested, 4) if invested > 0 else 0.0,
        "holdings": len(allocations),
        "dividend_basis": basis,
    }
    return {
        "available": True,
        "weight_mode": mode,
        "allocations": allocations,
        "summary": summary,
        "projection": _project(
            annual=annual,
            annual_latest=annual_latest,
            band_lower=band_lower,
            band_upper=band_upper,
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
    if comparison:
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
    series = (company or {}).get("dividend_series")
    band = dividend_band(series if isinstance(series, list) else [])

    override = holding.get("dividend_per_share")
    if override is not None:
        latest = _num(override)
    else:
        latest = _num((company or {}).get("latest_dividend_per_share"))
    conservative = band["lower"] if band else latest
    lot = int(_num(holding.get("lot"))) or lot_default
    return _Prepared(
        ticker=ticker,
        name=str(holding.get("name") or (company or {}).get("name") or ""),
        price=_num(holding.get("price")),
        dps_latest=latest,
        dps_conservative=conservative,
        band=band,
        lot=lot,
        safety=estimate_safety(company),
        weight_hint=_num(holding.get("weight")),
        shares_fixed=_num(holding.get("shares")),
        amount_fixed=_num(holding.get("amount")),
    )


def _resolve_weights(prepared: list[_Prepared], mode: str) -> list[float]:
    if mode == "safety":
        raw = [max(h.safety, 0.0) for h in prepared]
    elif mode in ("amount", "shares"):
        raw = [1.0 for _ in prepared]  # not used; allocation is per-holding fixed
    else:  # equal
        raw = [1.0 for _ in prepared]
    total = sum(raw)
    if total <= 0:
        return [1.0 / len(prepared) for _ in prepared]
    return [value / total for value in raw]


def _allocate(
    prepared: list[_Prepared],
    weights: list[float],
    budget: float,
    mode: str,
    basis: str,
) -> list[dict[str, object]]:
    allocations: list[dict[str, object]] = []
    for holding, weight in zip(prepared, weights, strict=True):
        lot_cost = holding.price * holding.lot
        if mode == "shares":
            lots = round(holding.shares_fixed / holding.lot) if holding.lot else 0
            shares = max(0, lots) * holding.lot
        elif mode == "amount":
            lots = math.floor(holding.amount_fixed / lot_cost) if lot_cost > 0 else 0
            shares = lots * holding.lot
        else:
            shares = (math.floor((budget * weight) / lot_cost) if lot_cost > 0 else 0) * holding.lot

        invested = shares * holding.price
        dps = holding.dps_conservative if basis == "conservative" else holding.dps_latest
        annual = shares * dps
        annual_latest = shares * holding.dps_latest
        band = holding.band or {}
        allocations.append(
            {
                "ticker": holding.ticker,
                "name": holding.name,
                "price": round(holding.price),
                "weight": round(weight, 4),
                "shares": shares,
                "invested": round(invested),
                "dividend_per_share": dps,
                "dividend_per_share_latest": holding.dps_latest,
                "annual_dividend": round(annual),
                "annual_dividend_latest": round(annual_latest),
                "annual_band_lower": round(shares * float(band.get("lower", dps))),
                "annual_band_upper": round(shares * float(band.get("upper", holding.dps_latest))),
                "yield": round((annual / invested) if invested > 0 else 0.0, 4),
                "safety": round(holding.safety, 4),
                "band": holding.band,
            }
        )
    return allocations


def _project(
    *,
    annual: float,
    annual_latest: float,
    band_lower: float,
    band_upper: float,
    invested: float,
    years: int,
    growth_rate: float,
    reinvest: bool,
) -> dict[str, object]:
    yield_safe = (annual / invested) if invested > 0 else 0.0
    nominal: list[int] = []
    conservative: list[int] = []
    reinvested: list[int] = []
    lower: list[int] = []
    upper: list[int] = []
    income = annual
    for year in range(0, years + 1):
        factor = (1 + growth_rate) ** year
        nominal.append(round(annual_latest * factor))
        conservative.append(round(annual * factor))
        lower.append(round(band_lower * factor))
        upper.append(round(band_upper * factor))
        reinvested.append(round(income))
        income = income * (1 + (yield_safe if reinvest else 0.0) + growth_rate)
    return {
        "years": list(range(0, years + 1)),
        "nominal": nominal,
        "conservative": conservative,
        "band_lower": lower,
        "band_upper": upper,
        "reinvested": reinvested,
        "reinvest": reinvest,
        "growth_rate": round(growth_rate, 4),
    }


def _surface(budget: float, years: int) -> dict[str, object]:
    yields = [round(0.01 * step, 2) for step in range(1, 9)]
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
