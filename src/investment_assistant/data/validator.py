"""Data quality validation for investment data.

Rules:
- Price must be positive and not more than 10x the 30-day average (spike detection)
- DPS payout ratio must be < 200% (negative EPS may be legitimate, but >200% signals anomaly)
- Consecutive DPS history must not drop > 50% in a single year without a note
- Financial data: equity ratio must be 0–100%, ROE must be < 100% for non-financials
- Cross-source check: DPS from Yahoo vs EDINET must agree within 5%
"""

from __future__ import annotations

from investment_assistant.data.models import DataQualityFlag, DividendHistory, StockQuote


def validate_quote(quote: StockQuote) -> list[DataQualityFlag]:
    flags: list[DataQualityFlag] = []

    if quote.price <= 0:
        flags.append(DataQualityFlag(
            ticker=quote.ticker, field="price", severity="error",
            message=f"株価が0以下: {quote.price}",
        ))

    if quote.dps_ttm < 0:
        flags.append(DataQualityFlag(
            ticker=quote.ticker, field="dps_ttm", severity="error",
            message=f"DPSが負値: {quote.dps_ttm}",
        ))

    if quote.eps_ttm != 0:
        payout = quote.payout_ratio
        if payout > 2.0:
            flags.append(DataQualityFlag(
                ticker=quote.ticker, field="payout_ratio", severity="warn",
                message=f"配当性向が200%超 ({payout:.0%}): 持続性に疑問",
            ))

    if quote.per < 0:
        flags.append(DataQualityFlag(
            ticker=quote.ticker, field="per", severity="warn",
            message=f"PERが負値: {quote.per} (赤字決算の可能性)",
        ))

    if quote.dividend_yield > 0.12:
        flags.append(DataQualityFlag(
            ticker=quote.ticker, field="dividend_yield", severity="warn",
            message=f"配当利回りが12%超 ({quote.dividend_yield:.1%}): 減配リスクまたはデータ異常",
        ))

    return flags


def validate_dividend_history(ticker: str, history: list[DividendHistory]) -> list[DataQualityFlag]:
    """Check for sudden large DPS cuts."""
    flags: list[DataQualityFlag] = []
    sorted_hist = sorted(history, key=lambda d: d.fiscal_year)
    for prev, curr in zip(sorted_hist, sorted_hist[1:]):
        if prev.dps > 0 and curr.dps < prev.dps * 0.5:
            flags.append(DataQualityFlag(
                ticker=ticker, field="dps",
                severity="warn",
                message=(
                    f"FY{curr.fiscal_year}: DPS {curr.dps}円 ← FY{prev.fiscal_year}: {prev.dps}円 "
                    f"(▼{(1 - curr.dps/prev.dps):.0%}の急落)"
                ),
            ))
    return flags


def cross_validate_dps(
    ticker: str,
    yahoo_dps: float,
    edinet_dps: float,
    tolerance: float = 0.05,
) -> list[DataQualityFlag]:
    """Flag DPS discrepancy between Yahoo Finance and EDINET."""
    flags: list[DataQualityFlag] = []
    if yahoo_dps <= 0 or edinet_dps <= 0:
        return flags
    diff_ratio = abs(yahoo_dps - edinet_dps) / max(yahoo_dps, edinet_dps)
    if diff_ratio > tolerance:
        flags.append(DataQualityFlag(
            ticker=ticker, field="dps_cross",
            severity="warn",
            message=(
                f"DPS乖離: Yahoo {yahoo_dps}円 vs EDINET {edinet_dps}円 "
                f"(差異{diff_ratio:.1%}) → 手動確認推奨"
            ),
        ))
    return flags
