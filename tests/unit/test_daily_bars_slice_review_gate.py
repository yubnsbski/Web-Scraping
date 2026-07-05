from __future__ import annotations

import csv
from pathlib import Path

from investment_assistant.webapi.daily_bars_slice_review_gate import (
    DailyBarsSliceReviewGateConfig,
    build_daily_bars_slice_review_gate,
)


def _write_review_queue(path: Path) -> None:
    rows = [
        {
            "ticker": "1419",
            "date": "2026-07-03",
            "open": "100",
            "high": "110",
            "low": "95",
            "close": "105",
            "volume": "123400",
            "source_provider": "manual_review",
            "source_url": "https://example.test/source",
            "checked_at": "2026-07-05T12:00:00+09:00",
            "note": "reviewed",
            "candidate_source_ref": "local_docs/market/daily_bars.csv",
            "review_status": "reviewed",
            "can_copy_to_input_template": "true",
        },
        {
            "ticker": "1429",
            "date": "2026-07-03",
            "open": "200",
            "high": "205",
            "low": "198",
            "close": "202",
            "volume": "2300",
            "source_provider": "manual_review",
            "source_url": "",
            "checked_at": "",
            "note": "needs source",
            "candidate_source_ref": "local_docs/market/daily_bars.csv",
            "review_status": "needs_source_review",
            "can_copy_to_input_template": "False",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_daily_bars_slice_review_gate_blocks_missing_source_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dashboard"
    mirror = tmp_path / "dist" / "market-dashboard"
    docs = tmp_path / "local_docs" / "market"
    root.mkdir(parents=True)
    review_queue = root / "daily_bars_backfill_batch001_slice001_local_evidence_review_queue.csv"
    _write_review_queue(review_queue)

    payload = build_daily_bars_slice_review_gate(
        DailyBarsSliceReviewGateConfig(
            dashboard_root=root,
            mirror_dirs=(mirror, docs),
            generated_at="2026-07-05T12:30:00+09:00",
        )
    )

    summary = payload["summary"]
    assert summary["status"] == "blocked"
    assert summary["review_queue_rows"] == 2
    assert summary["ready_rows"] == 1
    assert summary["field_blockers"] == 2
    assert summary["copy_approval_blockers"] == 1
    assert summary["blockers"] == 3
    assert summary["copy_to_input_template_ready"] is False
    assert summary["write_executed"] is False
    assert payload["validation_rows"][0]["status"] == "ready"
    assert payload["validation_rows"][1]["issues"] == (
        "missing_source_url;missing_checked_at;copy_not_approved"
    )
    assert any(row["issue"] == "missing_source_url" for row in payload["issue_rows"])
    assert (root / "daily_bars_backfill_batch001_slice001_review_gate.html").exists()
    assert (root / "daily_bars_backfill_batch001_slice001_review_gate_validation.csv").exists()
    assert (mirror / "daily_bars_backfill_batch001_slice001_review_gate.json").exists()
    assert (docs / "daily_bars_backfill_batch001_slice001_review_gate.csv").exists()
