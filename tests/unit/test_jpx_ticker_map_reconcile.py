from __future__ import annotations

import csv
import json
from pathlib import Path

from investment_assistant.webapi.jpx_ticker_map_reconcile import (
    TickerMapReconcileConfig,
    reconcile_ticker_data_map,
)


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_reconcile_ticker_map_applies_official_universe(tmp_path: Path) -> None:
    ticker_map = tmp_path / "ticker_data_map.csv"
    official = tmp_path / "official.csv"
    _write_csv(
        ticker_map,
        [
            {
                "ticker": "1301",
                "name": "Old Name",
                "segment": "Old Segment",
                "data_status": "complete",
                "past_price_history": "yes",
                "history_rows": "120",
                "history_period": "2026-01-01 - 2026-07-01",
                "current_price": "100",
                "price_as_of": "2026-07-01",
                "dividend_yield_pct": "1.0",
                "yield_as_of": "2026-07-01",
                "next_action": "compare_ready",
            },
            {
                "ticker": "9999",
                "name": "Extra",
                "segment": "Prime",
                "data_status": "complete",
                "past_price_history": "yes",
                "history_rows": "120",
                "history_period": "2026-01-01 - 2026-07-01",
                "current_price": "100",
                "price_as_of": "2026-07-01",
                "dividend_yield_pct": "1.0",
                "yield_as_of": "2026-07-01",
                "next_action": "compare_ready",
            },
        ],
        [
            "ticker",
            "name",
            "segment",
            "data_status",
            "past_price_history",
            "history_rows",
            "history_period",
            "current_price",
            "price_as_of",
            "dividend_yield_pct",
            "yield_as_of",
            "next_action",
        ],
    )
    _write_csv(
        official,
        [
            {"ticker": "1301", "name": "Official Name", "segment": "Prime"},
            {"ticker": "130A", "name": "New Official", "segment": "Growth"},
        ],
        ["ticker", "name", "segment"],
    )

    payload = reconcile_ticker_data_map(
        TickerMapReconcileConfig(
            ticker_map_path=ticker_map,
            official_snapshot_path=official,
            output_dir=tmp_path,
            apply=True,
            generated_at="2026-07-04T00:00:00+09:00",
        )
    )

    rows = list(csv.DictReader(ticker_map.open(encoding="utf-8")))
    assert payload["status"] == "fixed"
    assert payload["summary"]["extra_removed_count"] == 1
    assert payload["summary"]["missing_added_count"] == 1
    assert [row["ticker"] for row in rows] == ["1301", "130A"]
    assert rows[0]["name"] == "Official Name"
    assert rows[0]["current_price"] == "100"
    assert rows[1]["data_status"] == "missing"
    raw_json = ticker_map.with_suffix(".json").read_text(encoding="utf-8")
    assert all(ord(character) < 128 for character in raw_json)
    assert json.loads(raw_json)[1]["next_action"] == "collect_market_data"


def test_reconcile_ticker_map_report_only_does_not_edit_source(tmp_path: Path) -> None:
    ticker_map = tmp_path / "ticker_data_map.csv"
    official = tmp_path / "official.csv"
    _write_csv(
        ticker_map,
        [{"ticker": "9999", "name": "Extra", "segment": "Prime"}],
        ["ticker", "name", "segment"],
    )
    _write_csv(
        official,
        [{"ticker": "1301", "name": "Official", "segment": "Prime"}],
        ["ticker", "name", "segment"],
    )

    payload = reconcile_ticker_data_map(
        TickerMapReconcileConfig(
            ticker_map_path=ticker_map,
            official_snapshot_path=official,
            output_dir=tmp_path,
            apply=False,
        )
    )

    assert payload["status"] == "needs_apply"
    assert "9999" in ticker_map.read_text(encoding="utf-8")
