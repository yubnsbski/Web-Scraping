"""Detail and candidate screens must tolerate header-only (rows-less) CSVs.

The dashboard ships header-only sample CSVs, so these endpoints receive a CSV
with columns but no data rows. Holdings and fund profiles are optional context
here, so an empty CSV should yield empty context instead of a hard error.
"""

from __future__ import annotations

import pytest

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
