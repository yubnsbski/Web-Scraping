"""Domain models for the high-quality investment data pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class StockQuote:
    """Current market quote for a Japanese stock."""

    ticker: str
    name: str
    price: float
    price_date: date
    dps_ttm: float          # trailing twelve months dividend per share
    eps_ttm: float          # trailing twelve months EPS
    per: float              # price-earnings ratio
    pbr: float              # price-book ratio
    market_cap_m: float     # market cap in million JPY
    sector: str
    source: str             # "yahoo_jp" | "manual"
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def dividend_yield(self) -> float:
        return self.dps_ttm / self.price if self.price > 0 else 0.0

    @property
    def payout_ratio(self) -> float:
        return self.dps_ttm / self.eps_ttm if self.eps_ttm > 0 else 0.0


@dataclass
class DividendHistory:
    """One year's dividend record for a stock."""

    ticker: str
    fiscal_year: int        # e.g. 2025 for FY2025 (Mar 2026 close)
    dps: float              # yen per share
    source: str             # "edinet" | "yahoo_jp" | "manual"
    recorded_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FinancialSummary:
    """Key annual financial statement metrics for a stock."""

    ticker: str
    fiscal_year: int
    revenue_m: float            # million JPY
    operating_profit_m: float
    net_profit_m: float
    total_assets_m: float
    equity_m: float
    interest_bearing_debt_m: float
    operating_cf_m: float
    eps: float
    bps: float
    roe: float                  # return on equity (fraction, e.g. 0.12)
    equity_ratio: float         # equity / total assets (fraction)
    source: str
    recorded_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def debt_equity_ratio(self) -> float:
        return self.interest_bearing_debt_m / self.equity_m if self.equity_m > 0 else 0.0


@dataclass
class DataQualityFlag:
    """Quality issue detected during validation."""

    ticker: str
    field: str
    severity: str           # "warn" | "error"
    message: str
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CollectionResult:
    """Result of one data collection run."""

    ticker: str
    success: bool
    quote: Optional[StockQuote] = None
    dividends: list[DividendHistory] = field(default_factory=list)
    financials: list[FinancialSummary] = field(default_factory=list)
    flags: list[DataQualityFlag] = field(default_factory=list)
    error: Optional[str] = None
