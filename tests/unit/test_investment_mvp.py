from __future__ import annotations

import json
from pathlib import Path

import pytest

from investment_assistant.investment import (
    analyze_portfolio,
    audit_investment_report,
    build_investment_detail,
    build_investment_monthly_report,
    fund_profiles_from_payload,
    holdings_from_payload,
    screen_candidates,
)
from investment_assistant.investment.candidates import screen_from_values
from investment_assistant.investment.provider_policy import (
    ensure_provider_allowed,
    provider_policy_ledger,
)
from investment_assistant.investment.report_history import (
    list_investment_reports,
    load_investment_report,
    save_investment_report,
    verify_investment_report_history,
)
from investment_assistant.portfolio.simulator import plan_for_target_dividend

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
    nisa = summary["nisa"]
    assert isinstance(nisa, dict)
    assert nisa["status"] == "ok"
    assert nisa["growth_status"] == "ok"
    assert nisa["alerts"] == []
    data_quality = summary["data_quality"]
    assert isinstance(data_quality, dict)
    assert data_quality["status"] == "info"
    assert data_quality["missing_timestamp_count"] == 2
    income_quality = summary["income_quality"]
    assert isinstance(income_quality, dict)
    assert income_quality["status"] == "ok"
    assert income_quality["alert_count"] == 0
    assert income_quality["alerts"] == []
    assert result["auto_trading"] is False
    assert "投資助言" in str(result["disclaimer"])


def test_analyze_portfolio_flags_nisa_cap_usage(tmp_path: Path) -> None:
    holdings_csv = (
        "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
        "source,current_price,annual_income,distribution_per_unit\n"
        "stock,7203,Toyota,10000,1300,tokutei,nisa_growth,user_csv,1400,,\n"
    )
    result = analyze_portfolio(
        holdings_from_payload({"csv_text": holdings_csv}),
        financials_csv=_financials(tmp_path),
    )

    summary = result["summary"]
    assert isinstance(summary, dict)
    nisa = summary["nisa"]
    assert isinstance(nisa, dict)
    assert nisa["usage_pct"] > 70
    assert nisa["growth_status"] == "exceeded"
    assert nisa["growth_excess"] == 1_000_000.0
    alerts = nisa["alerts"]
    assert isinstance(alerts, list)
    assert alerts[0]["code"] == "nisa_growth_cap_exceeded"
    assert alerts[0]["level"] == "error"


