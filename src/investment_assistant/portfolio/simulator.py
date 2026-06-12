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
    "機械的な試算で、配当はボリンジャー下限で安全側に見積もっています。税引後は"
    "源泉徴収20.315%の概算（配当控除・総合課税等は未考慮、NISAは非課税扱い）です。"
    "将来を保証しない参考値です。"
)

_AUTO_WEIGHT_MODES = ("equal", "safety", "amount", "shares")
_OPTIMIZATION_MODES = ("none", "cash_min", "dividend_max", "balanced")
_BAND_K = 2.0

# Japanese listed-stock dividend withholding: 15.315% income + 5% resident tax.
# Mechanical approximation only — ignores 配当控除/総合課税 elections. NISA = 0%.
DIVIDEND_TAX_RATE = 0.20315

# Cap on the cash_min knapsack table (cells = reduced_budget × holdings) so an
# adversarial budget can never make the exact fill blow up; above it we fall back
# to a greedy fill.
_KNAPSACK_CELL_CAP = 4_000_000

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
    shares_fixed: float
    amount_fixed: float
    nisa: bool


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
    optimization: str = "none",
    dividend_basis: str = "conservative",
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    lot_default: int = 100,
) -> dict[str, object]:
    """Build a portfolio and project dividend income (conservative by default).

    ``optimization`` chooses how a *budget* is turned into integer lots when the
    weighting is not per-holding fixed (``amount`` / ``shares``):

    - ``none`` – split the budget by ``auto_weight`` and floor each to lots.
    - ``cash_min`` – minimise leftover cash (knapsack fill of the budget).
    - ``dividend_max`` – maximise annual dividend (buy best dividend-per-yen lots).
    - ``balanced`` – maximise dividend-per-yen weighted by each name's safety.
    """

    budget = max(0.0, float(budget))
    mode, optimize, basis, years = _normalize(auto_weight, optimization, dividend_basis, years)
    prepared = _prepare_universe(holdings, financials_csv, lot_default)
    if not prepared:
        return _unavailable()

    weights = _resolve_weights(prepared, mode)
    shares_list = _resolve_shares(prepared, weights, budget, mode, optimize, basis)
    allocations = _allocate(prepared, weights, shares_list, basis)

    return _build_result(
        allocations,
        budget=budget,
        years=years,
        growth_rate=float(growth_rate),
        reinvest=reinvest,
        mode=mode,
        optimize=optimize,
        basis=basis,
    )


def plan_for_target_dividend(
    *,
    target_annual_dividend: float,
    holdings: list[dict[str, object]],
    years: int = 10,
    reinvest: bool = True,
    growth_rate: float = 0.0,
    auto_weight: str = "equal",
    optimization: str = "none",
    dividend_basis: str = "conservative",
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    lot_default: int = 100,
    net_target: bool = False,
) -> dict[str, object]:
    """Reverse the simulator: find the budget that yields a target annual income.

    Buys whole lots until the (conservative by default) annual dividend reaches
    ``target_annual_dividend`` and reports the required budget. ``optimization``
    of ``dividend_max`` / ``balanced`` reaches the target with the *least* budget
    (best dividend-per-yen first); otherwise lots are spread round-robin across
    the holdings for diversification.

    ``net_target`` interprets the target as *after-tax* (手取り) income: taxable
    holdings count their dividend net of ``DIVIDEND_TAX_RATE``, NISA holdings
    count in full.
    """

    target = max(0.0, float(target_annual_dividend))
    mode, optimize, basis, years = _normalize(auto_weight, optimization, dividend_basis, years)
    prepared = _prepare_universe(holdings, financials_csv, lot_default)
    if not prepared:
        return _unavailable()

    shares_list, reachable = _target_shares(prepared, target, optimize, basis, net=net_target)
    invested = sum(shares * h.price for shares, h in zip(shares_list, prepared, strict=True))
    # Display weights reflect the realised allocation by invested amount.
    weights = [
        (shares * h.price / invested) if invested > 0 else 0.0
        for shares, h in zip(shares_list, prepared, strict=True)
    ]
    allocations = _allocate(prepared, weights, shares_list, basis)

    result = _build_result(
        allocations,
        budget=invested,  # required budget == invested (no leftover cash)
        years=years,
        growth_rate=float(growth_rate),
        reinvest=reinvest,
        mode=mode,
        optimize=optimize,
        basis=basis,
    )
    achieved = sum(_num(a["annual_dividend"]) for a in allocations)
    achieved_net = sum(_num(a["annual_dividend_net"]) for a in allocations)
    result["target"] = {
        "target_annual_dividend": round(target),
        "achieved_annual_dividend": round(achieved),
        "achieved_annual_dividend_net": round(achieved_net),
        "net_target": net_target,
        "required_budget": round(invested),
        "reachable": reachable,
    }
    if not reachable:
        result["hint"] = (
            "選択銘柄の保守的配当では目標に到達できません（配当データ不足の可能性）。"
            "銘柄を増やすか、目標額を下げてください。"
        )
    return result


