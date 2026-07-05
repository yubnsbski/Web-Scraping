from __future__ import annotations

import json
from pathlib import Path

from investment_assistant.webapi.data_lineage_artifacts import (
    build_data_lineage_artifacts,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_build_data_lineage_artifacts_refreshes_lineage_outputs(tmp_path) -> None:
    root = tmp_path / "public" / "market-dashboard"
    local_market = tmp_path / "local_docs" / "market"
    dist = tmp_path / "dist" / "market-dashboard"
    docs = tmp_path / "docs" / "market"
    root.mkdir(parents=True)
    local_market.mkdir(parents=True)
    raw_prices = local_market / "current_prices.csv"
    raw_financials = local_market / "yahoo_financials.csv"
    clean_prices = root / "current_prices_jpx_domestic_clean_preview.csv"
    clean_financials = root / "market_financials_jpx_domestic_clean_preview.csv"
    for path in [
        local_market / "jpx_domestic_stock_snapshot_20260630.csv",
        root / "ticker_data_map.json",
        raw_prices,
        raw_financials,
        clean_prices,
        clean_financials,
    ]:
        path.write_text("ticker\n1301\n", encoding="utf-8")

    _write_json(
        root / "jpx_ticker_map_reconciliation.json",
        {
            "status": "fixed",
            "summary": {
                "official_domestic_stock_issues": 3716,
                "reconciled_ticker_map_rows": 3716,
                "extra_removed_count": 23,
                "missing_added_count": 5,
            },
        },
    )
    _write_json(
        root / "source_cleansing_preview.json",
        {
            "status": "needs_attention",
            "summary": {
                "reference_count": 3716,
                "total_dropped_ticker_count": 38,
                "total_missing_ticker_count": 10,
            },
            "sources": [
                {
                    "source_id": "current_prices",
                    "source_path": str(raw_prices),
                    "status": "needs_attention",
                    "raw_row_count": 3734,
                    "raw_ticker_count": 3734,
                    "dropped_ticker_count": 23,
                    "missing_ticker_count": 5,
                    "preview_path": str(clean_prices),
                    "clean_preview_row_count": 3711,
                    "clean_preview_ticker_count": 3711,
                    "kept_reference_coverage_pct": 99.87,
                },
                {
                    "source_id": "market_financials",
                    "source_path": str(raw_financials),
                    "status": "needs_attention",
                    "raw_row_count": 3726,
                    "raw_ticker_count": 3726,
                    "dropped_ticker_count": 15,
                    "missing_ticker_count": 5,
                    "preview_path": str(clean_financials),
                    "clean_preview_row_count": 3711,
                    "clean_preview_ticker_count": 3711,
                    "kept_reference_coverage_pct": 99.87,
                },
            ],
        },
    )
    _write_json(
        root / "data_quality_control_report.json",
        {
            "status": "needs_attention",
            "summary": {
                "gate_count": 6,
                "pass_count": 3,
                "safe_data_mode": "clean_preview_only",
                "clean_preview_available": True,
                "downstream_ready": False,
            },
        },
    )
    _write_json(
        root / "data_quality_profile.json",
        {"summary": {"dimension_count": 6, "pass_count": 4, "needs_attention_count": 2}},
    )
    _write_json(
        root / "data_gap_dashboard.json",
        {
            "summary": {
                "price_gap": 5,
                "yield_gap": 3465,
                "yield_coverage_pct": 6.75,
                "latest_as_of": "2026-07-02",
            }
        },
    )
    _write_json(
        root / "source_drift_audit.json",
        {
            "status": "needs_attention",
            "summary": {
                "total_extra_ticker_count": 38,
                "total_missing_ticker_count": 10,
            },
        },
    )

    result = build_data_lineage_artifacts(
        dashboard_root=root,
        local_market_root=local_market,
        mirror_roots=(dist, docs),
        generated_at="2026-07-05T03:45:00+09:00",
    )

    lineage = json.loads((root / "lineage.json").read_text(encoding="utf-8"))
    node_ids = {node["id"] for node in lineage["nodes"]}

    assert result["status"] == "ready"
    assert result["lineage_status"] == "needs_attention"
    assert lineage["schema_version"] == 2
    assert lineage["summary"]["source_of_truth_count"] == 3716
    assert lineage["summary"]["clean_preview_count"] == 2
    assert lineage["summary"]["safe_data_mode"] == "clean_preview_only"
    assert lineage["guardrails"] == {
        "auto_trading": False,
        "call_real_api": False,
        "external_fetch_executed": False,
        "source_data_write_executed": False,
        "write_to_source_data": False,
    }
    assert {"clean_current_prices", "clean_market_financials"}.issubset(node_ids)
    assert any(
        edge["from"] == "source_cleansing_preview"
        and edge["to"] == "clean_current_prices"
        for edge in lineage["edges"]
    )
    assert (root / "lineage.html").is_file()
    assert (root / "lineage.csv").is_file()
    assert (root / "lineage.md").is_file()
    assert (dist / "lineage.json").read_text(encoding="utf-8") == (
        root / "lineage.json"
    ).read_text(encoding="utf-8")
    assert (docs / "lineage.html").read_text(encoding="utf-8") == (
        root / "lineage.html"
    ).read_text(encoding="utf-8")
