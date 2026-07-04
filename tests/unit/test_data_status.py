"""Unit coverage for the read-only data inventory (webapi.data_status).

The 550-line module had no dedicated test file; this locks the freshness/status
logic, the latest-value/unique-value helpers, and the top-level shapes. Pure /
read-only — uses the bundled sample CSV and non-existent paths.
"""

from __future__ import annotations

from pathlib import Path

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
    assert (
        ds._latest_value(
            [{"price_as_of": "2026-06-20", "date": "2026-06-01"}], ("price_as_of", "date")
        )
        == "2026-06-20"
    )
    assert ds._latest_value([{"x": "1"}], ("date",)) is None
    assert ds._latest_value([], _LATEST_COLUMNS) is None


def test_unique_values_dedupes_across_candidate_columns() -> None:
    rows = [{"ticker": "8306"}, {"code": "7203"}, {"ticker": "8306"}, {"ticker": ""}]
    assert ds._unique_values(rows, ("ticker", "code")) == {"8306", "7203"}


def test_data_status_reports_jpx_and_company_master_counts(tmp_path: Path) -> None:
    jpx = tmp_path / "listed_issues.csv"
    jpx.write_text(
        "日付,コード,銘柄名,市場・商品区分,33業種区分\n"
        "20260630,1301,極洋,プライム（内国株式）,水産・農林業\n"
        "20260630,1305,ETF,ETF・ETN,-\n",
        encoding="utf-8",
    )
    master = tmp_path / "company_master.csv"
    master.write_text(
        "ticker,name,market_segment,market_segment_raw,sector,as_of,entity_type,"
        "is_company,is_domestic_stock,is_prime,is_standard,is_growth,is_nikkei225,"
        "has_financials,financial_periods,source_ref\n"
        "1301,極洋,プライム（国内株式）,プライム（内国株式）,水産・農林業,"
        "20260630,domestic_stock,true,true,true,false,false,false,false,0,local_docs/jpx/listed_issues.csv\n"
        "1305,ETF,ETF・ETN,ETF・ETN,-,20260630,etf_etn,false,false,false,false,false,false,false,0,local_docs/jpx/listed_issues.csv\n",
        encoding="utf-8",
    )

    result = ds.data_status(
        {
            "financials_csv": _SAMPLE,
            "jpx_listed_issues_path": str(jpx),
            "company_master_path": str(master),
            "market_financials_path": str(tmp_path / "missing_market.csv"),
            "daily_bars_path": str(tmp_path / "missing_bars.csv"),
            "price_inbox_path": str(tmp_path / "missing_inbox.csv"),
            "edinet_financials_path": str(tmp_path / "missing_edinet.csv"),
            "rag_db_path": str(tmp_path / "missing.sqlite"),
            "market_log_path": str(tmp_path / "missing.log"),
        }
    )
    by_id = {str(item["id"]): item for item in result["datasets"]}

    assert by_id["jpx_listed_issues"]["row_count"] == 2
    assert by_id["jpx_listed_issues"]["ticker_count"] == 2
    assert by_id["jpx_listed_issues"]["latest_value"] == "20260630"
    assert by_id["company_master"]["row_count"] == 2
    assert by_id["company_master"]["ticker_count"] == 2
    assert by_id["company_master"]["latest_value"] == "20260630"