def test_analyze_portfolio_flags_data_quality_warnings(tmp_path: Path) -> None:
    holdings_csv = (
        "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
        "source,current_price,annual_income,distribution_per_unit,data_provider,price_as_of\n"
        "stock,8306,MUFG,100,1000,tokutei,taxable,stooq_public_csv,1200,,,"
        "stooq_public_csv,2020-01-01\n"
        "fund,F001,No Current Price Fund,10,10000,nisa,nisa_tsumitate,user_csv,,,30,"
        "user_csv,\n"
    )
    result = analyze_portfolio(
        holdings_from_payload({"csv_text": holdings_csv}),
        financials_csv=_financials(tmp_path),
        runtime_mode="production",
    )

    summary = result["summary"]
    assert isinstance(summary, dict)
    data_quality = summary["data_quality"]
    assert isinstance(data_quality, dict)
    assert data_quality["status"] == "error"
    assert data_quality["provider_blocked_count"] == 1
    assert data_quality["stale_price_count"] == 1
    assert data_quality["missing_price_count"] == 1
    alerts = data_quality["alerts"]
    assert isinstance(alerts, list)
    alert_codes = {str(alert.get("code")) for alert in alerts if isinstance(alert, dict)}
    assert {
        "provider_not_production_allowed",
        "price_stale",
        "price_missing_fallback_avg_cost",
    } <= alert_codes
    evidence_keys = {
        str(item.get("claim_key"))
        for item in result["evidence"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert "portfolio.data_quality" in evidence_keys
    assert "buy" not in str(result).lower()
    assert "sell" not in str(result).lower()


def test_analyze_portfolio_flags_income_quality_warnings(tmp_path: Path) -> None:
    holdings_csv = (
        "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
        "source,current_price,annual_income,distribution_per_unit\n"
        "stock,1111,No Income Source,10,1000,tokutei,taxable,user_csv,1000,,\n"
        "fund,F999,High Distribution Fund,10,1000,nisa,nisa_tsumitate,user_csv,1000,,150\n"
        "stock,2222,Negative Income Input,10,1000,tokutei,taxable,user_csv,1000,-100,\n"
    )
    result = analyze_portfolio(
        holdings_from_payload({"csv_text": holdings_csv}),
        financials_csv=_financials(tmp_path),
    )

    summary = result["summary"]
    assert isinstance(summary, dict)
    income_quality = summary["income_quality"]
    assert isinstance(income_quality, dict)
    assert income_quality["status"] == "error"
    assert income_quality["alert_count"] == 3
    assert income_quality["missing_income_count"] == 1
    assert income_quality["high_yield_count"] == 1
    assert income_quality["negative_input_count"] == 1
    alerts = income_quality["alerts"]
    assert isinstance(alerts, list)
    alert_codes = {str(alert.get("code")) for alert in alerts if isinstance(alert, dict)}
    assert {"income_missing", "income_yield_high", "income_negative_input"} <= alert_codes
    assert "buy" not in str(result).lower()
    assert "sell" not in str(result).lower()
    evidence_keys = {
        str(item.get("claim_key"))
        for item in result["evidence"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert "portfolio.income_quality" in evidence_keys


def test_investment_monthly_report_surfaces_income_quality_warnings(tmp_path: Path) -> None:
    holdings_csv = (
        "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
        "source,current_price,annual_income,distribution_per_unit\n"
        "stock,1111,No Income Source,10,1000,tokutei,taxable,user_csv,1000,,\n"
    )
    report = build_investment_monthly_report(
        holdings_from_payload({"csv_text": holdings_csv}),
        candidates=[],
        financials_csv=_financials(tmp_path),
    )

    sections = report["sections"]
    assert isinstance(sections, list)
    section_keys = {str(section.get("key")) for section in sections if isinstance(section, dict)}
    assert "income_quality" in section_keys
    evidence_keys = {
        str(item.get("claim_key"))
        for item in report["evidence"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert "portfolio.income_quality" in evidence_keys


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


def test_provider_policy_ledger_marks_production_blockers() -> None:
    ledger = provider_policy_ledger(
        runtime_mode="production",
        provider_ids=["user_csv", "edinet", "stooq_public_csv"],
    )

    rows = {
        str(item["provider_id"]): item
        for item in ledger["providers"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert ledger["runtime_mode"] == "production"
    assert rows["user_csv"]["runtime_decision"] == "allowed"
    assert rows["edinet"]["runtime_decision"] == "allowed"
    assert rows["stooq_public_csv"]["runtime_decision"] == "blocked_until_contracted"
    assert rows["stooq_public_csv"]["recommended_use"] == "development_only"
    assert ledger["auto_trading"] is False
    assert ledger["call_real_api"] is False


def test_investment_monthly_report_has_evidence_for_kpis(tmp_path: Path) -> None:
    holdings = holdings_from_payload({"csv_text": HOLDINGS_CSV})
    target_result = plan_for_target_dividend(
        target_annual_dividend=10_000,
        holdings=[
            {
                "ticker": "8306",
                "name": "MUFG",
                "price": 1200,
                "dividend_per_share": 45,
            }
        ],
        dividend_basis="latest",
        financials_csv=_financials(tmp_path),
    )
    report = build_investment_monthly_report(
        holdings,
        candidates=[{"code": "8306", "asset_type": "stock"}],
        target_result=target_result,
        financials_csv=_financials(tmp_path),
    )

    assert report["auto_trading"] is False
    assert report["candidate_count"] == 1
    publish_audit = report["publish_audit"]
    assert isinstance(publish_audit, dict)
    assert publish_audit["status"] == "ok"
    assert publish_audit["issue_count"] == 0
    assert publish_audit["issues"] == []
    kpis = report["kpis"]
    assert isinstance(kpis, list)
    assert all(item.get("evidence_keys") for item in kpis if isinstance(item, dict))
    metric_keys = {str(item.get("metric_key")) for item in kpis if isinstance(item, dict)}
    assert {
        "concentration_top_weight",
        "concentration_hhi",
        "concentration_effective_names",
        "target_annual_dividend",
        "target_achieved_annual_dividend",
        "target_required_budget",
        "target_reachable",
        "target_concentration_top_weight",
        "target_concentration_hhi",
        "target_effective_names",
    } <= metric_keys
    assert report["evidence"]
    evidence_keys = {
        str(item.get("claim_key"))
        for item in report["evidence"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert {
        "portfolio.concentration.current",
        "portfolio.data_quality",
        "portfolio.target.input",
        "portfolio.target.achieved",
        "portfolio.target.required_budget",
        "portfolio.target.reachable",
        "portfolio.target.concentration",
    } <= evidence_keys
    assert "投資助言" in str(report["disclaimer"])


def test_report_history_integrity_detects_saved_tampering(tmp_path: Path) -> None:
    report = build_investment_monthly_report(
        holdings_from_payload({"csv_text": HOLDINGS_CSV}),
        financials_csv=_financials(tmp_path),
    )
    history_dir = tmp_path / "report_history"
    summary = save_investment_report(report, history_dir=history_dir)
    report_id = str(summary["id"])

    assert summary["integrity_status"] == "ok"
    assert isinstance(summary["report_hash"], str)
    assert len(str(summary["report_hash"])) == 64
    loaded = load_investment_report(report_id, history_dir=history_dir)
    assert loaded["integrity_status"] == "ok"
    verified = verify_investment_report_history(report_id, history_dir=history_dir)
    assert verified["integrity_status"] == "ok"

    path = history_dir / f"{report_id}.json"
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["report"]["candidate_count"] = 999
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")

    tampered = load_investment_report(report_id, history_dir=history_dir)
    assert tampered["integrity_status"] == "tampered"
    assert tampered["summary"]["integrity_status"] == "tampered"
    assert tampered["report_hash"] != tampered["calculated_report_hash"]
    listed = list_investment_reports(history_dir=history_dir)
    assert listed["reports"][0]["integrity_status"] == "tampered"


def test_report_history_integrity_marks_legacy_entries_unknown(tmp_path: Path) -> None:
    report = build_investment_monthly_report(
        holdings_from_payload({"csv_text": HOLDINGS_CSV}),
        financials_csv=_financials(tmp_path),
    )
    history_dir = tmp_path / "report_history"
    history_dir.mkdir()
    legacy = {
        "id": "legacy",
        "saved_at": "2026-06-10T00:00:00+00:00",
        "summary": {"id": "legacy", "saved_at": "2026-06-10T00:00:00+00:00"},
        "report": report,
    }
    (history_dir / "legacy.json").write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    loaded = load_investment_report("legacy", history_dir=history_dir)
    assert loaded["integrity_status"] == "unknown"
    assert loaded["summary"]["integrity_status"] == "unknown"
    listed = list_investment_reports(history_dir=history_dir)
    assert listed["reports"][0]["integrity_status"] == "unknown"


def test_audit_investment_report_flags_missing_evidence_reference(tmp_path: Path) -> None:
    report = build_investment_monthly_report(
        holdings_from_payload({"csv_text": HOLDINGS_CSV}),
        financials_csv=_financials(tmp_path),
    )
    kpis = report["kpis"]
    assert isinstance(kpis, list)
    first_kpi = kpis[0]
    assert isinstance(first_kpi, dict)
    broken = {
        **report,
        "kpis": [
            {
                **first_kpi,
                "evidence_keys": ["missing.claim"],
            }
        ],
    }

    audit = audit_investment_report(broken)

    assert audit["status"] == "error"
    issue_codes = {
        str(item.get("code"))
        for item in audit["issues"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert "kpi_evidence_key_not_found" in issue_codes
    assert audit["auto_trading"] is False
    assert audit["call_real_api"] is False


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