def _target_shares(
    prepared: list[_Prepared], target: float, optimize: str, basis: str, *, net: bool = False
) -> tuple[list[int], bool]:
    """Greedily buy lots until the annual dividend (net if ``net``) reaches ``target``."""

    shares = [0 for _ in prepared]
    if target <= 0:
        return shares, True
    lot_dividend = [
        h.lot
        * (h.dps_conservative if basis == "conservative" else h.dps_latest)
        * ((1.0 if h.nisa else 1.0 - DIVIDEND_TAX_RATE) if net else 1.0)
        for h in prepared
    ]
    eligible = [i for i, div in enumerate(lot_dividend) if div > 0 and prepared[i].price > 0]
    if not eligible:
        return shares, False

    smallest = min(lot_dividend[i] for i in eligible)
    cap = min(int(target / smallest) + len(prepared) + 1, 500_000)
    achieved = 0.0
    rotation = 0
    for _ in range(cap):
        if achieved >= target:
            break
        if optimize in ("dividend_max", "balanced"):
            pick = max(eligible, key=lambda i: (_lot_score(prepared[i], optimize, basis)))
        else:
            pick = eligible[rotation % len(eligible)]
            rotation += 1
        shares[pick] += prepared[pick].lot
        achieved += lot_dividend[pick]
    return shares, achieved >= target


def _concentration(allocations: list[dict[str, object]]) -> dict[str, object]:
    """Mechanical concentration metrics over invested amounts (non-advisory)."""

    invested = [_num(a["invested"]) for a in allocations]
    total = sum(invested)
    if total <= 0:
        return {"top_weight": 0.0, "top_ticker": None, "hhi": 0.0, "effective_names": 0.0}
    weights = [value / total for value in invested]
    top_index = max(range(len(weights)), key=lambda i: weights[i])
    hhi = sum(weight**2 for weight in weights)
    return {
        "top_weight": round(weights[top_index], 4),
        "top_ticker": allocations[top_index].get("ticker"),
        "hhi": round(hhi, 4),
        # Inverse-HHI ≈ number of equally-weighted names the mix behaves like.
        "effective_names": round(1.0 / hhi, 2) if hhi > 0 else 0.0,
    }


