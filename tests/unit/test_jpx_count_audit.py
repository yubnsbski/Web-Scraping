from __future__ import annotations

import csv
import json
from pathlib import Path

from investment_assistant.webapi.jpx_count_audit import JpxCountAuditConfig, build_jpx_count_audit


def _write_ticker_map(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["ticker", "name", "segment", "data_status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_review(path: Path, domestic_stock_count: int) -> None:
    path.write_text(
        json.dumps({"summary": {"domestic_stock_count": domestic_stock_count}}),
        encoding="utf-8",
    )


def test_jpx_count_audit_passes_when_local_denominators_match(tmp_path: Path) -> None:
    _write_ticker_map(
        tmp_path / "ticker_data_map.csv",
        [
            {
                "ticker": "1301",
                "name": "Kyokuyo",
                "segment": "Prime domestic stock \u5185\u56fd\u682a\u5f0f",
                "data_status": "complete",
            },
            {
                "ticker": "130A",
                "name": "Sample",
                "segment": "Growth domestic stock \u5185\u56fd\u682a\u5f0f",
                "data_status": "complete",
            },
        ],
    )
    _write_review(tmp_path / "data_quality_sprint_review.json", 2)
    (tmp_path / "market_dashboard_entry.html").write_text("JPX 5 / domestic 2", encoding="utf-8")

    payload = build_jpx_count_audit(
        JpxCountAuditConfig(
            dashboard_root=tmp_path,
            expected_listed_issues=5,
            expected_domestic_stock_issues=2,
            expected_listed_companies=4,
            generated_at="2026-07-04T00:00:00+09:00",
        )
    )

    assert payload["status"] == "pass"
    assert payload["summary"]["local_ticker_map_rows"] == 2
    raw_json = (tmp_path / "jpx_listed_issue_count_audit.json").read_text(encoding="utf-8")
    assert all(ord(character) < 128 for character in raw_json)


def test_jpx_count_audit_flags_duplicate_and_count_mismatch(tmp_path: Path) -> None:
    _write_ticker_map(
        tmp_path / "ticker_data_map.csv",
        [
            {
                "ticker": "1301",
                "name": "Kyokuyo",
                "segment": "Prime domestic stock \u5185\u56fd\u682a\u5f0f",
                "data_status": "complete",
            },
            {
                "ticker": "1301",
                "name": "Kyokuyo Duplicate",
                "segment": "Prime domestic stock \u5185\u56fd\u682a\u5f0f",
                "data_status": "complete",
            },
        ],
    )
    _write_review(tmp_path / "data_quality_sprint_review.json", 1)
    (tmp_path / "market_dashboard_entry.html").write_text("JPX 5 only", encoding="utf-8")

    payload = build_jpx_count_audit(
        JpxCountAuditConfig(
            dashboard_root=tmp_path,
            expected_listed_issues=5,
            expected_domestic_stock_issues=1,
            expected_listed_companies=4,
        )
    )

    checks = {row["check_id"]: row for row in payload["checks"]}
    assert payload["status"] == "needs_attention"
    assert checks["ticker_map_rows_match_domestic_stock_issues"]["status"] == "fail"
    assert checks["no_duplicate_tickers_in_ticker_map"]["actual"] == 1
    assert payload["duplicate_tickers"] == ["1301"]
