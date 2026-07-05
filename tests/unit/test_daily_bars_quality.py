from __future__ import annotations

import csv
import json
from pathlib import Path

from investment_assistant.webapi.daily_bars_quality import SliceBuildConfig, build_daily_bars_slice


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "batch_id",
        "batch_rank",
        "queue_rank",
        "priority",
        "ticker",
        "name",
        "segment_bucket",
        "segment",
        "has_current_price",
        "has_market_financials",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _manifest_row(ticker: str = "1419") -> dict[str, str]:
    return {
        "batch_id": "daily-bars-batch001",
        "batch_rank": "1",
        "queue_rank": "1",
        "priority": "P0",
        "ticker": ticker,
        "name": "Sample Name",
        "segment_bucket": "Prime",
        "segment": "Prime domestic stock",
        "has_current_price": "True",
        "has_market_financials": "True",
    }


def test_blank_slice_is_blocked_and_no_write(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    _write_manifest(manifest, [_manifest_row("1419"), _manifest_row("1429")])

    payload = build_daily_bars_slice(
        SliceBuildConfig(
            batch_manifest_path=manifest,
            output_dir=tmp_path,
            slice_size=2,
            generated_at="2026-07-04T00:00:00+09:00",
        )
    )

    summary = payload["summary"]
    assert summary["status"] == "blocked"
    assert summary["ready_rows"] == 0
    assert summary["blockers"] == 18
    assert summary["append_candidate_rows"] == 0
    assert summary["write_executed"] is False
    assert summary["external_fetch_executed"] is False
    assert summary["auto_trading"] is False

    generated = json.loads((tmp_path / "daily_bars_backfill_batch001_slice001.json").read_text())
    assert generated["summary"]["blockers"] == 18
    assert (tmp_path / "daily_bars_backfill_batch001_slice001_input_template.csv").exists()
    preview_rows = list(
        csv.DictReader(
            (tmp_path / "daily_bars_backfill_batch001_slice001_append_preview.csv").open()
        )
    )
    assert preview_rows == []


def test_ready_input_becomes_append_preview_without_writing_source_data(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    _write_manifest(manifest, [_manifest_row()])
    input_path = tmp_path / "daily_bars_backfill_batch001_slice001_input_template.csv"
    input_path.write_text(
        "ticker,date,open,high,low,close,volume,source_provider,source_url,checked_at,note\n"
        "1419,2026-07-03,100,110,90,105,123400,manual,https://example.test/source,2026-07-04T00:00:00+09:00,reviewed\n",
        encoding="utf-8",
    )
    source_daily_bars = tmp_path / "daily_bars.csv"
    source_daily_bars.write_text("ticker,date,open,high,low,close,volume\n", encoding="utf-8")

    payload = build_daily_bars_slice(
        SliceBuildConfig(
            batch_manifest_path=manifest,
            output_dir=tmp_path,
            slice_size=1,
            generated_at="2026-07-04T00:00:00+09:00",
        )
    )

    summary = payload["summary"]
    assert summary["status"] == "ready"
    assert summary["ready_rows"] == 1
    assert summary["blockers"] == 0
    assert summary["append_candidate_rows"] == 1
    assert summary["append_ready"] is True
    assert (
        source_daily_bars.read_text(encoding="utf-8") == "ticker,date,open,high,low,close,volume\n"
    )

    preview_rows = list(
        csv.DictReader(
            (tmp_path / "daily_bars_backfill_batch001_slice001_append_preview.csv").open()
        )
    )
    assert preview_rows[0]["ticker"] == "1419"
    assert preview_rows[0]["close"] == "105"


def test_generated_json_is_ascii_escaped_for_legacy_powershell(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    row = _manifest_row()
    row["name"] = "タマホーム"
    row["segment"] = "プライム（内国株式）"
    _write_manifest(manifest, [row])

    build_daily_bars_slice(
        SliceBuildConfig(
            batch_manifest_path=manifest,
            output_dir=tmp_path,
            slice_size=1,
            generated_at="2026-07-04T00:00:00+09:00",
        )
    )

    raw_json = (tmp_path / "daily_bars_backfill_batch001_slice001.json").read_text(
        encoding="utf-8"
    )
    loaded = json.loads(raw_json)
    assert all(ord(character) < 128 for character in raw_json)
    assert "\\u30bf" in raw_json
    assert loaded["tickers"][0]["name"] == "タマホーム"


def test_invalid_ohlc_and_source_evidence_are_blockers(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    _write_manifest(manifest, [_manifest_row()])
    (tmp_path / "daily_bars_backfill_batch001_slice001_input_template.csv").write_text(
        "ticker,date,open,high,low,close,volume,source_provider,source_url,checked_at,note\n"
        "1419,20260703,100,95,98,105,1.5,manual,not-a-url,nope,reviewed\n",
        encoding="utf-8",
    )

    payload = build_daily_bars_slice(
        SliceBuildConfig(batch_manifest_path=manifest, output_dir=tmp_path, slice_size=1)
    )

    validation = payload["links"]["intake_validation"].replace(".html", ".json")
    intake = json.loads((tmp_path / validation).read_text())
    issues = intake["validation_rows"][0]["issues"]
    assert "invalid_date" in issues
    assert "invalid_checked_at" in issues
    assert "invalid_source_url" in issues
    assert "invalid_volume" in issues
    assert "invalid_high_below_price" in issues
    assert payload["summary"]["append_candidate_rows"] == 0