def test_data_status_marks_daily_bars_partial_when_coverage_is_low(tmp_path: Path) -> None:
    market = tmp_path / "yahoo_financials.csv"
    market.write_text(
        "ticker,name,price,per,pbr,dps,dividend_yield\n"
        + "".join(f"{1000 + index},Name{index},100,10,1,3,3.0\n" for index in range(100)),
        encoding="utf-8",
    )
    bars = tmp_path / "daily_bars.csv"
    bars.write_text(
        "ticker,date,open,high,low,close,volume\n"
        "1000,2026-06-15,100,110,90,105,1000\n"
        "1001,2026-06-15,100,110,90,105,1000\n"
        "1002,2026-06-15,100,110,90,105,1000\n",
        encoding="utf-8-sig",
    )

    result = ds.data_status(
        {
            "financials_csv": _SAMPLE,
            "market_financials_path": str(market),
            "daily_bars_path": str(bars),
            "price_inbox_path": str(tmp_path / "missing_inbox.csv"),
            "edinet_financials_path": str(tmp_path / "missing_edinet.csv"),
            "rag_db_path": str(tmp_path / "missing.sqlite"),
            "market_log_path": str(tmp_path / "missing.log"),
        }
    )
    by_id = {str(item["id"]): item for item in result["datasets"]}

    daily = by_id["daily_bars"]
    assert daily["status"] == "partial"
    assert daily["coverage_reference_ticker_count"] == 100
    assert daily["coverage_ticker_count"] == 3
    assert daily["coverage_percent"] == 3.0
    assert result["status"] == "needs_attention"
    assert result["summary"]["partial_count"] == 1

    actions = {str(item["id"]): item for item in result["actions"]}
    daily_action = actions["refresh_daily_bars"]
    assert daily_action["safe_to_run"] is True
    assert daily_action["recommended_scope"] == "domestic"
    assert daily_action["recommended_max_count"] == 50
    assert daily_action["recommended_range"] == "1mo"
    assert "カバー率" in str(daily_action["reason"])


def test_data_status_offers_optional_daily_bars_expansion_when_ready_but_narrow(
    tmp_path: Path,
) -> None:
    market = tmp_path / "yahoo_financials.csv"
    market.write_text(
        "ticker,name,price,per,pbr,dps,dividend_yield\n"
        + "".join(f"{1000 + index},Name{index},100,10,1,3,3.0\n" for index in range(300)),
        encoding="utf-8",
    )
    bars = tmp_path / "daily_bars.csv"
    bars.write_text(
        "ticker,date,open,high,low,close,volume\n"
        + "".join(f"{1000 + index},2026-06-15,100,110,90,105,1000\n" for index in range(60)),
        encoding="utf-8-sig",
    )

    result = ds.data_status(
        {
            "financials_csv": _SAMPLE,
            "market_financials_path": str(market),
            "daily_bars_path": str(bars),
            "price_inbox_path": str(tmp_path / "missing_inbox.csv"),
            "edinet_financials_path": str(tmp_path / "missing_edinet.csv"),
            "rag_db_path": str(tmp_path / "missing.sqlite"),
            "market_log_path": str(tmp_path / "missing.log"),
        }
    )
    by_id = {str(item["id"]): item for item in result["datasets"]}
    assert by_id["daily_bars"]["status"] == "ready"
    assert result["status"] == "ready"

    actions = {str(item["id"]): item for item in result["actions"]}
    expand = actions["expand_daily_bars"]
    assert expand["optional"] is True
    assert expand["safe_to_run"] is True
    assert expand["recommended_scope"] == "domestic"
    assert expand["recommended_max_count"] == 110
    assert expand["recommended_range"] == "1mo"


def test_price_inbox_action_is_optional_for_manual_csv_flow(tmp_path: Path) -> None:
    result = ds.data_status(
        {
            "financials_csv": _SAMPLE,
            "market_financials_path": str(tmp_path / "missing_market.csv"),
            "daily_bars_path": str(tmp_path / "missing_bars.csv"),
            "price_inbox_path": str(tmp_path / "missing_inbox.csv"),
            "edinet_financials_path": str(tmp_path / "missing_edinet.csv"),
            "rag_db_path": str(tmp_path / "missing.sqlite"),
            "market_log_path": str(tmp_path / "missing.log"),
        }
    )

    actions = {str(item["id"]): item for item in result["actions"]}
    inbox = actions["check_price_inbox"]
    assert inbox["safe_to_run"] is True
    assert inbox["optional"] is True
    assert inbox["priority"] > actions["refresh_market_financials"]["priority"]
    assert "使う場合だけ" in str(inbox["reason"])


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

    assert result["status"] in {"ready", "stale", "needs_attention"}
    assert result["summary"]["missing_count"] >= 1
    assert result["auto_trading"] is False


