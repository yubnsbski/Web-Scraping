"""Detail and candidate screens must tolerate header-only (rows-less) CSVs.

The dashboard ships header-only sample CSVs, so these endpoints receive a CSV
with columns but no data rows. Holdings and fund profiles are optional context
here, so an empty CSV should yield empty context instead of a hard error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.investment.detail import build_investment_detail
from investment_assistant.webapi.investments import candidates_screen, investment_detail

HOLDINGS_HEADER = (
    "asset_type,ticker_or_fund_code,name,quantity,avg_cost,"
    "account_type,tax_wrapper,source\n"
)
FUNDS_HEADER = (
    "fund_code,name,asset_class,expense_ratio,distribution_policy,"
    "nisa_eligible,provider_id,diversification_score\n"
)


def test_detail_accepts_header_only_holdings_and_funds() -> None:
    result = investment_detail(
        {
            "code": "8306",
            "asset_type": "stock",
            "csv_text": HOLDINGS_HEADER,
            "funds_csv_text": FUNDS_HEADER,
        }
    )
    assert result["code"] == "8306"
    assert result["auto_trading"] is False


def test_candidates_screen_accepts_header_only_funds() -> None:
    result = candidates_screen(
        {
            "asset_types": ["stock", "fund"],
            "min_equity_ratio": 30,
            "max_expense_ratio": 0.3,
            "funds_csv_text": FUNDS_HEADER,
        }
    )
    assert "results" in result


def test_detail_still_rejects_malformed_csv() -> None:
    with pytest.raises(ValueError, match="Missing required CSV columns"):
        investment_detail(
            {"code": "8306", "asset_type": "stock", "csv_text": "bad,columns\n1,2\n"}
        )


def test_detail_surfaces_yahoo_market_financials(tmp_path: Path) -> None:
    market_csv = tmp_path / "yahoo_financials.csv"
    market_csv.write_text(
        "ticker,name,price,per,pbr,dps,dividend_yield,dividend_yield_percent,eps,market_cap\n"
        "8306,三菱UFJ,2100,12.5,0.9,60,0.0285,2.85,168,2.6e13\n",
        encoding="utf-8",
    )
    result = build_investment_detail(
        code="8306",
        asset_type="stock",
        market_financials_csv=market_csv,
    )
    assert result["available"] is True
    assert result["name"] == "三菱UFJ"
    market = result["market_financials"]
    assert isinstance(market, dict)
    assert market["price"] == "2100"
    metric_keys = {str(m["metric_key"]) for m in result["metrics"]}  # type: ignore[index]
    assert "market.price" in metric_keys
    assert "market.dps" in metric_keys
