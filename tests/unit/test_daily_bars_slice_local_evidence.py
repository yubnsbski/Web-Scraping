from __future__ import annotations

import csv
import json
from pathlib import Path

from investment_assistant.webapi.daily_bars_slice_local_evidence import (
    DailyBarsSliceLocalEvidenceConfig,
    build_daily_bars_slice_local_evidence,
)


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_daily_bars_slice_local_evidence_keeps_template_unmodified(tmp_path: Path) -> None:
    root = tmp_path / "dashboard"
    docs = tmp_path / "local_docs" / "market"
    mirror = tmp_path / "dist" / "market-dashboard"
    root.mkdir(parents=True)
    docs.mkdir(parents=True)
    template = root / "daily_bars_backfill_batch001_slice001_input_template.csv"
    template_text = (
        "ticker,date,open,high,low,close,volume,source_provider,source_url,checked_at,note\n"
        "1419,,,,,,,,,,review only\n"
        "1429,,,,,,,,,,review only\n"
    )
    template.write_text(template_text, encoding="utf-8")
    (root / "daily_bars_backfill_batch001_slice001_readiness_backlog.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "summary": {
                    "slice_id": "daily-bars-batch001-slice001",
                    "blockers": 18,
                },
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        docs / "daily_bars.csv",
        [
            {
                "ticker": "1419",
                "date": "2026-07-02",
                "open": "100",
                "high": "110",
                "low": "95",
                "close": "105",
                "volume": "1000",
            },
            {
                "ticker": "1419",
                "date": "2026-07-03",
                "open": "106",
                "high": "112",
                "low": "101",
                "close": "108",
                "volume": "1200",
            },
            {
                "ticker": "1429",
                "date": "2026-07-03",
                "open": "200",
                "high": "205",
                "low": "198",
                "close": "202",
                "volume": "2300",
            },
        ],
        ["ticker", "date", "open", "high", "low", "close", "volume"],
    )
    _write_csv(
        docs / "current_prices.csv",
        [
            {
                "ticker": "1419",
                "price": "108",
                "as_of": "2026-07-03",
                "provider_id": "daily_bars_derived",
                "source_ref": "local_docs/market/daily_bars.csv",
                "note": "synced",
            },
            {
                "ticker": "1429",
                "price": "202",
                "as_of": "2026-07-03",
                "provider_id": "daily_bars_derived",
                "source_ref": "local_docs/market/daily_bars.csv",
                "note": "synced",
            },
        ],
        ["ticker", "price", "as_of", "provider_id", "source_ref", "note"],
    )
    _write_csv(
        docs / "yahoo_financials.csv",
        [{"ticker": "1419", "price": "108", "dps": "5", "dividend_yield_percent": "4.63"}],
        ["ticker", "price", "dps", "dividend_yield_percent"],
    )
    _write_csv(
        root / "yield_gap_batch_roadmap.csv",
        [
            {
                "ticker": "1419",
                "current_price": "108",
                "current_dividend_per_share": "5",
                "yield_pct": "4.63",
                "as_of": "2026-07-03",
                "source_ref": "local_docs/market/yahoo_financials.csv",
                "provider_id": "yahoo_finance_derived",
            }
        ],
        [
            "ticker",
            "current_price",
            "current_dividend_per_share",
            "yield_pct",
            "as_of",
            "source_ref",
            "provider_id",
        ],
    )

    payload = build_daily_bars_slice_local_evidence(
        DailyBarsSliceLocalEvidenceConfig(
            dashboard_root=root,
            daily_bars_path=docs / "daily_bars.csv",
            current_prices_path=docs / "current_prices.csv",
            yahoo_financials_path=docs / "yahoo_financials.csv",
            mirror_dirs=(mirror, docs),
            generated_at="2026-07-05T12:00:00+09:00",
        )
    )

    summary = payload["summary"]
    assert summary["status"] == "needs_attention"
    assert summary["local_ohlcv_candidate_rows"] == 2
    assert summary["review_queue_rows"] == 2
    assert summary["prepopulated_required_field_count"] == 14
    assert summary["remaining_review_field_count"] == 4
    assert summary["source_url_gap_count"] == 2
    assert summary["checked_at_gap_count"] == 2
    assert summary["append_ready_candidates"] == 0
    assert summary["input_template_autofill_allowed"] is False
    assert summary["readiness_backlog_blockers"] == 18
    assert payload["safe_flags"]["external_fetch_executed"] is False
    assert payload["safe_flags"]["auto_trading"] is False
    assert template.read_text(encoding="utf-8") == template_text
    assert payload["evidence_rows"][0]["ticker"] == "1419"
    assert payload["evidence_rows"][0]["latest_date"] == "2026-07-03"
    assert payload["evidence_rows"][0]["close"] == "108"
    assert all(row["can_fill_input_template"] is False for row in payload["field_matrix"])
    date_candidate = next(
        row
        for row in payload["field_matrix"]
        if row["ticker"] == "1419" and row["field"] == "date"
    )
    assert date_candidate["local_candidate_available"] is True
    assert (root / "daily_bars_backfill_batch001_slice001_local_evidence.html").exists()
    review_queue = list(
        csv.DictReader(
            (
                root
                / "daily_bars_backfill_batch001_slice001_local_evidence_review_queue.csv"
            ).open(encoding="utf-8")
        )
    )
    assert review_queue[0]["ticker"] == "1419"
    assert review_queue[0]["date"] == "2026-07-03"
    assert review_queue[0]["source_provider"] == "daily_bars_derived"
    assert review_queue[0]["source_url"] == ""
    assert review_queue[0]["checked_at"] == ""
    assert review_queue[0]["can_copy_to_input_template"] == "False"
    assert (mirror / "daily_bars_backfill_batch001_slice001_local_evidence.json").exists()
    assert (
        mirror / "daily_bars_backfill_batch001_slice001_local_evidence_review_queue.csv"
    ).exists()
    assert (docs / "daily_bars_backfill_batch001_slice001_local_evidence.csv").exists()
