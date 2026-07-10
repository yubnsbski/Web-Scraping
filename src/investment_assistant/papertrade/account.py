"""Cash + position book-keeping for one paper-trading run.

Cash-only, no shorting, no margin (design doc: "現物のみ。ショート・信用は
実装しない"). Buys move average cost with a simple moving-average update;
sells realize P/L against that average cost, feed the run's
:class:`~investment_assistant.papertrade.mechanics.TaxLedger`, and settle
cash immediately (order-date cash accounting, matching the design doc's v1
choice -- "約定日基準の現金管理" -- while still *recording* the T+2
受渡日 via ``calendar.add_business_days`` for later reporting/audit).

Every order's share count must already be a 単元 (100-share) multiple by the
time it reaches this module; :class:`Account` re-validates that itself
(defense in depth -- an upstream strategy/policy bug producing an odd lot
must never silently corrupt the position book).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from investment_assistant.papertrade.calendar import TradingCalendar
from investment_assistant.papertrade.mechanics import CommissionModel, TaxLedger, commission

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Order:
    """A decided (not yet filled) virtual order."""

    ticker: str
    side: Side
    shares: int
    decision_date: str


@dataclass(frozen=True)
class Fill:
    """A filled order: price, commission, and recorded settlement date."""

    order: Order
    date: str
    price: float
    shares: int
    commission: float
    clamped: bool
    settlement_date: str


@dataclass(frozen=True)
class Position:
    """A held position (moving-average cost basis)."""

    ticker: str
    shares: int
    avg_cost: float


@dataclass(frozen=True)
class OrderResult:
    """Outcome of :meth:`Account.execute_buy` / :meth:`Account.execute_sell`.

    ``fill`` is ``None`` on rejection, with ``reason`` set to a short
    machine-readable code (``"insufficient_cash"`` or ``"oversell"``) rather
    than raising -- a rejected order is an expected, routine outcome for a
    strategy layer to handle (e.g. skip and try the next candidate), unlike
    a malformed order (non-lot shares, wrong side), which *does* raise
    ``ValueError`` since that indicates a programming error upstream.
    """

    fill: Fill | None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.fill is not None


class Account:
    """One run's cash + position book. No shorting, no margin."""

    def __init__(self, *, cash: float, tax_ledger: TaxLedger | None = None) -> None:
        self.cash = cash
        self.positions: dict[str, Position] = {}
        self.tax_ledger = tax_ledger if tax_ledger is not None else TaxLedger()
        self.realized_pnl: float = 0.0

    @staticmethod
    def _check_lot(order: Order) -> None:
        if order.shares <= 0 or order.shares % 100 != 0:
            raise ValueError(
                f"order shares must be a positive multiple of 100 (単元), got {order.shares}"
            )

    def execute_buy(
        self,
        order: Order,
        price: float,
        date: str,
        calendar: TradingCalendar,
        commission_model: CommissionModel,
        *,
        clamped: bool = False,
    ) -> OrderResult:
        """Execute a buy fill: cash check, moving-average cost update, T+2 record."""

        if order.side != "buy":
            raise ValueError(f"execute_buy requires a buy order, got side={order.side!r}")
        self._check_lot(order)

        notional = price * order.shares
        fee = commission(notional, commission_model)
        total_cost = notional + fee
        if total_cost > self.cash:
            return OrderResult(fill=None, reason="insufficient_cash")

        settlement_date = calendar.add_business_days(date, 2)
        self.cash -= total_cost

        existing = self.positions.get(order.ticker)
        if existing is None:
            new_position = Position(ticker=order.ticker, shares=order.shares, avg_cost=price)
        else:
            total_shares = existing.shares + order.shares
            total_basis = existing.avg_cost * existing.shares + notional
            new_position = Position(
                ticker=order.ticker,
                shares=total_shares,
                avg_cost=total_basis / total_shares,
            )
        self.positions[order.ticker] = new_position

        fill = Fill(
            order=order,
            date=date,
            price=price,
            shares=order.shares,
            commission=fee,
            clamped=clamped,
            settlement_date=settlement_date,
        )
        return OrderResult(fill=fill)

    def execute_sell(
        self,
        order: Order,
        price: float,
        date: str,
        calendar: TradingCalendar,
        commission_model: CommissionModel,
        *,
        clamped: bool = False,
    ) -> OrderResult:
        """Execute a sell fill: oversell check, realized P/L, tax, T+2 record."""

        if order.side != "sell":
            raise ValueError(f"execute_sell requires a sell order, got side={order.side!r}")
        self._check_lot(order)

        position = self.positions.get(order.ticker)
        if position is None or position.shares < order.shares:
            return OrderResult(fill=None, reason="oversell")

        notional = price * order.shares
        fee = commission(notional, commission_model)
        pnl = (price - position.avg_cost) * order.shares - fee
        settlement_date = calendar.add_business_days(date, 2)
        tax_delta = self.tax_ledger.record_realized_pnl(pnl)
        self.cash += notional - fee - tax_delta
        self.realized_pnl += pnl

        remaining = position.shares - order.shares
        if remaining == 0:
            del self.positions[order.ticker]
        else:
            self.positions[order.ticker] = Position(
                ticker=order.ticker, shares=remaining, avg_cost=position.avg_cost
            )

        fill = Fill(
            order=order,
            date=date,
            price=price,
            shares=order.shares,
            commission=fee,
            clamped=clamped,
            settlement_date=settlement_date,
        )
        return OrderResult(fill=fill)

    def missing_prices(self, prices: Mapping[str, float]) -> tuple[str, ...]:
        """Held tickers absent from a mark-price mapping."""

        return tuple(ticker for ticker in self.positions if ticker not in prices)

    def equity(self, prices: Mapping[str, float]) -> float:
        """Cash + positions marked at ``prices``.

        Missing held tickers fall back to their average cost to preserve v1
        marking behavior. The P2 engine must call :meth:`missing_prices` on
        marking days and record any price gaps before relying on this fallback.
        """

        marked = sum(
            position.shares * prices.get(ticker, position.avg_cost)
            for ticker, position in self.positions.items()
        )
        return self.cash + marked

    def snapshot(self) -> dict[str, Any]:
        """A plain-dict snapshot suitable for JSON persistence."""

        return {
            "cash": self.cash,
            "positions": {
                ticker: {"shares": position.shares, "avg_cost": position.avg_cost}
                for ticker, position in self.positions.items()
            },
            "realized_pnl": self.realized_pnl,
            "tax_ledger": {
                "nisa": self.tax_ledger.nisa,
                "cumulative_pnl": self.tax_ledger.cumulative_pnl,
                "cumulative_tax_withheld": self.tax_ledger.cumulative_tax_withheld,
            },
        }