def test_financials_preview_missing_and_present() -> None:
    assert ds.financials_preview({"financials_csv": "local_docs/_none.csv"})["status"] == "missing"

    preview = ds.financials_preview({"financials_csv": _SAMPLE})
    assert preview["status"] == "ready"
    assert preview["company_count"] == 2 and preview["row_count"] == 10


def test_data_quality_profile_reports_six_dimensions_and_jpx_gaps(tmp_path: Path) -> None:
    date_col = "\u65e5\u4ed8"
    code_col = "\u30b3\u30fc\u30c9"
    name_col = "\u9283\u67c4\u540d"
    segment_col = "\u5e02\u5834\u30fb\u5546\u54c1\u533a\u5206"
    sector_col = "33\u696d\u7a2e\u533a\u5206"

    jpx = tmp_path / "listed_issues.csv"
    jpx.write_text(
        f'"{date_col}","{code_col}","{name_col}","{segment_col}","{sector_col}"\n'
        f'"20260630","1301","Kyokuyo","\u30d7\u30e9\u30a4\u30e0\uff08\u5185\u56fd\u682a\u5f0f\uff09","Foods"\n'
        '"20260630","1302","Domestic Missing",'
        f'"\u30b9\u30bf\u30f3\u30c0\u30fc\u30c9\uff08\u5185\u56fd\u682a\u5f0f\uff09","Foods"\n'
        f'"20260630","1305","ETF","ETF\u30fbETN","-"\n',
        encoding="utf-8",
    )
    master = tmp_path / "company_master.csv"
    master.write_text(
        "ticker,name,market_segment_raw,as_of,is_domestic_stock\n"
        "1301,Kyokuyo,Prime domestic,20260630,true\n"
        "1302,Domestic Missing,Standard domestic,20260630,true\n"
        "1305,ETF,ETF,20260630,false\n",
        encoding="utf-8",
    )
    universe = tmp_path / "domestic_universe.csv"
    universe.write_text(
        "ticker,name,as_of\n1301,Kyokuyo,20260630\n1302,Domestic Missing,20260630\n",
        encoding="utf-8",
    )
    prices = tmp_path / "current_prices.csv"
    prices.write_text(
        "ticker,price,as_of\n1301,100,2026-07-01\n9999,10,2026-07-01\n",
        encoding="utf-8",
    )
    financials = tmp_path / "yahoo_financials.csv"
    financials.write_text("ticker,name,price\n1301,Kyokuyo,100\n", encoding="utf-8")
    bars = tmp_path / "daily_bars.csv"
    bars.write_text(
        "ticker,date,open,high,low,close,volume\n"
        "1301,2026-07-01,1,1,1,1,100\n"
        "9999,2026-07-01,1,1,1,1,100\n",
        encoding="utf-8-sig",
    )

    result = ds.data_quality_profile(
        {
            "jpx_listed_issues_path": str(jpx),
            "company_master_path": str(master),
            "domestic_universe_path": str(universe),
            "current_prices_path": str(prices),
            "market_financials_path": str(financials),
            "daily_bars_path": str(bars),
        }
    )
    dimensions = {str(item["id"]): item for item in result["dimensions"]}

    assert result["status"] == "needs_attention"
    assert result["summary"]["dimension_count"] == 6
    assert result["summary"]["jpx_all_count"] == 3
    assert result["summary"]["jpx_domestic_stock_count"] == 2
    assert dimensions["accuracy"]["metrics"]["current_prices_outside_jpx_all_count"] == 1
    assert dimensions["completeness"]["metrics"]["current_prices_missing_count"] == 1
    assert dimensions["completeness"]["metrics"]["market_financials_missing_count"] == 1
    assert dimensions["consistency"]["status"] == "pass"
    assert dimensions["validity"]["status"] == "pass"
    assert result["write_executed"] is False
    assert result["external_fetch_executed"] is False
    assert result["auto_trading"] is False
    assert result["call_real_api"] is False


