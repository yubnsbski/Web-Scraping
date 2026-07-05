from __future__ import annotations

import json
from pathlib import Path

from investment_assistant.webapi.market_dashboard_entry_artifacts import (
    SYNC_FILENAMES,
    build_market_dashboard_entry_artifacts,
)


def _write_seed_artifacts(root: Path) -> None:
    control_summary = {
        "gate_count": 6,
        "pass_count": 3,
        "needs_attention_count": 3,
        "safe_data_mode": "clean_preview_only",
        "raw_source_ingestion_allowed": False,
        "source_data_write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
    }
    (root / "data_quality_control_report.json").write_text(
        json.dumps(
            {
                "status": "needs_attention",
                "summary": control_summary,
                "auto_trading": False,
                "call_real_api": False,
                "external_fetch_executed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for filename in SYNC_FILENAMES:
        path = root / filename
        if path.exists():
            continue
        if filename.endswith(".json"):
            path.write_text('{"status":"pass"}\n', encoding="utf-8")
        else:
            path.write_text(f"{filename}\n", encoding="utf-8")


def test_build_market_dashboard_entry_adds_control_report_card(tmp_path) -> None:
    root = tmp_path / "public" / "market-dashboard"
    dist = tmp_path / "dist" / "market-dashboard"
    docs = tmp_path / "local_docs" / "market"
    root.mkdir(parents=True)
    _write_seed_artifacts(root)

    result = build_market_dashboard_entry_artifacts(
        dashboard_root=root,
        mirror_roots=(dist, docs),
        generated_at="2026-07-05T03:30:00+09:00",
    )

    entry = json.loads((root / "market_dashboard_entry.json").read_text(encoding="utf-8"))
    health = json.loads(
        (root / "market_dashboard_health_check.json").read_text(encoding="utf-8")
    )
    control_card = entry["cards"][-1]

    assert result["entry"]["card_count"] == 10
    assert entry["card_count"] == 10
    assert entry["ready_card_count"] == 8
    assert entry["data_quality_control_visible"] is True
    assert entry["auto_trading"] is False
    assert entry["call_real_api"] is False
    assert control_card["title"] == "統合品質ゲート"
    assert control_card["status"] == "needs_attention"
    assert control_card["metric"] == "3/6 gates pass"
    assert control_card["link"] == "data_quality_control_report.html"
    assert "data_quality_control_report.html" in (
        root / "market_dashboard_entry.html"
    ).read_text(encoding="utf-8")
    assert (dist / "market_dashboard_entry.html").read_text(encoding="utf-8") == (
        root / "market_dashboard_entry.html"
    ).read_text(encoding="utf-8")
    assert (docs / "market_dashboard_entry.json").read_text(encoding="utf-8") == (
        root / "market_dashboard_entry.json"
    ).read_text(encoding="utf-8")
    assert health["summary"]["entry_cards"] == 10
    assert health["summary"]["check_count"] == 14
    assert health["summary"]["passed_count"] == 14
    assert health["summary"]["static_sync"] == "46/46"
    assert any(
        item["file"] == "data_quality_control_report.html"
        for item in health["important_files"]
    )
    assert any(
        item["file"] == "data_quality_sprint_review.html"
        for item in health["important_files"]
    )
    assert any(
        item["file"] == "daily_bars_backfill_batch001_slice001_readiness_backlog.html"
        for item in health["important_files"]
    )
    assert "daily_bars_backfill_batch001_slice001_readiness_backlog.html" in (
        root / "market_dashboard_entry.html"
    ).read_text(encoding="utf-8")
    assert any(
        item["file"] == "daily_bars_backfill_batch001_slice001_local_evidence.html"
        for item in health["important_files"]
    )
    assert "daily_bars_backfill_batch001_slice001_local_evidence.html" in (
        root / "market_dashboard_entry.html"
    ).read_text(encoding="utf-8")
    assert any(
        item["file"] == "daily_bars_backfill_batch001_slice001_review_gate.html"
        for item in health["important_files"]
    )
    assert "daily_bars_backfill_batch001_slice001_review_gate.html" in (
        root / "market_dashboard_entry.html"
    ).read_text(encoding="utf-8")
    assert any(item["file"] == "lineage.html" for item in health["important_files"])
    assert health["auto_trading"] is False
    assert health["call_real_api"] is False
    assert health["external_fetch_executed"] is False
