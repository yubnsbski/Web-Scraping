"""Unit coverage for the read-only data inventory (webapi.data_status).

The 550-line module had no dedicated test file; this locks the freshness/status
logic, the latest-value/unique-value helpers, and the top-level shapes. Pure /
read-only — uses the bundled sample CSV and non-existent paths.
"""

from __future__ import annotations

from investment_assistant.webapi import data_status as ds

_SAMPLE = "examples/financials_sample.csv"
_LATEST_COLUMNS = ("price_as_of", "as_of", "date", "period_end", "fiscal_year")


def test_status_for_existing_empty_ready_stale() -> None:
    assert ds._status_for_existing({"age_hours": 1.0, "freshness_days": 3}, row_count=0) == "empty"
    assert ds._status_for_existing({"age_hours": 1.0, "freshness_days": 3}, row_count=5) == "ready"
    stale = ds._status_for_existing({"age_hours": 3 * 24 + 1, "freshness_days": 3}, row_count=5)
    assert stale == "stale"


def test_latest_value_picks_lexicographic_max_iso_date() -> None:
    rows = [{"date": "2026-06-10"}, {"date": "2026-06-15"}, {"date": "2026-06-12"}]
    assert ds._latest_value(rows, _LATEST_COLUMNS) == "2026-06-15"


def test_latest_value_uses_first_non_empty_column_and_none_when_absent() -> None:
    # price_as_of takes priority over date within a row.
    assert ds._latest_value([{"price_as_of": "2026-06-20", "date": "2026-06-01"}],
                            ("price_as_of", "date")) == "2026-06-20"
    assert ds._latest_value([{"x": "1"}], ("date",)) is None
    assert ds._latest_value([], _LATEST_COLUMNS) is None


def test_unique_values_dedupes_across_candidate_columns() -> None:
    rows = [{"ticker": "8306"}, {"code": "7203"}, {"ticker": "8306"}, {"ticker": ""}]
    assert ds._unique_values(rows, ("ticker", "code")) == {"8306", "7203"}


def test_data_status_marks_present_and_missing_datasets() -> None:
    result = ds.data_status(
        {
            "financials_csv": _SAMPLE,
            "market_financials_path": "local_docs/_nope_mf.csv",
            "daily_bars_path": "local_docs/_nope_bars.csv",
            "price_inbox_path": "local_docs/_nope_inbox.csv",
            "edinet_financials_path": "local_docs/_nope_edinet.csv",
            "rag_db_path": "local_docs/_nope.sqlite",
        }
    )
    by_id = {d["id"]: d for d in result["datasets"]}

    selected = by_id["selected_financials"]
    assert selected["status"] == "ready" and selected["exists"] is True
    assert selected["row_count"] == 10 and selected["ticker_count"] == 2

    missing = by_id["market_financials"]
    assert missing["status"] == "missing" and missing["exists"] is False
    assert missing["required"] is False

    assert result["status"] in {"ready", "stale", "attention"}
    assert result["summary"]["missing_count"] >= 1
    assert result["auto_trading"] is False


def test_financials_preview_missing_and_present() -> None:
    assert ds.financials_preview({"financials_csv": "local_docs/_none.csv"})["status"] == "missing"

    preview = ds.financials_preview({"financials_csv": _SAMPLE})
    assert preview["status"] == "ready"
    assert preview["company_count"] == 2 and preview["row_count"] == 10
