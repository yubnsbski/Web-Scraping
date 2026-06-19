"""Yahoo market financials enrich price/dividend in portfolio analysis."""

from __future__ import annotations

from pathlib import Path

from investment_assistant.investment import analyze_portfolio, holdings_from_payload

_HOLDINGS = (
    "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source\n"
    "stock,8306,三菱UFJ,100,1000,tokutei,taxable,user_csv\n"
)
# 7203: Yahoo price 2500, dividend-per-share 60. 9999 absent -> no enrichment.
_YAHOO = (
    "ticker,name,price,per,pbr,dps,dividend_yield,dividend_yield_percent,eps,market_cap\n"
    "8306,三菱UFJ,2500,10,1.1,60,0.024,2.4,200,30000000000000\n"
)


def _holdings():
    return holdings_from_payload({"csv_text": _HOLDINGS})


def test_yahoo_price_and_dividend_used_when_holding_lacks_them(tmp_path: Path) -> None:
    yahoo = tmp_path / "yahoo_financials.csv"
    yahoo.write_text(_YAHOO, encoding="utf-8")

    result = analyze_portfolio(
        _holdings(),
        financials_csv="examples/financials_sample.csv",
        market_financials_csv=yahoo,
    )
    row = result["holdings"][0]
    # Price from Yahoo (2500), not the 1000 avg cost.
    assert row["price_source"] == "yahoo_price"
    assert row["price_used"] == 2500.0
    assert row["market_value"] == 250000.0
    # Annual income from Yahoo dps (60) x 100 shares.
    assert row["annual_income_source"] == "yahoo_dividend_per_share"
    assert row["annual_income_estimate"] == 6000.0


def test_without_market_csv_falls_back_to_avg_cost(tmp_path: Path) -> None:
    result = analyze_portfolio(_holdings(), financials_csv="examples/financials_sample.csv")
    row = result["holdings"][0]
    assert row["price_source"] == "avg_cost"
    assert row["price_used"] == 1000.0


def test_explicit_current_price_beats_yahoo(tmp_path: Path) -> None:
    yahoo = tmp_path / "yahoo_financials.csv"
    yahoo.write_text(_YAHOO, encoding="utf-8")
    csv_text = (
        "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
        "source,current_price\n"
        "stock,8306,三菱UFJ,100,1000,tokutei,taxable,user_csv,3000\n"
    )
    result = analyze_portfolio(
        holdings_from_payload({"csv_text": csv_text}),
        financials_csv="examples/financials_sample.csv",
        market_financials_csv=yahoo,
    )
    row = result["holdings"][0]
    assert row["price_source"] == "current_price"
    assert row["price_used"] == 3000.0
