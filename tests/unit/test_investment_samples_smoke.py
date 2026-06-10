from __future__ import annotations

from pathlib import Path

from investment_assistant.webapi.service import handle_api

ROOT = Path(__file__).resolve().parents[2]
HOLDINGS_SAMPLE = ROOT / "examples" / "investment_holdings_sample.csv"
FUNDS_SAMPLE = ROOT / "examples" / "investment_funds_sample.csv"
FINANCIALS_SAMPLE = ROOT / "examples" / "financials_sample.csv"


def test_investment_sample_csvs_drive_full_api_smoke() -> None:
    status, imported = handle_api(
        "POST",
        "/api/holdings/import",
        {"path": str(HOLDINGS_SAMPLE)},
    )
    assert status == 200
    assert imported["count"] == 4
    assert imported["input_warnings"] == []
    assert imported["auto_trading"] is False

    status, analysis = handle_api(
        "POST",
        "/api/portfolio/analyze",
        {"path": str(HOLDINGS_SAMPLE), "financials_csv": str(FINANCIALS_SAMPLE)},
    )
    assert status == 200
    assert analysis["summary"]["holdings_count"] == 4
    assert analysis["summary"]["market_value"] == 2_514_000.0
    assert analysis["summary"]["cost_basis"] == 2_160_000.0
    assert analysis["summary"]["annual_income_estimate"] == 12_450.0

    status, candidates = handle_api(
        "POST",
        "/api/candidates/screen",
        {
            "asset_types": ["stock", "fund"],
            "funds_path": str(FUNDS_SAMPLE),
            "financials_csv": str(FINANCIALS_SAMPLE),
            "exclude_dividend_cut": True,
            "min_equity_ratio": 50,
            "max_expense_ratio": 0.2,
            "nisa_eligible_only": True,
            "min_diversification_score": 0.85,
            "sort_by": "score",
        },
    )
    assert status == 200
    codes = {item["code"] for item in candidates["results"]}
    assert {"7203", "FND001"} <= codes
    assert "9999" not in codes
    assert "FND999" not in codes
    assert candidates["auto_trading"] is False

    status, report = handle_api(
        "POST",
        "/api/reports/investment-monthly",
        {
            "path": str(HOLDINGS_SAMPLE),
            "financials_csv": str(FINANCIALS_SAMPLE),
            "candidates": candidates["results"],
        },
    )
    assert status == 200
    assert report["candidate_count"] == candidates["count"]
    assert report["auto_trading"] is False
    _assert_report_kpis_are_auditable(report)


def _assert_report_kpis_are_auditable(report: dict[str, object]) -> None:
    evidence = report["evidence"]
    assert isinstance(evidence, list)
    claim_keys = {item.get("claim_key") for item in evidence if isinstance(item, dict)}

    kpis = report["kpis"]
    assert isinstance(kpis, list)
    assert kpis
    for item in kpis:
        assert isinstance(item, dict)
        assert item.get("evidence_keys")
        assert item.get("formula")
        assert item.get("last_updated")
        assert item.get("disclaimer") == report["disclaimer"]
        assert set(item["evidence_keys"]) <= claim_keys
