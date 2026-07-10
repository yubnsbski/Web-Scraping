"""Japanese-equity market mechanics for the v1 paper-trading simulation.

Every rule here follows the tables in ``docs/papertrade-design.md`` ("市場
メカニクス" section), sourced from JPX's published 制限値幅 page, 呼値
(tick) tables, and SBI/楽天's 2026 zero-commission online domestic-stock
pricing. v1 deliberately keeps this simple and conservative rather than
exactly matching every real-market nuance:

- **Tick table**: the *general* (non-TOPIX500) table only -- v1 does not
  determine TOPIX500 membership, so all tickers use the coarser general
  table (conservative: real TOPIX500 ticks are finer, so this never lets a
  fill look more precise than it would in practice).
- **Boundary semantics**: JPX quotation-unit (tick) bands use less-or-equal
  boundaries: 3,000 yen or below uses a 1-yen tick, above 3,000 through
  5,000 uses a 5-yen tick, and so on. The implementation stores those bands
  as exclusive upper bounds because all six boundaries are valid prices under
  both neighboring tick sizes, making the numeric result identical at the
  boundary. JPX price-limit tables use strictly-less boundaries; that
  semantics is correct here and must stay.
- **Order of operations for a fill**: slippage is applied to the raw open
  price first (it approximates the real bid/ask spread impact of a market
  order), then the slipped price is rounded to the nearest valid tick
  (an execution can only occur at a quotable price), and finally the ticked
  price is clamped to the prior close's price-limit band (a real order
  could never execute outside the day's limit-up/limit-down band). See
  :func:`fill_price`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Side = Literal["buy", "sell"]

# --- 呼値 (tick size) table -------------------------------------------------
# (upper_bound_exclusive, tick_size). JPX publishes the quotation-unit table
# with less-or-equal bounds; representing it with exclusive upper bounds is
# numerically identical at the six boundaries because each boundary is a valid
# price under both neighboring tick sizes. Above the last bound,
# TICK_CATCHALL applies (the design doc's table trails off at
# 3,000万円:1,000円, which for the price ranges this dataset ever sees is
# equivalent to "everything above 500,000 uses a 1,000 yen tick").
TICK_TABLE: tuple[tuple[float, int], ...] = (
    (3_000, 1),
    (5_000, 5),
    (30_000, 10),
    (50_000, 50),
    (300_000, 100),
    (500_000, 500),
)
TICK_CATCHALL = 1_000

# --- 値幅制限 (daily price-limit band) table --------------------------------
# (upper_bound_exclusive, half_width). Table implemented through the design
# doc's last enumerated band (150,000円); above that, v1 falls back to a
# +/-20% band rather than enumerating JPX's much coarser high-price bands
# (documented deviation -- see module docstring and design doc's mechanics
# table, which itself trails off after 50,000円 with "...").
_LIMIT_TABLE: tuple[tuple[float, float], ...] = (
    (100, 30),
    (200, 50),
    (500, 80),
    (700, 100),
    (1_000, 150),
    (1_500, 300),
    (2_000, 400),
    (3_000, 500),
    (5_000, 700),
    (7_000, 1_000),
    (10_000, 1_500),
    (15_000, 3_000),
    (20_000, 4_000),
    (30_000, 5_000),
    (50_000, 7_000),
    (70_000, 10_000),
    (100_000, 15_000),
    (150_000, 30_000),
)
_LIMIT_FALLBACK_RATE = 0.20

# 特定口座（源泉徴収あり）の譲渡益・配当課税率 (2026年時点)
CAPITAL_GAINS_TAX_RATE = 0.20315


def _tick_size(price: float) -> int:
    for bound, tick in TICK_TABLE:
        if price < bound:
            return tick
    return TICK_CATCHALL


def round_to_tick(price: float, *, side: Side) -> float:
    """Round ``price`` to the nearest valid 呼値 (tick) for its price band.

    Buys round *up* to the next tick (conservative: never lets a simulated
    buy fill better than a real order could), sells round *down*.
    """

    tick = _tick_size(price)
    quotient = price / tick
    # A tiny epsilon absorbs float representation error (e.g. 600/5 landing on
    # 119.99999999999999) without changing the rounding direction for any
    # genuinely non-boundary price.
    steps = math.ceil(quotient - 1e-9) if side == "buy" else math.floor(quotient + 1e-9)
    return float(steps * tick)


def price_limit_band(reference_price: float) -> tuple[float, float]:
    """The (low, high) 値幅制限 band for a given 基準値段 (reference price)."""

    for bound, width in _LIMIT_TABLE:
        if reference_price < bound:
            return (reference_price - width, reference_price + width)
    width = reference_price * _LIMIT_FALLBACK_RATE
    return (reference_price - width, reference_price + width)


def clamp_to_limit(price: float, reference_price: float) -> tuple[float, bool]:
    """Clamp ``price`` into ``reference_price``'s 値幅制限 band.

    A limit boundary can be off-tick. High-side clamps snap down to the
    nearest valid tick; low-side clamps snap up, so the returned price remains
    quotable without escaping the band.

    Returns ``(clamped_price, was_clamped)``.
    """

    low, high = price_limit_band(reference_price)
    if price < low:
        return (round_to_tick(low, side="buy"), True)
    if price > high:
        return (round_to_tick(high, side="sell"), True)
    return (price, False)


def apply_slippage(price: float, *, side: Side, bps: float = 10) -> float:
    """Apply fixed slippage (basis points) unfavorably: buy up, sell down."""

    factor = bps / 10_000
    if side == "buy":
        return price * (1 + factor)
    return price * (1 - factor)


@dataclass(frozen=True)
class FillPriceResult:
    """Result of simulating one 寄付成行 (market-on-open) fill."""

    price: float
    clamped: bool


def fill_price(
    open_price: float,
    prev_close: float,
    *,
    side: Side,
    slippage_bps: float = 10,
) -> FillPriceResult:
    """Simulate a market-on-open fill price.

    Composition order (see module docstring): slippage -> tick rounding ->
    price-limit clamp against the prior close.
    """

    slipped = apply_slippage(open_price, side=side, bps=slippage_bps)
    ticked = round_to_tick(slipped, side=side)
    clamped_price, was_clamped = clamp_to_limit(ticked, prev_close)
    return FillPriceResult(price=clamped_price, clamped=was_clamped)


def round_lot(shares: float) -> int:
    """Floor ``shares`` down to the nearest 単元 (100-share lot)."""

    return int(shares // 100) * 100


@dataclass(frozen=True)
class CommissionModel:
    """Commission schedule: ``zero`` (default, SBI/楽天 2026) or ``bps``."""

    kind: Literal["zero", "bps"]
    rate: float = 0.0

    @classmethod
    def zero(cls) -> CommissionModel:
        return cls(kind="zero", rate=0.0)

    @classmethod
    def bps(cls, rate: float) -> CommissionModel:
        return cls(kind="bps", rate=rate)


ZERO_COMMISSION = CommissionModel.zero()


def commission(notional: float, model: CommissionModel) -> float:
    """Commission due on a trade of ``notional`` yen under ``model``."""

    if model.kind == "zero":
        return 0.0
    return notional * (model.rate / 10_000)


def round_yen(value: float) -> int:
    """Round a float yen amount to the nearest whole yen (round-half-up).

    Used at every tax-boundary computation so repeated float arithmetic
    never leaves a fractional-yen residue in the ledger.
    """

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class TaxLedger:
    """Simplified 特定口座（源泉徴収あり）損益通算 (loss-offsetting) tax model.

    Tracks *cumulative* realized P/L across the run. On every realized event,
    the tax "due so far" is recomputed as
    ``max(cumulative_pnl, 0) * CAPITAL_GAINS_TAX_RATE``; the delta versus tax
    already withheld is the cash effect of *this* event -- positive means
    additional tax withheld (cash outflow), negative means a refund (cash
    inflow), matching how 損益通算 works within a single 特定口座 over a
    year: a later loss refunds tax already withheld on an earlier gain, and
    the running total tax is always zero once cumulative P/L goes negative.

    ``nisa=True`` makes every event tax-free (NISA 非課税), matching the
    design doc's NISA mode.
    """

    nisa: bool = False
    cumulative_pnl: float = 0.0
    cumulative_tax_withheld: int = 0

    def record_realized_pnl(self, pnl: float) -> int:
        """Apply one realized P/L event; return this event's tax cash delta.

        Positive = tax withheld (subtract from proceeds). Negative = refund
        (add to proceeds). Always 0 under NISA.
        """

        self.cumulative_pnl += pnl
        if self.nisa:
            return 0
        tax_due = round_yen(max(self.cumulative_pnl, 0.0) * CAPITAL_GAINS_TAX_RATE)
        delta = tax_due - self.cumulative_tax_withheld
        self.cumulative_tax_withheld = tax_due
        return delta
