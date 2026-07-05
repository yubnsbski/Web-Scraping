from __future__ import annotations

import csv
import json
from pathlib import Path

from investment_assistant.webapi.data_gap_dashboard import (
    DataGapDashboardConfig,
    build_data_gap_dashboard,
)


def _write_ticker_map(path: Path) -> None:
    fieldnames = [
        "ticker",
        "name",
        "segment",
        "current_price",
        "price_as_of",
        "dividend_yield_pct",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "ticker": "1301",
                    "name": "Kyokuyo",
                    "segment": "Prime",
                    "current_price": "100",
                    "price_as_of": "2026-07-01",
                    "dividend_yield_pct": "1.0",
                },
                {
                    "ticker": "130A",
                    "name": "Missing Yield",
                    "segment": "Growth",
                    "current_price": "200",
                    "price_as_of": "2026-07-01",
                    "dividend_yield_pct": "",
                },
                {
                    "ticker": "575A",
                    "name": "Missing Price",
                    "segment": "Growth",
                    "current_price": "",
                    "price_as_of": "",
                    "dividend_yield_pct": "",
                },
            ]
        )


def test_data_gap_dashboard_uses_reconciled_ticker_map_denominator(tmp_path: Path) -> None:
    ticker_map = tmp_path / "ticker_data_map.csv"
    _write_ticker_map(ticker_map)

    payload = build_data_gap_dashboard(
        DataGapDashboardConfig(
            ticker_map_path=ticker_map,
            output_dir=tmp_path,
            generated_at="2026-07-05T00:00:00+09:00",
        )
    )

    summary = payload["summary"]
    assert summary["universe_count"] == 3
    assert summary["price_count"] == 2
    assert summary["yield_ready_count"] == 1
    assert summary["yield_gap_count"] == 2
    assert summary["source_data_write_executed"] is False
    assert payload["priority_gaps"][0]["ticker"] == "130A"
    raw_json = (tmp_path / "data_gap_dashboard.json").read_text(encoding="utf-8")
    assert all(ord(character) < 128 for character in raw_json)
    assert json.loads(raw_json)["summary"]["universe_count"] == 3


def test_data_gap_dashboard_writes_all_artifact_formats(tmp_path: Path) -> None:
    ticker_map = tmp_path / "ticker_data_map.csv"
    _write_ticker_map(ticker_map)

    build_data_gap_dashboard(
        DataGapDashboardConfig(ticker_map_path=ticker_map, output_dir=tmp_path)
    )

    assert (tmp_path / "data_gap_dashboard.csv").exists()
    html = (tmp_path / "data_gap_dashboard.html").read_text(encoding="utf-8")
    assert "Yield coverage" in html
    assert "33.33%" in html
    assert (tmp_path / "data_gap_dashboard.md").exists()
