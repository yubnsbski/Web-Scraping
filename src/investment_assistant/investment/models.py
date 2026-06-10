"""Typed inputs for the investment-only MVP.

The dataclasses intentionally stay simple and deterministic. They model user
provided holdings and fund profiles; no brokerage connectivity or order flow is
represented here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

HOLDING_COLUMNS: tuple[str, ...] = (
    "asset_type",
    "ticker_or_fund_code",
    "name",
    "quantity",
    "avg_cost",
    "account_type",
    "tax_wrapper",
    "source",
)

FUND_PROFILE_COLUMNS: tuple[str, ...] = (
    "fund_code",
    "name",
    "asset_class",
    "expense_ratio",
    "distribution_policy",
    "nisa_eligible",
    "provider_id",
)

DISCLAIMER = (
    "これは投資助言・売買推奨ではありません。ユーザー提供データと取得済み公開情報を"
    "機械的に集計した比較材料です。最終的な投資判断はユーザー本人が行います。"
    "自動売買や証券口座への注文連携は行いません。"
)


@dataclass(frozen=True)
class InvestmentHolding:
    asset_type: str
    ticker_or_fund_code: str
    name: str
    quantity: float
    avg_cost: float
    account_type: str
    tax_wrapper: str
    source: str
    current_price: float | None = None
    annual_income: float | None = None
    distribution_per_unit: float | None = None
    data_provider: str | None = None
    price_as_of: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FundProfile:
    fund_code: str
    name: str
    asset_class: str
    expense_ratio: float
    distribution_policy: str
    nisa_eligible: bool
    provider_id: str
    diversification_score: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateScreen:
    asset_types: tuple[str, ...] = ("stock", "fund")
    exclude_dividend_cut: bool = False
    min_equity_ratio: float | None = None
    max_expense_ratio: float | None = None
    nisa_eligible_only: bool = False
    min_diversification_score: float | None = None
    sort_by: str = "score"
    limit: int | None = None
    include_evidence: bool = True
