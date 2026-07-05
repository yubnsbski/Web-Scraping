from __future__ import annotations

import json
from pathlib import Path

from investment_assistant.webapi.data_quality_sprint_review import (
    DataQualitySprintReviewConfig,
    build_data_quality_sprint_review,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_build_data_quality_sprint_review_summarizes_local_sprint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "market-dashboard"
    mirror = tmp_path / "dist" / "market-dashboard"
    root.mkdir(parents=True)
    _write_json(
        root / "data_quality_profile.json",
        {
            "status": "needs_attention",
            "summary": {
                "dimension_count": 6,
                "pass_count": 4,
                "needs_attention_count": 2,
                "jpx_domestic_stock_count": 3716,
            },
            "sources": {
                "daily_bars": {
                    "row_count": 460,
                    "ticker_count": 20,
                    "latest_value": "2026-07-03",
                }
            },
            "dimensions": [
                {
                    "id": "accuracy",
                    "label": "Accuracy",
                    "status": "needs_attention",
                    "score": 50,
                    "observations": ["Compares Yahoo-derived datasets with JPX."],
                    "recommended_actions": ["Review off-universe tickers."],
                },
                {
                    "id": "completeness",
                    "label": "Completeness",
                    "status": "needs_attention",
                    "score": 66.76,
                    "observations": ["Measures coverage against JPX domestic stocks."],
                    "recommended_actions": ["Backfill missing tickers."],
                },
            ],
        },
    )
    _write_json(
        root / "daily_bars_backfill_batch001_workflow.json",
        {
            "summary": {
                "current_stage": "data_entry",
                "template_rows": 50,
                "input_ready_rows": 0,
                "append_candidate_rows": 0,
                "active_slice_id": "daily-bars-batch001-slice001",
                "active_slice_ready_rows": 0,
                "active_slice_template_rows": 5,
                "active_slice_blockers": 45,
            },
            "links": {"batch001_slice001": "daily_bars_backfill_batch001_slice001.html"},
        },
    )
    _write_json(
        root / "daily_bars_backfill_batch001_intake_validation.json",
        {"summary": {"template_rows": 50, "ready_rows": 0, "blocker_count": 450}},
    )
    _write_json(
        root / "daily_bars_backfill_batch001_append_dry_run.json",
        {
            "summary": {
                "template_rows": 50,
                "append_candidate_rows": 0,
                "append_ready": False,
                "write_executed": False,
            }
        },
    )
    _write_json(
        root / "daily_bars_backfill_batch001_slice001.json",
        {"summary": {"slice_id": "daily-bars-batch001-slice001", "blockers": 45}},
    )
    _write_json(
        root / "daily_bars_backfill_batch001_slice001_intake_validation.json",
        {"summary": {"ready_rows": 0, "template_rows": 5, "issue_count": 45}},
    )

    payload = build_data_quality_sprint_review(
        DataQualitySprintReviewConfig(
            dashboard_root=root,
            generated_at="2026-07-05T04:00:00+09:00",
            mirror_dirs=(mirror,),
        )
    )

    assert payload["status"] == "ready"
    assert payload["summary"]["domestic_stock_count"] == 3716
    assert payload["summary"]["daily_bars_coverage_rate"] == 0.54
    assert payload["summary"]["active_slice_blockers"] == 45
    assert payload["summary"]["write_executed"] is False
    assert payload["summary"]["external_fetch_executed"] is False
    assert payload["summary"]["auto_trading"] is False
    assert payload["summary"]["call_real_api"] is False
    assert "Slice 001" in payload["summary"]["next_sprint_goal"]
    assert len(payload["quality_dimensions"]) == 2
    assert payload["process_steps"][0]["status"] == "complete"
    assert payload["process_steps"][1]["status"] == "active"
    assert (root / "data_quality_sprint_review.json").is_file()
    assert (root / "data_quality_sprint_review_dimensions.csv").is_file()
    assert (root / "data_quality_sprint_review_process.csv").is_file()
    assert (mirror / "data_quality_sprint_review.html").read_text(
        encoding="utf-8"
    ) == (root / "data_quality_sprint_review.html").read_text(encoding="utf-8")
    raw_json = (root / "data_quality_sprint_review.json").read_text(encoding="utf-8")
    assert all(ord(character) < 128 for character in raw_json)
    html = (root / "data_quality_sprint_review.html").read_text(encoding="utf-8")
    assert "\u7e5d" not in html
    assert "\ufffd" not in html
