"""Independent recomputation of the dividend-simulator math.

Recomputes every figure with plain formulas (no simulator imports for the
expected side) and diffs them against the library output. Exits non-zero on any
mismatch. Run: python scripts/verify_simulator_math.py
"""

from __future__ import annotations

import math
import sys

from investment_assistant.financials.models import equity_ratio_to_percent
from investment_assistant.portfolio.simulator import (
    DIVIDEND_TAX_RATE,
    dividend_band,
    plan_for_target_dividend,
    simulate_portfolio,
)

NO_CSV = "/nonexistent/financials.csv"
FAILURES: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK ' if ok else 'NG '} {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        FAILURES.append(label)


def main() -> int:
    # --- 1. Bollinger band, by hand -------------------------------------
    series = [30.0, 40.0, 50.0]
    mean = sum(series) / 3  # 40
    var = sum((v - mean) ** 2 for v in series) / 3  # population variance
    std = var**0.5
    band = dividend_band(series)
    assert band is not None
    check("band.mean", band["mean"], round(mean, 2))
    check("band.std", band["std"], round(std, 2))
    check("band.lower = mean-2σ", band["lower"], round(max(mean - 2 * std, 0.0), 2))
    check("band.upper = mean+2σ", band["upper"], round(mean + 2 * std, 2))

    # --- 2. equity ratio normalisation ----------------------------------
    check("equity 0.766 -> %", equity_ratio_to_percent(0.766), 76.6)
    check("equity 62.3 stays", equity_ratio_to_percent(62.3), 62.3)
    check("equity idempotent", equity_ratio_to_percent(equity_ratio_to_percent(0.5)), 50.0)

    # --- 3. equal-weight budget allocation, by hand ---------------------
    # budget 1,000,000, two names, price 1000/2000, lot 100.
    budget = 1_000_000.0
    half = budget / 2
    exp_shares_a = math.floor(half / (1000 * 100)) * 100  # 500
    exp_shares_b = math.floor(half / (2000 * 100)) * 100  # 200
    out = simulate_portfolio(
        budget=budget,
        holdings=[
            {"ticker": "A", "price": 1000, "dividend_per_share": 40},
            {"ticker": "B", "price": 2000, "dividend_per_share": 50},
        ],
        auto_weight="equal",
        dividend_basis="latest",
        financials_csv=NO_CSV,
    )
    allocs = {a["ticker"]: a for a in out["allocations"]}  # type: ignore[union-attr]
    check("equal A shares", allocs["A"]["shares"], exp_shares_a)
    check("equal B shares", allocs["B"]["shares"], exp_shares_b)
    invested = exp_shares_a * 1000 + exp_shares_b * 2000
    annual = exp_shares_a * 40 + exp_shares_b * 50
    s = out["summary"]
    check("invested", s["invested"], invested)  # type: ignore[index]
    check("cash_left", s["cash_left"], round(budget - invested))  # type: ignore[index]
    check("annual_dividend", s["annual_dividend"], annual)  # type: ignore[index]
    check("portfolio_yield", s["portfolio_yield"], round(annual / invested, 4))  # type: ignore[index]

    # tax: both taxable -> net = annual − tax per holding (rounded per holding)
    tax_a = round(exp_shares_a * 40 * DIVIDEND_TAX_RATE)
    tax_b = round(exp_shares_b * 50 * DIVIDEND_TAX_RATE)
    check("dividend_tax", s["dividend_tax"], tax_a + tax_b)  # type: ignore[index]
    check(
        "annual_dividend_net",
        s["annual_dividend_net"],  # type: ignore[index]
        round(exp_shares_a * 40 - exp_shares_a * 40 * DIVIDEND_TAX_RATE)
        + round(exp_shares_b * 50 - exp_shares_b * 50 * DIVIDEND_TAX_RATE),
    )

    # concentration, by hand: weights by invested
    w_a = exp_shares_a * 1000 / invested
    w_b = exp_shares_b * 2000 / invested
    hhi = w_a**2 + w_b**2
    conc = s["concentration"]  # type: ignore[index]
    check("hhi", conc["hhi"], round(hhi, 4))
    check("effective_names", conc["effective_names"], round(1 / hhi, 2))
    check("top_weight", conc["top_weight"], round(max(w_a, w_b), 4))

    # projection year N = annual × (1+g)^N ; reinvested compounds by yield+g
    growth = 0.02
    out_g = simulate_portfolio(
        budget=budget,
        holdings=[{"ticker": "A", "price": 1000, "dividend_per_share": 40}],
        growth_rate=growth,
        dividend_basis="latest",
        financials_csv=NO_CSV,
        years=10,
    )
    proj = out_g["projection"]
    annual_a = 1000 * 40  # 1000 shares (whole budget, one name)
    check("proj conservative[5]", proj["conservative"][5], round(annual_a * 1.02**5))  # type: ignore[index]
    y = annual_a / 1_000_000
    income = float(annual_a)
    series_exp = []
    for _ in range(0, 11):
        series_exp.append(round(income))
        income *= 1 + y + growth
    check("proj reinvested[10]", proj["reinvested"][10], series_exp[10])  # type: ignore[index]
    check(
        "proj net[3]",
        proj["conservative_net"][3],  # type: ignore[index]
        round(round(annual_a - annual_a * DIVIDEND_TAX_RATE) * 1.02**3),
    )

    # --- 4. cash_min is truly minimal (brute force) ----------------------
    # budget 1,200,000; lots 700k / 600k. Enumerate all (i,j) combos.
    best_leftover = min(
        1_200_000 - (i * 700_000 + j * 600_000)
        for i in range(0, 2)
        for j in range(0, 3)
        if i * 700_000 + j * 600_000 <= 1_200_000
    )
    out_cm = simulate_portfolio(
        budget=1_200_000,
        holdings=[
            {"ticker": "A", "price": 7000, "dividend_per_share": 100},
            {"ticker": "B", "price": 6000, "dividend_per_share": 100},
        ],
        optimization="cash_min",
        dividend_basis="latest",
        financials_csv=NO_CSV,
    )
    check("cash_min leftover == brute-force min", out_cm["summary"]["cash_left"], best_leftover)  # type: ignore[index]

    # --- 5. net target lots, by hand -------------------------------------
    # dps 40, lot 100 -> net/lot = 4000×(1−rate); lots = ceil(target / net_lot)
    net_lot = 100 * 40 * (1 - DIVIDEND_TAX_RATE)
    target = 20_000
    lots_needed = math.ceil(target / net_lot)
    out_t = plan_for_target_dividend(
        target_annual_dividend=target,
        holdings=[{"ticker": "A", "price": 1000, "dividend_per_share": 40}],
        dividend_basis="latest",
        financials_csv=NO_CSV,
        net_target=True,
    )
    t = out_t["target"]
    check("net-target shares", out_t["allocations"][0]["shares"], lots_needed * 100)  # type: ignore[index]
    check("net-target budget", t["required_budget"], lots_needed * 100 * 1000)  # type: ignore[index]
    check(
        "net-target achieved_net >= target",
        bool(t["achieved_annual_dividend_net"] >= target),  # type: ignore[index]
        True,
    )

    # --- 6. invariants over a random sweep --------------------------------
    import random

    rng = random.Random(42)
    violations = 0
    for _ in range(300):
        names = rng.randint(1, 5)
        holdings = [
            {
                "ticker": f"T{k}",
                "price": rng.choice([500, 1000, 1500, 3000, 7000]),
                "dividend_per_share": rng.choice([0, 10, 25, 40, 80]),
                "nisa": rng.random() < 0.5,
            }
            for k in range(names)
        ]
        b = rng.choice([100_000, 350_000, 1_000_000, 2_345_000])
        for opt in ("none", "cash_min", "dividend_max", "balanced"):
            r = simulate_portfolio(
                budget=b,
                holdings=holdings,
                optimization=opt,
                dividend_basis="latest",
                financials_csv=NO_CSV,
            )
            sm = r["summary"]
            if not (int(str(sm["cash_left"])) >= 0):  # type: ignore[index]
                violations += 1
            if int(str(sm["invested"])) > b:  # type: ignore[index]
                violations += 1
            gross = int(str(sm["annual_dividend"]))  # type: ignore[index]
            net = int(str(sm["annual_dividend_net"]))  # type: ignore[index]
            taxv = int(str(sm["dividend_tax"]))  # type: ignore[index]
            if net > gross or net + taxv != gross:
                violations += 1
    check("random sweep (1200 runs): violations", violations, 0)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} mismatch(es): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
