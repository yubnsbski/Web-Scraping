from __future__ import annotations

from pathlib import Path

from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.store import RagStore
from investment_assistant.webapi.service import _sources_to_yaml, available_routes, handle_api

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "examples" / "sp500_monthly_sample.csv"
SCORING_CSV = (
    "name,expense_ratio,annual_return,volatility,diversification_score\n"
    "低コスト全世界株式,0.12,0.065,0.18,0.95\n"
    "高コスト型,1.20,0.080,0.35,0.45\n"
)


def _index_doc(db_path: Path, tmp_path: Path) -> None:
    doc = tmp_path / "memo.md"
    doc.write_text("投資判断はユーザー本人が行います。分散投資が重要です。", encoding="utf-8")
    document = load_document(doc)
    RagStore(db_path).upsert_document(
        document,
        chunk_text(source=document.source, text=document.text, content_hash=document.content_hash),
    )


def test_health_and_unknown_route() -> None:
    status, payload = handle_api("GET", "/api/health")
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["auto_trading"] is False

    status, payload = handle_api("GET", "/api/does-not-exist")
    assert status == 404
    assert "error" in payload


def test_edinet_ingest_route_is_registered_and_routed(monkeypatch) -> None:
    from investment_assistant.webapi import service

    assert "POST /api/edinet/ingest" in available_routes()
    assert "GET /api/edinet/status" in available_routes()

    captured: dict[str, object] = {}

    def fake_ingest(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ingested_count": 0, "results": []}

    monkeypatch.setattr(service.cli, "run_edinet_ingest", fake_ingest)
    status, payload = handle_api(
        "POST",
        "/api/edinet/ingest",
        {"registry_path": "examples/source_registry_edinet_sample.yaml", "days": 5},
    )

    assert status == 200
    assert payload["ingested_count"] == 0
    assert captured["days"] == 5


def test_edinet_status_reports_api_key_configuration(monkeypatch) -> None:
    monkeypatch.setenv("EDINET_API_KEY", "dummy-key")

    status, payload = handle_api("GET", "/api/edinet/status")

    assert status == 200
    assert payload["api_key_configured"] is True
    assert payload["default_financials_csv"] == "local_docs/edinet/financials.csv"
    assert payload["auto_trading"] is False


def test_edinet_api_key_can_be_set_for_runtime_without_echo(monkeypatch) -> None:
    monkeypatch.delenv("EDINET_API_KEY", raising=False)

    status, payload = handle_api(
        "POST",
        "/api/edinet/api-key",
        {"api_key": "runtime-secret"},
    )

    assert status == 200
    assert payload["api_key_configured"] is True
    assert payload["request_api_key_applied"] is True
    assert "runtime-secret" not in str(payload)


def test_edinet_status_reads_local_dotenv_without_exposing_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("EDINET_API_KEY=from-dotenv\n", encoding="utf-8")

    status, payload = handle_api("GET", "/api/edinet/status")

    assert status == 200
    assert payload["api_key_configured"] is True
    assert "from-dotenv" not in str(payload)


def test_financials_import_saves_manual_csv_and_searches_securities(
    tmp_path: Path,
) -> None:
    csv_text = (
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "8306,MUFG,2023,1000,45,40,stable\n"
        "8306,MUFG,2024,1200,48,45,stable\n"
        "7203,Toyota,2024,3000,55,60,stable\n"
    )
    output_path = tmp_path / "financials.csv"

    status, imported = handle_api(
        "POST",
        "/api/financials/import",
        {
            "csv_text": csv_text,
            "save": True,
            "output_path": str(output_path),
        },
    )

    assert status == 200
    assert imported["saved_path"] == str(output_path)
    assert imported["count"] == 3
    assert imported["company_count"] == 2
    assert imported["auto_trading"] is False
    assert output_path.is_file()

    status, searched = handle_api(
        "POST",
        "/api/financials/securities",
        {"financials_csv": str(output_path), "query": "8306"},
    )

    assert status == 200
    assert searched["count"] == 1
    assert searched["securities"][0]["ticker"] == "8306"
    assert searched["securities"][0]["name"] == "MUFG"


def test_financials_status_reports_saved_data(tmp_path: Path) -> None:
    csv_text = (
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "8306,MUFG,2023,1000,45,40,stable\n"
        "8306,MUFG,2024,1200,48,45,stable\n"
        "7203,Toyota,2024,3000,55,60,stable\n"
    )
    output_path = tmp_path / "financials.csv"
    output_path.write_text(csv_text, encoding="utf-8")

    status, payload = handle_api(
        "POST",
        "/api/financials/status",
        {"path": str(output_path), "stale_after_days": 3650},
    )

    assert status == 200
    assert payload["available"] is True
    assert payload["status"] == "fresh"
    assert payload["path"] == str(output_path)
    assert payload["point_count"] == 3
    assert payload["company_count"] == 2
    assert payload["latest_fiscal_year"] == 2024
    assert payload["modified_at"]


def test_financials_status_reports_missing_data(tmp_path: Path) -> None:
    missing = tmp_path / "missing-financials.csv"

    status, payload = handle_api(
        "POST",
        "/api/financials/status",
        {"path": str(missing)},
    )

    assert status == 200
    assert payload["available"] is False
    assert payload["status"] == "missing"
    assert payload["point_count"] == 0
    assert payload["company_count"] == 0
    assert "財務データ" in payload["hint"]


def test_financials_securities_missing_csv_returns_empty_result(tmp_path: Path) -> None:
    missing = tmp_path / "missing-financials.csv"

    status, payload = handle_api(
        "POST",
        "/api/financials/securities",
        {"financials_csv": str(missing), "query": "7203"},
    )

    assert status == 200
    assert payload["available"] is False
    assert payload["count"] == 0
    assert payload["securities"] == []
    assert payload["source_ref"] == str(missing)
    assert "財務データ" in payload["hint"]


def test_portfolio_universe_missing_csv_returns_empty_result(tmp_path: Path) -> None:
    missing = tmp_path / "missing-financials.csv"

    status, payload = handle_api(
        "POST",
        "/api/portfolio/universe",
        {"financials_csv": str(missing)},
    )

    assert status == 200
    assert payload["available"] is False
    assert payload["count"] == 0
    assert payload["universe"] == []
    assert payload["source_ref"] == str(missing)
    assert "財務データ" in payload["hint"]


def test_jpx_listed_import_and_market_universe_prime_scope(tmp_path: Path) -> None:
    financials = tmp_path / "financials.csv"
    financials.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "7203,Toyota,2024,1000,55,60,stable\n"
        "8306,MUFG,2024,1200,48,45,stable\n"
        "9999,Standard Sample,2024,90,18,10,unstable\n",
        encoding="utf-8",
    )
    listed = (
        "日付,コード,銘柄名,市場・商品区分,33業種区分\n"
        "2026-05-31,7203,トヨタ自動車,プライム（内国株式）,輸送用機器\n"
        "2026-05-31,8306,三菱ＵＦＪフィナンシャル・グループ,プライム（内国株式）,銀行業\n"
        "2026-05-31,9999,サンプルスタンダード,スタンダード（内国株式）,サービス業\n"
    )
    listed_path = tmp_path / "listed_issues.csv"

    status, imported = handle_api(
        "POST",
        "/api/market/jpx-listed/import",
        {"csv_text": listed, "output_path": str(listed_path), "save": True},
    )

    assert status == 200
    assert imported["count"] == 3
    assert imported["prime_count"] == 2
    assert listed_path.is_file()

    status, universe = handle_api(
        "POST",
        "/api/market/universe",
        {
            "financials_csv": str(financials),
            "jpx_listed_path": str(listed_path),
            "scope": "prime",
            "query": "",
            "limit": 10,
        },
    )

    assert status == 200
    codes = {str(item["ticker"]) for item in universe["securities"]}
    assert codes == {"7203", "8306"}
    rows = {str(item["ticker"]): item for item in universe["securities"]}
    assert rows["8306"]["is_prime"] is True
    assert rows["8306"]["is_nikkei225"] is True
    assert rows["8306"]["has_financials"] is True
    assert universe["auto_trading"] is False
    assert universe["call_real_api"] is False



