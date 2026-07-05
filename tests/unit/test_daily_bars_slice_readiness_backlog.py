from __future__ import annotations

import json

from investment_assistant.webapi.daily_bars_slice_readiness_backlog import (
    DailyBarsSliceReadinessBacklogConfig,
    build_daily_bars_slice_readiness_backlog,
)


def test_build_daily_bars_slice_readiness_backlog_summarizes_blockers(tmp_path) -> None:
    root = tmp_path / "market-dashboard"
    mirror = tmp_path / "mirror"
    root.mkdir()
    validation = {
        "status": "blocked",
        "summary": {
            "generated_at": "2026-07-05T05:00:00+09:00",
            "status": "blocked",
            "slice_id": "daily-bars-batch001-slice001",
            "batch_id": "daily-bars-batch001",
            "ready_rows": 0,
            "template_rows": 2,
            "blockers": 4,
            "append_ready": False,
            "write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
        },
        "validation_rows": [
            {
                "slice_id": "daily-bars-batch001-slice001",
                "row_number": 2,
                "ticker": "1419",
                "name": "Alpha",
                "status": "needs_input",
                "issue_count": 3,
                "issues": "missing_date;missing_open;missing_source_url",
            },
            {
                "slice_id": "daily-bars-batch001-slice001",
                "row_number": 3,
                "ticker": "1429",
                "name": "Beta",
                "status": "needs_input",
                "issue_count": 1,
                "issues": "missing_date",
            },
        ],
        "field_completion": [
            {
                "slice_id": "daily-bars-batch001-slice001",
                "field": "date",
                "completed_rows": 0,
                "missing_rows": 2,
                "total_rows": 2,
                "completion_rate": 0,
            },
            {
                "slice_id": "daily-bars-batch001-slice001",
                "field": "open",
                "completed_rows": 1,
                "missing_rows": 1,
                "total_rows": 2,
                "completion_rate": 50,
            },
            {
                "slice_id": "daily-bars-batch001-slice001",
                "field": "source_url",
                "completed_rows": 1,
                "missing_rows": 1,
                "total_rows": 2,
                "completion_rate": 50,
            },
        ],
    }
    (root / "daily_bars_backfill_batch001_slice001_intake_validation.json").write_text(
        json.dumps(validation),
        encoding="utf-8",
    )

    payload = build_daily_bars_slice_readiness_backlog(
        DailyBarsSliceReadinessBacklogConfig(
            dashboard_root=root,
            generated_at="2026-07-05T05:10:00+09:00",
            mirror_dirs=(mirror,),
        )
    )

    summary = payload["summary"]
    assert payload["status"] == "blocked"
    assert summary["blockers"] == 4
    assert summary["blocked_ticker_count"] == 2
    assert summary["blocked_field_count"] == 3
    assert summary["append_ready"] is False
    assert summary["write_executed"] is False
    assert summary["external_fetch_executed"] is False
    assert summary["auto_trading"] is False
    assert summary["call_real_api"] is False
    assert payload["backlog_rows"][0]["field"] == "date"
    assert payload["backlog_rows"][0]["field_group"] == "timeliness"
    assert payload["backlog_rows"][2]["field_group"] == "source_evidence"
    assert payload["field_summary"][0]["blocking_issue_count"] == 2
    assert "Slice 001 backlog rows" in summary["next_sprint_goal"]

    html = root / "daily_bars_backfill_batch001_slice001_readiness_backlog.html"
    json_path = root / "daily_bars_backfill_batch001_slice001_readiness_backlog.json"
    csv_path = root / "daily_bars_backfill_batch001_slice001_readiness_backlog.csv"
    fields_path = (
        root / "daily_bars_backfill_batch001_slice001_readiness_backlog_field_summary.csv"
    )
    assert html.is_file()
    assert json_path.is_file()
    assert csv_path.is_file()
    assert fields_path.is_file()
    assert (mirror / html.name).read_text(encoding="utf-8") == html.read_text(
        encoding="utf-8"
    )
    raw_json = json_path.read_text(encoding="utf-8")
    assert raw_json.isascii()
    assert "\\u7e5d" not in html.read_text(encoding="utf-8")
    assert "\ufffd" not in html.read_text(encoding="utf-8")