def test_data_quality_profile_uniqueness_flags_duplicate_rows(tmp_path: Path) -> None:
    company = tmp_path / "company_master.csv"
    company.write_text(
        "ticker,name,market_segment_raw,as_of,is_domestic_stock\n"
        "1301,Kyokuyo,Prime domestic,20260630,true\n"
        "1301,Kyokuyo Dup,Prime domestic,20260630,true\n"
        "1302,Other,Prime domestic,20260630,true\n",
        encoding="utf-8",
    )
    bars = tmp_path / "daily_bars.csv"
    bars.write_text(
        "ticker,date,open,high,low,close,volume\n"
        "1301,2026-07-01,1,1,1,1,100\n"
        "1301,2026-07-01,2,2,2,2,200\n"
        "1302,2026-07-01,1,1,1,1,100\n",
        encoding="utf-8-sig",
    )

    result = ds.data_quality_profile(
        {
            "jpx_listed_issues_path": str(tmp_path / "no_jpx.csv"),
            "company_master_path": str(company),
            "domestic_universe_path": str(tmp_path / "no_universe.csv"),
            "current_prices_path": str(tmp_path / "no_prices.csv"),
            "market_financials_path": str(tmp_path / "no_market.csv"),
            "daily_bars_path": str(bars),
        }
    )
    dimensions = {str(item["id"]): item for item in result["dimensions"]}

    assert dimensions["uniqueness"]["status"] == "needs_attention"
    assert dimensions["uniqueness"]["metrics"]["company_master_duplicate_ticker_count"] > 0
    assert dimensions["uniqueness"]["metrics"]["daily_bars_duplicate_ticker_date_count"] > 0


def test_data_quality_profile_timeliness_flags_missing_dataset(tmp_path: Path) -> None:
    jpx = tmp_path / "listed_issues.csv"
    jpx.write_text(
        "日付,コード,銘柄名,市場・商品区分,33業種区分\n"
        "20260630,1301,Kyokuyo,プライム（内国株式）,Foods\n",
        encoding="utf-8",
    )
    universe = tmp_path / "domestic_universe.csv"
    universe.write_text("ticker,name,as_of\n1301,Kyokuyo,20260630\n", encoding="utf-8")
    prices = tmp_path / "current_prices.csv"
    prices.write_text("ticker,price,as_of\n1301,100,2026-07-01\n", encoding="utf-8")
    financials = tmp_path / "yahoo_financials.csv"
    financials.write_text("ticker,name,price\n1301,Kyokuyo,100\n", encoding="utf-8")
    bars = tmp_path / "daily_bars.csv"
    bars.write_text(
        "ticker,date,open,high,low,close,volume\n1301,2026-07-01,1,1,1,1,100\n",
        encoding="utf-8-sig",
    )

    result = ds.data_quality_profile(
        {
            "jpx_listed_issues_path": str(jpx),
            "company_master_path": str(tmp_path / "no_company_master.csv"),
            "domestic_universe_path": str(universe),
            "current_prices_path": str(prices),
            "market_financials_path": str(financials),
            "daily_bars_path": str(bars),
        }
    )
    dimensions = {str(item["id"]): item for item in result["dimensions"]}

    assert dimensions["timeliness"]["status"] == "needs_attention"
    assert "company_master" in dimensions["timeliness"]["metrics"]["stale_or_missing_datasets"]


def test_data_quality_profile_validity_flags_invalid_ticker_but_not_new_style_code(
    tmp_path: Path,
) -> None:
    prices = tmp_path / "current_prices.csv"
    prices.write_text(
        "ticker,price,as_of\n"
        "1301,100,2026-07-01\n"
        "130A,50,2026-07-01\n"
        "12,999,2026-07-01\n",
        encoding="utf-8",
    )

    result = ds.data_quality_profile(
        {
            "jpx_listed_issues_path": str(tmp_path / "no_jpx.csv"),
            "company_master_path": str(tmp_path / "no_company_master.csv"),
            "domestic_universe_path": str(tmp_path / "no_universe.csv"),
            "current_prices_path": str(prices),
            "market_financials_path": str(tmp_path / "no_market.csv"),
            "daily_bars_path": str(tmp_path / "no_bars.csv"),
        }
    )
    dimensions = {str(item["id"]): item for item in result["dimensions"]}
    validity = dimensions["validity"]

    assert validity["status"] == "needs_attention"
    assert validity["metrics"]["current_prices_invalid_ticker_count"] == 1
    samples = validity["metrics"]["invalid_ticker_samples"]["current_prices"]
    assert "12" in samples
    assert "130A" not in samples


