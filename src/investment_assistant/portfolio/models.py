"""Models for local portfolio analytics."""

from __future__ import annotations

from dataclasses import dataclass

DIVIDEND_COLUMNS: tuple[str, ...] = ("period", "dividend_received", "yield_pct")
PERFORMANCE_COLUMNS: tuple[str, ...] = ("period", "market_value", "principal")


@dataclass(frozen=True)
class DividendPoint:
    period: str
    dividend_received: float
    yield_pct: float


@dataclass(frozen=True)
class PerformancePoint:
    period: str
    market_value: float
    principal: float

    @property
    def pnl(self) -> float:
        return round(self.market_value - self.principal, 2)

    @property
    def pnl_pct(self) -> float:
        if self.principal == 0:
            return 0.0
        return round(
            (self.market_value - self.principal) / self.principal * 100.0,
            2,
        )