def _build_result(
    allocations: list[dict[str, object]],
    *,
    budget: float,
    years: int,
    growth_rate: float,
    reinvest: bool,
    mode: str,
    optimize: str,
    basis: str,
) -> dict[str, object]:
    invested = sum(_num(a["invested"]) for a in allocations)
    annual = sum(_num(a["annual_dividend"]) for a in allocations)
    annual_net = sum(_num(a["annual_dividend_net"]) for a in allocations)
    tax = sum(_num(a["dividend_tax"]) for a in allocations)
    annual_latest = sum(_num(a["annual_dividend_latest"]) for a in allocations)
    band_lower = sum(_num(a["annual_band_lower"]) for a in allocations)
    band_upper = sum(_num(a["annual_band_upper"]) for a in allocations)
    concentration = _concentration(allocations)

    summary: dict[str, object] = {
        "budget": round(budget),
        "invested": round(invested),
        "cash_left": round(budget - invested),
        "annual_dividend": round(annual),
        "annual_dividend_net": round(annual_net),
        "dividend_tax": round(tax),
        "tax_rate": DIVIDEND_TAX_RATE,
        "annual_dividend_latest": round(annual_latest),
        "annual_band_lower": round(band_lower),
        "annual_band_upper": round(band_upper),
        "portfolio_yield": round(annual / invested, 4) if invested > 0 else 0.0,
        "portfolio_yield_net": round(annual_net / invested, 4) if invested > 0 else 0.0,
        "portfolio_yield_latest": round(annual_latest / invested, 4) if invested > 0 else 0.0,
        "holdings": len(allocations),
        "dividend_basis": basis,
        "optimization": optimize,
        "concentration": concentration,
    }
    return {
        "available": True,
        "weight_mode": mode,
        "optimization": optimize,
        "allocations": allocations,
        "summary": summary,
        "projection": _project(
            annual=annual,
            annual_net=annual_net,
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


def _normalize(
    auto_weight: str, optimization: str, dividend_basis: str, years: int
) -> tuple[str, str, str, int]:
    """Validate the strategy knobs shared by both simulator entry points."""

    mode = auto_weight if auto_weight in _AUTO_WEIGHT_MODES else "equal"
    optimize = optimization if optimization in _OPTIMIZATION_MODES else "none"
    basis = "latest" if dividend_basis == "latest" else "conservative"
    return mode, optimize, basis, max(1, min(int(years), 50))


def _prepare_universe(
    holdings: list[dict[str, object]], financials_csv: str | Path, lot_default: int
) -> list[_Prepared]:
    """Load financials and build priced holdings, dropping any without a price."""

    by_ticker = _index_companies(load_comparison(financials_csv))
    prepared = [_prepare_holding(h, by_ticker, lot_default) for h in holdings]
    return [h for h in prepared if h.price > 0]


def _unavailable() -> dict[str, object]:
    return {
        "available": False,
        "hint": "有効な銘柄（ticker と price>0）を1件以上入力してください。",
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
        shares_fixed=_num(holding.get("shares")),
        amount_fixed=_num(holding.get("amount")),
        nisa=bool(holding.get("nisa")),
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


def _resolve_shares(
    prepared: list[_Prepared],
    weights: list[float],
    budget: float,
    mode: str,
    optimize: str,
    basis: str,
) -> list[int]:
    """Compute integer share counts per holding for the chosen strategy."""

    if mode == "shares":
        return [max(0, round(h.shares_fixed / h.lot)) * h.lot if h.lot else 0 for h in prepared]
    if mode == "amount":
        return [
            (math.floor(h.amount_fixed / (h.price * h.lot)) if h.price * h.lot > 0 else 0) * h.lot
            for h in prepared
        ]
    if optimize != "none":
        return _optimize_shares(prepared, budget, optimize, basis)
    # Default: split the budget by weight and floor each holding to whole lots.
    return _weighted_floor_shares(prepared, weights, budget)


def _weighted_floor_shares(
    prepared: list[_Prepared], weights: list[float], budget: float
) -> list[int]:
    """Split ``budget`` by ``weights`` and floor each holding to whole lots."""

    shares: list[int] = []
    for holding, weight in zip(prepared, weights, strict=True):
        lot_cost = holding.price * holding.lot
        lots = math.floor((budget * weight) / lot_cost) if lot_cost > 0 else 0
        shares.append(lots * holding.lot)
    return shares


def _lot_score(holding: _Prepared, optimize: str, basis: str) -> float:
    """Per-yen desirability of one lot under dividend_max / balanced."""

    lot_cost = holding.price * holding.lot
    if lot_cost <= 0:
        return 0.0
    dps = holding.dps_conservative if basis == "conservative" else holding.dps_latest
    per_yen = (holding.lot * dps) / lot_cost
    if optimize == "balanced":
        return per_yen * max(holding.safety, 0.0)
    return per_yen  # dividend_max


def _optimize_shares(
    prepared: list[_Prepared], budget: float, optimize: str, basis: str
) -> list[int]:
    lot_costs = [h.price * h.lot for h in prepared]
    if optimize == "cash_min":
        return _cash_min_shares(prepared, lot_costs, budget)
    # dividend_max / balanced: greedily buy the best-scoring affordable lot.
    shares = [0 for _ in prepared]
    remaining = budget
    scores = [_lot_score(h, optimize, basis) for h in prepared]
    if max(scores, default=0.0) <= 0.0:
        # No holding has a positive (conservative) dividend to maximise — e.g.
        # every band lower clamped to 0. Deploy the budget evenly instead of
        # returning an empty portfolio.
        equal = [1.0 / len(prepared) for _ in prepared] if prepared else []
        return _weighted_floor_shares(prepared, equal, budget)
    while True:
        affordable = [
            i for i, cost in enumerate(lot_costs) if 0 < cost <= remaining and scores[i] > 0
        ]
        if not affordable:
            break
        pick = max(affordable, key=lambda i: (scores[i], -lot_costs[i]))
        shares[pick] += prepared[pick].lot
        remaining -= lot_costs[pick]
    return shares


def _cash_min_shares(
    prepared: list[_Prepared], lot_costs: list[float], budget: float
) -> list[int]:
    """Minimise leftover cash via an unbounded knapsack over lot costs.

    Lots cost ``price × lot`` (whole yen here), so the table is reduced by the
    gcd of the costs and budget before filling; above a cell cap we fall back to a
    largest-fit-then-fill greedy so an adversarial budget can't blow up runtime.

    Costs are rounded *up* and the budget *down* so the integer knapsack can
    never select a combination whose real (possibly fractional) cost exceeds the
    budget — i.e. ``cash_left`` stays non-negative even with fractional prices.
    """

    costs = [math.ceil(c) for c in lot_costs]
    budget_int = math.floor(budget)
    positive = [c for c in costs if c > 0]
    if not positive or budget_int < min(positive):
        return [0 for _ in prepared]

    divisor = budget_int
    for cost in positive:
        divisor = math.gcd(divisor, cost)
    divisor = max(divisor, 1)
    reduced_budget = budget_int // divisor
    reduced_costs = [c // divisor for c in costs]

    if reduced_budget * len(prepared) > _KNAPSACK_CELL_CAP:
        return _greedy_fill_shares(prepared, costs, budget_int)

    best = [0] * (reduced_budget + 1)
    choice = [-1] * (reduced_budget + 1)
    for cap in range(1, reduced_budget + 1):
        for i, cost in enumerate(reduced_costs):
            if 0 < cost <= cap and best[cap - cost] + cost > best[cap]:
                best[cap] = best[cap - cost] + cost
                choice[cap] = i
    shares = [0 for _ in prepared]
    cap = reduced_budget
    while cap > 0 and choice[cap] != -1:
        i = choice[cap]
        shares[i] += prepared[i].lot
        cap -= reduced_costs[i]
    return shares


def _greedy_fill_shares(
    prepared: list[_Prepared], costs: list[int], budget: int
) -> list[int]:
    """Fallback cash_min: buy the most expensive lot that still fits, repeat."""

    shares = [0 for _ in prepared]
    remaining = budget
    while True:
        affordable = [i for i, cost in enumerate(costs) if 0 < cost <= remaining]
        if not affordable:
            break
        pick = max(affordable, key=lambda i: costs[i])
        shares[pick] += prepared[pick].lot
        remaining -= costs[pick]
    return shares


def _allocate(
    prepared: list[_Prepared],
    weights: list[float],
    shares_list: list[int],
    basis: str,
) -> list[dict[str, object]]:
    allocations: list[dict[str, object]] = []
    for holding, weight, shares in zip(prepared, weights, shares_list, strict=True):
        invested = shares * holding.price
        dps = holding.dps_conservative if basis == "conservative" else holding.dps_latest
        annual = shares * dps
        annual_latest = shares * holding.dps_latest
        tax = 0.0 if holding.nisa else annual * DIVIDEND_TAX_RATE
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
                "annual_dividend_net": round(annual - tax),
                "dividend_tax": round(tax),
                "nisa": holding.nisa,
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
    annual_net: float | None = None,
) -> dict[str, object]:
    yield_safe = (annual / invested) if invested > 0 else 0.0
    net = annual if annual_net is None else annual_net
    nominal: list[int] = []
    conservative: list[int] = []
    conservative_net: list[int] = []
    reinvested: list[int] = []
    lower: list[int] = []
    upper: list[int] = []
    income = annual
    for year in range(0, years + 1):
        factor = (1 + growth_rate) ** year
        nominal.append(round(annual_latest * factor))
        conservative.append(round(annual * factor))
        conservative_net.append(round(net * factor))
        lower.append(round(band_lower * factor))
        upper.append(round(band_upper * factor))
        reinvested.append(round(income))
        income = income * (1 + (yield_safe if reinvest else 0.0) + growth_rate)
    return {
        "years": list(range(0, years + 1)),
        "nominal": nominal,
        "conservative": conservative,
        "conservative_net": conservative_net,
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