def test_data_quality_profile_consistency_flags_missing_and_extra_codes(tmp_path: Path) -> None:
    jpx = tmp_path / "listed_issues.csv"
    jpx.write_text(
        "日付,コード,銘柄名,市場・商品区分,33業種区分\n"
        "20260630,1301,Kyokuyo,プライム（内国株式）,Foods\n"
        "20260630,1302,Domestic Missing,スタンダード（内国株式）,Foods\n"
        "20260630,1305,ETF,ETF・ETN,-\n",
        encoding="utf-8",
    )
    master = tmp_path / "company_master.csv"
    master.write_text(
        "ticker,name,market_segment_raw,as_of,is_domestic_stock\n"
        "1301,Kyokuyo,Prime domestic,20260630,true\n"
        "1305,ETF,ETF,20260630,false\n"
        "9999,Extra Co,Prime domestic,20260630,true\n",
        encoding="utf-8",
    )
    universe = tmp_path / "domestic_universe.csv"
    universe.write_text(
        "ticker,name,as_of\n1301,Kyokuyo,20260630\n8888,Extra Universe,20260630\n",
        encoding="utf-8",
    )

    result = ds.data_quality_profile(
        {
            "jpx_listed_issues_path": str(jpx),
            "company_master_path": str(master),
            "domestic_universe_path": str(universe),
            "current_prices_path": str(tmp_path / "no_prices.csv"),
            "market_financials_path": str(tmp_path / "no_market.csv"),
            "daily_bars_path": str(tmp_path / "no_bars.csv"),
        }
    )
    dimensions = {str(item["id"]): item for item in result["dimensions"]}
    consistency = dimensions["consistency"]

    assert consistency["status"] == "needs_attention"
    assert consistency["metrics"]["company_master_missing_jpx_all_count"] == 1
    assert consistency["metrics"]["company_master_extra_vs_jpx_all_count"] == 1
    assert consistency["metrics"]["domestic_universe_missing_jpx_domestic_count"] == 1
    assert consistency["metrics"]["domestic_universe_extra_vs_jpx_domestic_count"] == 1


def test_data_quality_profile_handles_all_datasets_missing(tmp_path: Path) -> None:
    result = ds.data_quality_profile(
        {
            "jpx_listed_issues_path": str(tmp_path / "no_jpx.csv"),
            "company_master_path": str(tmp_path / "no_company_master.csv"),
            "domestic_universe_path": str(tmp_path / "no_universe.csv"),
            "current_prices_path": str(tmp_path / "no_prices.csv"),
            "market_financials_path": str(tmp_path / "no_market.csv"),
            "daily_bars_path": str(tmp_path / "no_bars.csv"),
        }
    )
    dimensions = {str(item["id"]): item for item in result["dimensions"]}
    completeness = dimensions["completeness"]["metrics"]

    assert result["summary"]["dimension_count"] == 6
    assert completeness["current_prices_coverage_percent"] == 0.0
    assert completeness["market_financials_coverage_percent"] == 0.0
    assert completeness["daily_bars_coverage_percent"] == 0.0
    for source in result["sources"].values():
        assert source["status"] == "missing"


def test_data_quality_profile_sources_never_leak_raw_rows(tmp_path: Path) -> None:
    prices = tmp_path / "current_prices.csv"
    prices.write_text("ticker,price,as_of\n1301,100,2026-07-01\n", encoding="utf-8")

    result = ds.data_quality_profile(
        {
            "jpx_listed_issues_path": str(tmp_path / "no_jpx.csv"),
            "company_master_path": str(tmp_path / "no_company_master.csv"),
            "domestic_universe_path": str(tmp_path / "no_universe.csv"),
            "current_prices_path": str(prices),
            "market_financials_path": str(tmp_path / "no_market.csv"),
            "daily_bars_path": str(tmp_path / "no_bars.csv"),
        }
    )

    assert result["sources"]
    for source in result["sources"].values():
        assert "rows" not in source