def test_rag_stats_endpoint_reports_db_contents(tmp_path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_doc(db, tmp_path)

    status, payload = handle_api(
        "POST",
        "/api/rag/stats",
        {"db_path": str(db), "keywords": ["投資判断"]},
    )

    assert status == 200
    assert payload["sources_count"] == 1
    assert payload["chunks_count"] >= 1
    assert payload["keyword_totals"]["投資判断"] >= 1


def test_rag_search_endpoint(tmp_path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_doc(db, tmp_path)
    status, payload = handle_api(
        "POST", "/api/rag/search", {"query": "投資判断", "db_path": str(db), "hybrid": True}
    )
    assert status == 200
    assert payload["results"]
    assert "投資判断" in payload["results"][0]["text"]


def test_rag_search_requires_query() -> None:
    status, payload = handle_api("POST", "/api/rag/search", {})
    assert status == 400
    assert "query" in payload["error"]


def test_orchestrate_endpoint_is_offline(tmp_path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_doc(db, tmp_path)
    status, payload = handle_api(
        "POST",
        "/api/orchestrate",
        {"query": "分散投資とは", "db_path": str(db), "drafts": 2},
    )
    assert status == 200
    assert payload["call_real_api"] is False
    assert payload["orchestration"]["drafts"] == 3
    assert "answer" in payload


def test_orchestrate_injects_dividend_evidence(tmp_path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_doc(db, tmp_path)
    financials = tmp_path / "financials.csv"
    financials.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "8306,MUFG,2023,1100000,9.5,50.0,配当性向 38%\n"
        "8306,MUFG,2024,1200000,9.9,40.0,配当性向 42%\n",
        encoding="utf-8",
    )
    status, payload = handle_api(
        "POST",
        "/api/orchestrate",
        {
            "query": "配当の持続性は？",
            "db_path": str(db),
            "target_source": "local_docs/nikkei225/8306/ir.txt",
            "financials_csv": str(financials),
        },
    )
    assert status == 200
    assert payload["financial_evidence"] is not None
    assert "減配年: 2024" in payload["financial_evidence"]


def test_orchestrate_real_api_is_guarded_when_env_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("INVESTMENT_ASSISTANT_WEB_REAL_API", raising=False)
    db = tmp_path / "rag.sqlite"
    _index_doc(db, tmp_path)
    status, payload = handle_api(
        "POST",
        "/api/orchestrate",
        {"query": "分散投資とは", "db_path": str(db), "call_real_api": True},
    )
    assert status == 200
    assert payload["call_real_api"] is False
    assert "GEMINI_API_KEY is not configured" in payload["real_api_note"]


def test_fetch_job_auto_fetches_allowed_sources_and_indexes(monkeypatch, tmp_path) -> None:
    calls: list[bool] = []

    def fake_run_fetch_job(*, path, dry_run: bool, preview_chars: int = 500):
        _ = path, preview_chars
        calls.append(dry_run)
        source = {
            "name": "allowed_ir",
            "url": "https://example.com/ir",
            "output_path": "local_docs/allowed.txt",
            "fetch": {
                "allowed_by_robots": True,
                "source": "dry_run" if dry_run else "network",
                "status_code": None if dry_run else 200,
                "saved_path": None if dry_run else "local_docs/allowed.txt",
            },
        }
        blocked = {
            "name": "blocked_ir",
            "url": "https://example.com/private",
            "output_path": "local_docs/blocked.txt",
            "fetch": {
                "allowed_by_robots": False,
                "source": "blocked_by_robots",
                "status_code": None,
                "saved_path": None,
            },
        }
        return {"results": [source, blocked] if dry_run else [source]}

    def fake_index_dir(*, path, db_path):
        assert path == "local_docs"
        assert db_path == str(tmp_path / "rag.sqlite")
        return {"files_indexed": 1, "chunks_indexed": 2}

    from investment_assistant.webapi import service

    monkeypatch.setattr(service.cli, "run_fetch_job", fake_run_fetch_job)
    monkeypatch.setattr(service.cli, "run_rag_index_dir", fake_index_dir)

    status, payload = handle_api(
        "POST",
        "/api/fetch-job/auto",
        {
            "db_path": str(tmp_path / "rag.sqlite"),
            "sources": [
                {
                    "name": "allowed_ir",
                    "url": "https://example.com/ir",
                    "output_path": "local_docs/allowed.txt",
                },
                {
                    "name": "blocked_ir",
                    "url": "https://example.com/private",
                    "output_path": "local_docs/blocked.txt",
                },
            ],
        },
    )
    assert status == 200
    assert calls == [True, False]
    assert payload["policy"]["robots_checked"] is True
    assert payload["policy"]["robots_blocked_count"] == 1
    assert payload["allowed_sources_count"] == 1
    assert payload["index"]["chunks_indexed"] == 2


def test_manual_doc_save_indexes_pasted_text(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "rag.sqlite"
    status, payload = handle_api(
        "POST",
        "/api/manual-doc/save",
        {
            "title": "配当方針メモ",
            "source_url": "https://example.com/ir",
            "text": "この会社はDOEと配当性向を重視する方針です。",
            "db_path": str(db),
        },
    )
    assert status == 200
    assert Path(payload["saved_path"]).is_file()
    assert payload["indexed"]["chunks_indexed"] >= 1

    status, search_payload = handle_api(
        "POST",
        "/api/rag/search",
        {"query": "DOE 配当性向", "db_path": str(db)},
    )
    assert status == 200
    assert search_payload["results"]


def test_manual_doc_save_requires_text() -> None:
    status, payload = handle_api("POST", "/api/manual-doc/save", {"title": "empty"})
    assert status == 400
    assert "text" in payload["error"]


def test_scoring_rank_from_csv_text() -> None:
    status, payload = handle_api("POST", "/api/scoring/rank", {"csv_text": SCORING_CSV, "limit": 2})
    assert status == 200
    assert payload["count"] == 2
    assert payload["results"][0]["name"] == "低コスト全世界株式"
    assert payload["auto_trading"] is False


def test_forecast_evaluate_defaults_to_sample() -> None:
    status, payload = handle_api(
        "POST", "/api/forecast/evaluate", {"space": "returns", "include_ml": False}
    )
    assert status == 200
    assert payload["best_model"]
    assert any(model["name"] == "naive" for model in payload["models"])


def test_forecast_predict_defaults_to_sample() -> None:
    status, payload = handle_api("POST", "/api/forecast/predict", {"horizon": 2})
    assert status == 200
    assert len(payload["ensemble_forecast"]) == 2


def test_available_routes_lists_endpoints() -> None:
    routes = available_routes()
    assert "GET /api/health" in routes
    assert "POST /api/rag/search" in routes
    assert "POST /api/rag/stats" in routes
    assert "POST /api/manual-doc/save" in routes
    assert "POST /api/fetch-job/auto" in routes
    assert "POST /api/fetch-job/dry-run" in routes


def test_sources_to_yaml_roundtrips_with_loader(tmp_path) -> None:
    from investment_assistant.cli import _fetch_job_sources
    from investment_assistant.config.loader import load_yaml

    yaml_text = _sources_to_yaml(
        [
            {
                "name": "9432_NTT_ir",
                "url": "https://group.ntt/jp/ir/",
                "output_path": "local_docs/nikkei225/9432/ir.txt",
                "extract_text": True,
                "preview_chars": 500,
            }
        ]
    )
    path = tmp_path / "job.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    sources = _fetch_job_sources(load_yaml(path), path)
    assert sources[0]["name"] == "9432_NTT_ir"
    assert sources[0]["extract_text"] is True
    assert sources[0]["preview_chars"] == 500



def test_portfolio_endpoints_return_sample_summaries() -> None:
    root = Path(__file__).resolve().parents[2]
    dividends_csv = root / "examples" / "portfolio_dividends_sample.csv"
    performance_csv = root / "examples" / "portfolio_performance_sample.csv"

    status, dividends = handle_api(
        "POST",
        "/api/portfolio/dividends",
        {"path": str(dividends_csv)},
    )
    assert status == 200
    assert dividends["latest_annual"] == 182400.0
    assert dividends["increase_streak"] == 6
    assert "投資助言" in str(dividends["disclaimer"])

    status, performance = handle_api(
        "POST",
        "/api/portfolio/performance",
        {"path": str(performance_csv)},
    )
    assert status == 200
    assert performance["market_value"] == 5420000.0
    assert performance["pnl"] == 850000.0
    assert performance["max_drawdown_pct"] <= 0


def test_available_routes_includes_portfolio_endpoints() -> None:
    routes = available_routes()
    assert "POST /api/portfolio/dividends" in routes
    assert "POST /api/portfolio/performance" in routes
    assert "POST /api/portfolio/target" in routes


def test_portfolio_target_reverse_calc_endpoint() -> None:
    status, body = handle_api(
        "POST",
        "/api/portfolio/target",
        {
            "target_annual_dividend": 20000,
            "dividend_basis": "latest",
            "financials_csv": "/nonexistent/financials.csv",
            "holdings": [{"ticker": "A", "price": 1000, "dividend_per_share": 40}],
        },
    )
    assert status == 200
    assert body["available"] is True
    assert body["target"]["required_budget"] == 500000
    assert body["target"]["reachable"] is True


def test_investment_mvp_routes_import_analyze_screen_and_report(tmp_path: Path) -> None:
    holdings_csv = (
        "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
        "source,current_price,annual_income,distribution_per_unit\n"
        "stock,8306,MUFG,100,1000,tokutei,nisa_growth,user_csv,1200,,\n"
        "fund,F001,低コスト投信,50,10000,nisa,nisa_tsumitate,user_csv,11000,,30\n"
    )
    funds_csv = (
        "fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,"
        "provider_id,diversification_score\n"
        "F001,低コスト全世界株式,global_equity,0.12,reinvest,true,user_csv,0.95\n"
    )
    financials = tmp_path / "financials.csv"
    financials.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "8306,MUFG,2023,1000,45,40,安定\n"
        "8306,MUFG,2024,1200,48,45,安定\n",
        encoding="utf-8",
    )

    status, imported = handle_api("POST", "/api/holdings/import", {"csv_text": holdings_csv})
    assert status == 200
    assert imported["count"] == 2
    assert imported["recommended_columns"] == ["data_provider", "price_as_of"]
    warning_codes = {
        str(item.get("code"))
        for item in imported["input_warnings"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert {"recommended_column_missing", "price_as_of_recommended"} <= warning_codes

    holdings_csv_with_guidance = (
        "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,"
        "source,current_price,annual_income,distribution_per_unit,data_provider,price_as_of\n"
        "stock,8306,MUFG,100,1000,tokutei,nisa_growth,user_csv,1200,,,user_csv,2026-06-10\n"
    )
    status, guided_import = handle_api(
        "POST",
        "/api/holdings/import",
        {"csv_text": holdings_csv_with_guidance},
    )
    assert status == 200
    assert guided_import["input_warnings"] == []

    status, analysis = handle_api(
        "POST",
        "/api/portfolio/analyze",
        {"csv_text": holdings_csv, "financials_csv": str(financials)},
    )
    assert status == 200
    assert analysis["summary"]["market_value"] == 670000.0
    assert analysis["summary"]["edinet_covered_holdings"] == 1
    assert analysis["summary"]["edinet_source_ref"] == str(financials)
    assert analysis["summary"]["nisa"]["status"] == "ok"
    assert analysis["summary"]["nisa"]["alerts"] == []
    assert analysis["summary"]["data_quality"]["missing_timestamp_count"] == 2
    assert analysis["summary"]["income_quality"]["status"] == "ok"
    assert analysis["summary"]["income_quality"]["alerts"] == []

    status, production_analysis = handle_api(
        "POST",
        "/api/portfolio/analyze",
        {
            "csv_text": (
                "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,"
                "tax_wrapper,source,current_price,annual_income,distribution_per_unit,"
                "data_provider,price_as_of\n"
                "stock,8306,MUFG,100,1000,tokutei,taxable,stooq_public_csv,1200,,,"
                "stooq_public_csv,2020-01-01\n"
            ),
            "financials_csv": str(financials),
            "runtime_mode": "production",
        },
    )
    assert status == 200
    assert production_analysis["summary"]["data_quality"]["provider_blocked_count"] == 1

    status, candidates = handle_api(
        "POST",
        "/api/candidates/screen",
        {
            "asset_types": ["stock", "fund"],
            "funds_csv_text": funds_csv,
            "financials_csv": str(financials),
            "exclude_dividend_cut": True,
            "max_expense_ratio": 0.2,
            "nisa_eligible_only": True,
        },
    )
    assert status == 200
    assert candidates["count"] >= 2
    assert candidates["auto_trading"] is False
    stock_candidate = next(
        item for item in candidates["results"] if item["asset_type"] == "stock"
    )
    assert stock_candidate["edinet_summary"]["source_ref"] == str(financials)
    assert stock_candidate["edinet_summary"]["latest_dividend_per_share"] == 45.0
    assert stock_candidate["evidence"][0]["source_ref"] == str(financials)

    status, detail = handle_api(
        "POST",
        "/api/investment/detail",
        {
            "code": "8306",
            "asset_type": "stock",
            "csv_text": holdings_csv,
            "funds_csv_text": funds_csv,
            "financials_csv": str(financials),
        },
    )
    assert status == 200
    assert detail["available"] is True
    assert detail["asset_type"] == "stock"
    assert detail["metrics"]
    assert detail["evidence"]
    assert detail["edinet_summary"]["source_ref"] == str(financials)
    assert detail["edinet_summary"]["latest_fiscal_year"] == 2024
    assert detail["auto_trading"] is False

    status, report = handle_api(
        "POST",
        "/api/reports/investment-monthly",
        {
            "csv_text": holdings_csv,
            "financials_csv": str(financials),
            "candidates": candidates["results"],
            "target_annual_dividend": 10_000,
            "optimization": "balanced",
            "history_dir": str(tmp_path / "report_history"),
        },
    )
    assert status == 200
    assert report["kpis"]
    assert report["evidence"]
    assert report["publish_audit"]["status"] == "ok"
    assert report["publish_audit"]["issue_count"] == 0
    history_summary = report["history"]
    assert history_summary["id"]
    assert history_summary["market_value"] == 670000.0
    assert history_summary["publish_audit_status"] == "ok"
    assert history_summary["publish_audit_issue_count"] == 0
    assert history_summary["integrity_status"] == "ok"
    assert isinstance(history_summary["report_hash"], str)
    metric_keys = {
        str(item.get("metric_key"))
        for item in report["kpis"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert "target_required_budget" in metric_keys
    assert "concentration_effective_names" in metric_keys
    evidence_keys = {
        str(item.get("claim_key"))
        for item in report["evidence"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert "portfolio.target.required_budget" in evidence_keys
    assert "portfolio.concentration.current" in evidence_keys
    assert "candidate.8306.edinet_financials" in evidence_keys
    assert "candidate.8306.edinet_summary" in evidence_keys

    status, audit = handle_api(
        "POST",
        "/api/reports/investment-monthly/audit",
        {"report": report},
    )
    assert status == 200
    assert audit["status"] == "ok"
    assert audit["issue_count"] == 0

    status, history = handle_api(
        "POST",
        "/api/reports/investment-monthly/history",
        {"history_dir": str(tmp_path / "report_history")},
    )
    assert status == 200
    assert history["count"] == 1
    assert history["reports"][0]["id"] == history_summary["id"]
    assert history["reports"][0]["target_required_budget"] is not None
    assert history["reports"][0]["integrity_status"] == "ok"

    status, saved = handle_api(
        "POST",
        "/api/reports/investment-monthly/history/load",
        {"history_dir": str(tmp_path / "report_history"), "id": history_summary["id"]},
    )
    assert status == 200
    assert saved["summary"]["id"] == history_summary["id"]
    assert saved["integrity_status"] == "ok"
    assert saved["summary"]["integrity_status"] == "ok"
    assert saved["report"]["kpis"]
    assert saved["report"]["evidence"]
    assert "csv_text" not in saved["report"]

    status, verified_history = handle_api(
        "POST",
        "/api/reports/investment-monthly/history/verify",
        {"history_dir": str(tmp_path / "report_history"), "id": history_summary["id"]},
    )
    assert status == 200
    assert verified_history["integrity_status"] == "ok"

    status, saved_audit = handle_api(
        "POST",
        "/api/reports/investment-monthly/audit",
        {"history_dir": str(tmp_path / "report_history"), "id": history_summary["id"]},
    )
    assert status == 200
    assert saved_audit["status"] == "ok"

    status, markdown = handle_api(
        "POST",
        "/api/reports/investment-monthly/markdown",
        {"history_dir": str(tmp_path / "report_history"), "id": history_summary["id"]},
    )
    assert status == 200
    assert markdown["auto_trading"] is False
    assert "## Publish Audit" in markdown["markdown"]
    assert "status: ok" in markdown["markdown"]
    assert "## KPIs" in markdown["markdown"]
    assert "market_value" in markdown["markdown"]
    assert "portfolio.concentration.current" in markdown["markdown"]
    assert "## Disclaimer" in markdown["markdown"]

    higher_price_csv = holdings_csv.replace("user_csv,1200,,", "user_csv,1300,,")
    status, newer_report = handle_api(
        "POST",
        "/api/reports/investment-monthly",
        {
            "csv_text": higher_price_csv,
            "financials_csv": str(financials),
            "candidates": candidates["results"],
            "target_annual_dividend": 10_000,
            "optimization": "balanced",
            "history_dir": str(tmp_path / "report_history"),
        },
    )
    assert status == 200
    newer_summary = newer_report["history"]
    assert newer_summary["id"] != history_summary["id"]

    status, comparison = handle_api(
        "POST",
        "/api/reports/investment-monthly/history/compare",
        {
            "history_dir": str(tmp_path / "report_history"),
            "base_id": history_summary["id"],
            "compare_id": newer_summary["id"],
        },
    )
    assert status == 200
    assert comparison["auto_trading"] is False
    deltas = {
        item["metric_key"]: item
        for item in comparison["metrics"]
        if isinstance(item, dict)
    }
    assert deltas["market_value"]["delta"] == 10000.0
    assert deltas["annual_income_estimate"]["delta"] == 0.0
    assert comparison["evidence"]["compare_count"] >= comparison["evidence"]["base_count"]

    status, deleted = handle_api(
        "POST",
        "/api/reports/investment-monthly/history/delete",
        {"history_dir": str(tmp_path / "report_history"), "id": history_summary["id"]},
    )
    assert status == 200
    assert deleted["deleted"] is True

    status, history = handle_api(
        "POST",
        "/api/reports/investment-monthly/history",
        {"history_dir": str(tmp_path / "report_history")},
    )
    assert status == 200
    assert history["count"] == 1


def test_investment_csv_template_routes_return_importable_samples() -> None:
    status, holdings_template = handle_api(
        "POST",
        "/api/holdings/template",
        {"include_examples": True},
    )
    assert status == 200
    assert holdings_template["kind"] == "holdings"
    assert "data_provider" in holdings_template["recommended_columns"]
    assert "price_as_of" in holdings_template["columns"]

    status, imported = handle_api(
        "POST",
        "/api/holdings/import",
        {"csv_text": holdings_template["csv_text"]},
    )
    assert status == 200
    assert imported["count"] == 2
    assert imported["input_warnings"] == []

    status, funds_template = handle_api(
        "POST",
        "/api/funds/template",
        {"include_examples": True},
    )
    assert status == 200
    assert funds_template["kind"] == "fund_profiles"
    assert "diversification_score" in funds_template["optional_columns"]

    status, candidates = handle_api(
        "POST",
        "/api/candidates/screen",
        {
            "asset_types": ["fund"],
            "funds_csv_text": funds_template["csv_text"],
            "max_expense_ratio": 0.2,
        },
    )
    assert status == 200
    assert candidates["count"] == 1
    assert candidates["auto_trading"] is False


def test_investment_csv_validation_routes_accept_template_samples() -> None:
    status, holdings_template = handle_api(
        "POST",
        "/api/holdings/template",
        {"include_examples": True},
    )
    assert status == 200

    status, holdings_validation = handle_api(
        "POST",
        "/api/holdings/validate",
        {"csv_text": holdings_template["csv_text"]},
    )
    assert status == 200
    assert holdings_validation["valid"] is True
    assert holdings_validation["count"] == 2
    assert holdings_validation["errors"] == []
    assert holdings_validation["warnings"] == []
    assert holdings_validation["auto_trading"] is False
    assert holdings_validation["call_real_api"] is False

    status, funds_template = handle_api(
        "POST",
        "/api/funds/template",
        {"include_examples": True},
    )
    assert status == 200

    status, funds_validation = handle_api(
        "POST",
        "/api/funds/validate",
        {"funds_csv_text": funds_template["csv_text"]},
    )
    assert status == 200
    assert funds_validation["valid"] is True
    assert funds_validation["count"] == 1
    assert funds_validation["errors"] == []
    assert funds_validation["auto_trading"] is False
    assert funds_validation["call_real_api"] is False


def test_holdings_csv_validation_reports_missing_columns() -> None:
    status, payload = handle_api(
        "POST",
        "/api/holdings/validate",
        {"csv_text": "asset_type,ticker_or_fund_code,name\nstock,7203,Toyota\n"},
    )

    assert status == 200
    assert payload["valid"] is False
    assert payload["count"] == 0
    assert payload["errors"][0]["code"] == "required_column_missing"
    assert "quantity" in payload["errors"][0]["columns"]


def test_holdings_csv_validation_reports_row_errors() -> None:
    bad_csv = (
        "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,"
        "tax_wrapper,source\n"
        "stock,7203,Toyota,not-a-number,1800,tokutei,nisa_growth,user_csv\n"
    )
    status, payload = handle_api("POST", "/api/holdings/validate", {"csv_text": bad_csv})

    assert status == 200
    assert payload["valid"] is False
    assert payload["errors"][0]["code"] == "row_invalid"
    assert payload["errors"][0]["row"] == 2
    assert payload["errors"][0]["column"] == "quantity"


def test_fund_csv_validation_requires_input_source() -> None:
    status, payload = handle_api("POST", "/api/funds/validate", {})

    assert status == 200
    assert payload["valid"] is False
    assert payload["errors"][0]["code"] == "input_missing"
    assert payload["auto_trading"] is False
    assert payload["call_real_api"] is False


def test_market_prices_reject_uncontracted_provider_in_production() -> None:
    status, payload = handle_api(
        "POST",
        "/api/market/prices",
        {"tickers": ["8306"], "runtime_mode": "production"},
    )
    assert status == 400
    assert "not allowed in production" in payload["error"]


def test_provider_policy_ledger_route_reports_runtime_decisions() -> None:
    status, payload = handle_api(
        "POST",
        "/api/providers/policy",
        {
            "runtime_mode": "production",
            "provider_ids": ["user_csv", "stooq_public_csv", "jquants"],
        },
    )

    assert status == 200
    rows = {
        str(item["provider_id"]): item
        for item in payload["providers"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    assert payload["runtime_mode"] == "production"
    assert rows["user_csv"]["runtime_decision"] == "allowed"
    assert rows["stooq_public_csv"]["runtime_decision"] == "blocked_until_contracted"
    assert rows["jquants"]["recommended_use"] == "contract_required"
    assert payload["auto_trading"] is False
    assert payload["call_real_api"] is False
