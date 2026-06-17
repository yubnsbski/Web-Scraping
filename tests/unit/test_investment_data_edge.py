"""Regression coverage for two investment data-handling defects.

New / conflict-light file (complements test_investment_mvp.py):
1. analysis.py counted the ``growth_nisa`` tax-wrapper spelling toward neither
   the lifetime NISA cap nor the growth sub-cap, silently understating usage.
2. loader.py rejected Excel/Windows CSVs carrying a UTF-8 BOM with a misleading
   "missing required column" error.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.investment import analyze_portfolio, holdings_from_payload
from investment_assistant.investment.loader import load_funds_csv_text, load_holdings_csv_text

_FINANCIALS = "examples/financials_sample.csv"

_HOLDINGS_HEADER = (
    "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
    "source,current_price,annual_income,distribution_per_unit\n"
)
_FUNDS_HEADER = (
    "fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,provider_id\n"
)


def _financials(tmp_path: Path) -> Path:
    # analyze_portfolio only needs a readable financials CSV; the bundled sample works.
    return Path(_FINANCIALS)


def _nisa(tax_wrapper: str) -> dict:
    csv_text = (
        _HOLDINGS_HEADER
        + f"stock,7203,Toyota,10000,1300,tokutei,{tax_wrapper},user_csv,1400,,\n"
    )
    result = analyze_portfolio(
        holdings_from_payload({"csv_text": csv_text}), financials_csv=Path(_FINANCIALS)
    )
    summary = result["summary"]
    assert isinstance(summary, dict)
    nisa = summary["nisa"]
    assert isinstance(nisa, dict)
    return nisa


def test_growth_nisa_wrapper_counts_same_as_nisa_growth() -> None:
    canonical = _nisa("nisa_growth")
    alias = _nisa("growth_nisa")
    # Before the fix, growth_nisa fell through every NISA branch -> all zeros.
    assert alias["used_cost_basis"] == canonical["used_cost_basis"] > 0
    assert alias["growth_used_cost_basis"] == canonical["growth_used_cost_basis"] > 0
    assert alias["growth_status"] == canonical["growth_status"]


def test_holdings_csv_with_utf8_bom_parses() -> None:
    body = (
        _HOLDINGS_HEADER
        + "stock,8306,MUFG,100,1000,tokutei,nisa_growth,user_csv,1200,,\n"
    )
    holdings = load_holdings_csv_text("﻿" + body)
    assert [h.ticker_or_fund_code for h in holdings] == ["8306"]


def test_funds_csv_with_utf8_bom_parses() -> None:
    body = _FUNDS_HEADER + "F001,All World,global_equity,0.1,reinvest,true,user_csv\n"
    funds = load_funds_csv_text("﻿" + body)
    assert [f.fund_code for f in funds] == ["F001"]


def test_holdings_csv_with_lone_cr_line_endings_parses() -> None:
    # Excel "save as CSV" can emit lone-CR endings, which previously raised
    # "new-line character seen in unquoted field".
    header = _HOLDINGS_HEADER.rstrip("\n")
    row = "stock,8306,MUFG,100,1000,tokutei,nisa_growth,user_csv,1200,,"
    holdings = load_holdings_csv_text(header + "\r" + row + "\r")
    assert [h.ticker_or_fund_code for h in holdings] == ["8306"]
