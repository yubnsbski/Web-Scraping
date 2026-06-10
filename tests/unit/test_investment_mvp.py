from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.investment import (
    analyze_portfolio,
    build_investment_detail,
    build_investment_monthly_report,
    fund_profiles_from_payload,
    holdings_from_payload,
    screen_candidates,
)
from investment_assistant.investment.candidates import screen_from_values
from investment_assistant.investment.provider_policy import ensure_provider_allowed

HOLDINGS_CSV = (
    "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
    "source,current_price,annual_income,distribution_per_unit\n"
    """stock,8306,MUFG,100,1000,tokutei,nisa_growth,user_csv,1200,,
fund,F001,低コスト投信,50,10000,nisa,nisa_tsumitate,user_csv,11000,,30
"""
)

FUNDS_CSV = (
    "fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,"
    "provider_id,diversification_score\n"
    """F001,低コスト全世界株式,global_equity,0.12,reinvest,true,user_csv,0.95
F999,高コストテーマ型,theme,1.20,distribution,false,user_csv,0.40
"""
)


def _financials(tmp_path: Path) -> Path:
    path = tmp_path / "financials.csv"
    path.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "8306,MUFG,2023,1000,45,40,安定\n"
        "8306,MUFG,2024,1200,48,45,安定\n"
        "9999,Risky,2023,100,20,30,不安定\n"
        "9999,Risky,2024,90,18,10,不安定\n",
        encoding="utf-8",
    )
    return path


def test_analyze_mixed_stock_and_fund_portfolio(tmp_path: Path) -> None:
    holdings = holdings_from_payload({"csv_text": HOLDINGS_CSV})
    result = analyze_portfolio(holdings, financials_csv=_financials(tmp_path))

    summary = result["summary"]
    assert isinstance(summary, dict)
    assert summary["holdings_count"] == 2
    assert summary["market_value"] == 670000.0
    assert summary["cost_basis"] == 600000.0
    assert summary["annual_income_estimate"] == 6000.0
    assert result["auto_trading"] is False
    assert "投資助言" in str(result["disclaimer"])


def test_candidate_screen_returns_condition_matches_not_recommendations(tmp_path: Path) -> None:
    funds = fund_profiles_from_payload({"funds_csv_text": FUNDS_CSV})
    screen = screen_from_values(
        asset_types=["stock", "fund"],
        exclude_dividend_cut=True,
        min_equity_ratio=40.0,
        max_expense_ratio=0.2,
        nisa_eligible_only=True,
        min_diversification_score=0.8,
        sort_by="score",
        limit=None,
    )
    result = screen_candidates(screen=screen, funds=funds, financials_csv=_financials(tmp_path))

    codes = {str(item["code"]) for item in result["results"]}  # type: ignore[index]
    assert {"8306", "F001"} <= codes
    assert "9999" not in codes and "F999" not in codes
    assert result["auto_trading"] is False
    assert "買い推奨" not in str(result)
    assert "売り推奨" not in str(result)


def test_provider_policy_blocks_uncontracted_production_provider() -> None:
    with pytest.raises(ValueError, match="not allowed in production"):
        ensure_provider_allowed("stooq_public_csv", runtime_mode="production")

    assert ensure_provider_allowed("user_csv", runtime_mode="production").production_allowed


def test_investment_monthly_report_has_evidence_for_kpis(tmp_path: Path) -> None:
    holdings = holdings_from_payload({"csv_text": HOLDINGS_CSV})
    report = build_investment_monthly_report(
        holdings,
        candidates=[{"code": "8306", "asset_type": "stock"}],
        financials_csv=_financials(tmp_path),
    )

    assert report["auto_trading"] is False
    assert report["candidate_count"] == 1
    kpis = report["kpis"]
    assert isinstance(kpis, list)
    assert all(item.get("evidence_keys") for item in kpis if isinstance(item, dict))
    assert report["evidence"]
    assert "投資助言" in str(report["disclaimer"])


def test_stock_detail_combines_holding_and_financial_evidence(tmp_path: Path) -> None:
    holdings = holdings_from_payload({"csv_text": HOLDINGS_CSV})
    detail = build_investment_detail(
        code="8306",
        asset_type="stock",
        holdings=holdings,
        financials_csv=_financials(tmp_path),
    )

    assert detail["available"] is True
    assert detail["asset_type"] == "stock"
    assert detail["auto_trading"] is False
    assert "買い推奨" not in str(detail)
    metric_keys = {
        str(item.get("metric_key"))
        for item in detail["metrics"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert {"holding.market_value", "financials.latest_equity_ratio"} <= metric_keys
    assert detail["evidence"]
    assert "投資助言" in str(detail["disclaimer"])


def test_fund_detail_uses_fund_profile_without_holding_csv() -> None:
    funds = fund_profiles_from_payload({"funds_csv_text": FUNDS_CSV})
    detail = build_investment_detail(code="F001", asset_type="fund", funds=funds)

    assert detail["available"] is True
    assert detail["asset_type"] == "fund"
    assert detail["fund_profile"]
    metric_keys = {
        str(item.get("metric_key"))
        for item in detail["metrics"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert {"fund.expense_ratio", "fund.nisa_eligible"} <= metric_keys
    assert detail["auto_trading"] is False
