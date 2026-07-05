from __future__ import annotations

import json
from pathlib import Path

from investment_assistant.webapi.data_quality_control_report import (
    DataQualityControlReportConfig,
    build_data_quality_control_report,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _write_inputs(root: Path) -> dict[str, Path]:
    profile = root / "data_quality_profile.json"
    _write_json(
        profile,
        {
            "status": "needs_attention",
            "summary": {
                "dimension_count": 6,
                "pass_count": 4,
                "needs_attention_count": 2,
                "jpx_domestic_stock_count": 2,
            },
            "write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
        },
    )
    gap = root / "data_gap_dashboard.json"
    _write_json(
        gap,
        {
            "status": "needs_attention",
            "summary": {
                "universe_count": 2,
                "price_gap_count": 1,
                "yield_gap_count": 1,
                "yield_coverage_pct": 50.0,
                "source_data_write_executed": False,
                "external_fetch_executed": False,
                "auto_trading": False,
                "call_real_api": False,
            },
        },
    )
    drift = root / "source_drift_audit.json"
    _write_json(
        drift,
        {
            "status": "needs_attention",
            "summary": {
                "reference_count": 2,
                "source_with_drift_count": 1,
                "total_extra_ticker_count": 1,
                "total_missing_ticker_count": 1,
                "source_data_write_executed": False,
                "external_fetch_executed": False,
                "auto_trading": False,
                "call_real_api": False,
            },
        },
    )
    preview = root / "source_cleansing_preview.json"
    _write_json(
        preview,
        {
            "status": "needs_attention",
            "summary": {
                "reference_count": 2,
                "source_count": 2,
                "total_dropped_row_count": 1,
                "total_missing_ticker_count": 1,
                "source_data_write_executed": False,
                "external_fetch_executed": False,
                "auto_trading": False,
                "call_real_api": False,
            },
            "sources": [
                {
                    "source_id": "current_prices",
                    "preview_filename": "current_prices_jpx_domestic_clean_preview.csv",
                }
            ],
        },
    )
    (root / "current_prices_jpx_domestic_clean_preview.csv").write_text(
        "ticker,price\n1301,100\n",
        encoding="utf-8",
    )
    backlog = root / "daily_bars_backfill_batch001_slice001_readiness_backlog.json"
    _write_json(
        backlog,
        {
            "status": "blocked",
            "summary": {
                "blockers": 45,
                "blocked_ticker_count": 5,
                "blocked_field_count": 9,
                "ready_rows": 0,
                "template_rows": 5,
                "append_ready": False,
                "next_sprint_goal": (
                    "Resolve P0 Slice 001 backlog rows by filling reviewed "
                    "OHLCV/source evidence."
                ),
                "source_data_write_executed": False,
                "external_fetch_executed": False,
                "auto_trading": False,
                "call_real_api": False,
            },
        },
    )
    return {
        "profile": profile,
        "gap": gap,
        "drift": drift,
        "preview": preview,
        "backlog": backlog,
    }


def test_data_quality_control_report_summarizes_safe_mode_and_gates(
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path)
    mirror_dir = tmp_path / "mirror"

    payload = build_data_quality_control_report(
        DataQualityControlReportConfig(
            output_dir=tmp_path,
            data_quality_profile_path=paths["profile"],
            data_gap_dashboard_path=paths["gap"],
            source_drift_audit_path=paths["drift"],
            source_cleansing_preview_path=paths["preview"],
            daily_bars_readiness_backlog_path=paths["backlog"],
            mirror_dirs=(mirror_dir,),
            generated_at="2026-07-05T00:00:00+09:00",
        )
    )

    assert payload["status"] == "needs_attention"
    assert payload["summary"]["gate_count"] == 6
    assert payload["summary"]["pass_count"] == 3
    assert payload["summary"]["needs_attention_count"] == 3
    assert payload["summary"]["blocked_count"] == 0
    assert payload["summary"]["raw_source_ingestion_allowed"] is False
    assert payload["summary"]["clean_preview_available"] is True
    assert payload["summary"]["safe_data_mode"] == "clean_preview_only"
    assert payload["summary"]["downstream_ready"] is False
    assert payload["summary"]["operational_backlog_count"] == 1
    assert payload["summary"]["operational_backlog_blockers"] == 45
    assert payload["summary"]["operational_backlog_blocked_ticker_count"] == 5
    assert payload["summary"]["operational_backlog_blocked_field_count"] == 9
    assert payload["summary"]["operational_backlog_ready"] is False
    assert payload["summary"]["external_fetch_executed"] is False
    assert payload["summary"]["auto_trading"] is False
    assert payload["summary"]["call_real_api"] is False

    gate_status = {gate["gate_id"]: gate["status"] for gate in payload["gates"]}
    assert gate_status["source_of_truth"] == "pass"
    assert gate_status["raw_source_drift"] == "needs_attention"
    assert gate_status["clean_preview_available"] == "pass"
    assert gate_status["downstream_completeness"] == "needs_attention"
    assert gate_status["quality_dimensions"] == "needs_attention"
    assert gate_status["operational_guardrails"] == "pass"
    assert payload["operational_backlogs"] == [
        {
            "backlog_id": "daily_bars_slice001_readiness",
            "label": "Daily bars Slice 001 readiness",
            "status": "needs_attention",
            "blockers": 45,
            "blocked_ticker_count": 5,
            "blocked_field_count": 9,
            "ready_rows": 0,
            "template_rows": 5,
            "append_ready": False,
            "next_action": (
                "Resolve P0 Slice 001 backlog rows by filling reviewed "
                "OHLCV/source evidence."
            ),
            "artifact": "daily_bars_backfill_batch001_slice001_readiness_backlog.json",
            "link": "daily_bars_backfill_batch001_slice001_readiness_backlog.html",
        }
    ]
    assert any("Slice 001 backlog" in action for action in payload["recommended_actions"])

    raw_json = (tmp_path / "data_quality_control_report.json").read_text(
        encoding="utf-8"
    )
    assert all(ord(character) < 128 for character in raw_json)
    assert json.loads(raw_json)["title"] == "Data Quality Control Report"

    for suffix in ("json", "csv", "html", "md"):
        filename = f"data_quality_control_report.{suffix}"
        assert (tmp_path / filename).exists()
        assert (mirror_dir / filename).exists()
        assert (tmp_path / filename).read_bytes() == (mirror_dir / filename).read_bytes()


def test_data_quality_control_report_blocks_when_preview_file_is_missing(
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path)
    (tmp_path / "current_prices_jpx_domestic_clean_preview.csv").unlink()

    payload = build_data_quality_control_report(
        DataQualityControlReportConfig(
            output_dir=tmp_path,
            data_quality_profile_path=paths["profile"],
            data_gap_dashboard_path=paths["gap"],
            source_drift_audit_path=paths["drift"],
            source_cleansing_preview_path=paths["preview"],
            daily_bars_readiness_backlog_path=paths["backlog"],
            generated_at="2026-07-05T00:00:00+09:00",
        )
    )

    assert payload["status"] == "blocked"
    gate_status = {gate["gate_id"]: gate["status"] for gate in payload["gates"]}
    assert gate_status["clean_preview_available"] == "blocked"
    assert payload["summary"]["safe_data_mode"] == "blocked"
