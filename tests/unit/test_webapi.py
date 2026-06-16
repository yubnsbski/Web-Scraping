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


def test_edinet_status_reports_api_key_and_registry_plan(
    monkeypatch, tmp_path: Path
) -> None:
    from investment_assistant.edinet.client import API_KEY_ENV_VAR
    from investment_assistant.webapi.local_env import LOCAL_ENV_ROOT_ENV

    monkeypatch.chdir(tmp_path)
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "sources:\n"
        "  - name: mufg_edinet\n"
        "    source_type: public_api\n"
        "    provider: edinet\n"
        "    allowed: true\n"
        "    ticker: '8306'\n"
        "    company: MUFG\n"
        "    doc_types: ['120']\n",
        encoding="utf-8",
    )

    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    status, missing_key = handle_api(
        "POST",
        "/api/edinet/status",
        {"registry_path": str(registry), "output_dir": str(tmp_path / "edinet"), "days": 5},
    )
    assert status == 200
    assert missing_key["can_start"] is False
    assert missing_key["api_key_configured"] is False
    assert missing_key["setup_guidance"]["env_var"] == API_KEY_ENV_VAR
    assert missing_key["setup_guidance"]["explicit_root_env"] == LOCAL_ENV_ROOT_ENV
    assert missing_key["setup_guidance"]["example_line"] == (
        f"{API_KEY_ENV_VAR}=<your-edinet-api-key>"
    )
    assert "dummy-key" not in str(missing_key["setup_guidance"])

    monkeypatch.setenv(API_KEY_ENV_VAR, "dummy-key")
    status, payload = handle_api(
        "POST",
        "/api/edinet/status",
        {"registry_path": str(registry), "output_dir": str(tmp_path / "edinet"), "days": 5},
    )

    assert status == 200
    assert payload["status"] == "ready"
    assert payload["can_start"] is True
    assert payload["target_count"] == 1
    assert payload["sample_targets"][0]["ticker"] == "8306"
    assert payload["start_endpoint"] == "/api/edinet/ingest-async"
    assert payload["start_payload"]["registry_path"] == str(registry)
    assert payload["start_payload"]["days"] == 5
    assert "POST /api/edinet/status" in available_routes()


def test_edinet_status_reloads_local_env_without_restart(
    monkeypatch, tmp_path: Path
) -> None:
    from investment_assistant.edinet.client import API_KEY_ENV_VAR
    from investment_assistant.webapi.local_env import LOCAL_ENV_ROOT_ENV

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    monkeypatch.delenv(LOCAL_ENV_ROOT_ENV, raising=False)
    (tmp_path / ".env.local").write_text(
        f"{API_KEY_ENV_VAR}=dummy-key-from-file\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "sources:\n"
        "  - name: kddi_edinet\n"
        "    source_type: public_api\n"
        "    provider: edinet\n"
        "    allowed: true\n"
        "    ticker: '9433'\n"
        "    company: KDDI\n"
        "    doc_types: ['120']\n",
        encoding="utf-8",
    )

    status, payload = handle_api(
        "POST",
        "/api/edinet/status",
        {"registry_path": str(registry), "output_dir": str(tmp_path / "edinet"), "days": 5},
    )

    assert status == 200
    assert payload["api_key_configured"] is True
    assert payload["can_start"] is True
    assert payload["env_reload"]["loaded_keys"] == [API_KEY_ENV_VAR]
    assert str(tmp_path / ".env.local") in payload["env_reload"]["loaded_files"]
    assert "dummy-key-from-file" not in str(payload)



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


def test_market_prices_defaults_to_yahoo_and_accepts_comma_string(monkeypatch) -> None:
    from investment_assistant.portfolio import prices as prices_mod

    captured: dict[str, object] = {}

    def fake_fetch_prices(tickers: object, **kwargs: object) -> dict[str, object]:
        captured["tickers"] = tickers
        captured.update(kwargs)
        return {"provider_id": "yfinance", "prices": {"8306": 3010.0}, "notes": {}}

    monkeypatch.setattr(prices_mod, "fetch_prices", fake_fetch_prices)

    status, payload = handle_api("POST", "/api/market/prices", {"tickers": "8306, 7203"})

    assert status == 200
    assert captured["tickers"] == ["8306", "7203"]
    assert captured["provider_id"] == "yfinance"
    assert captured["rate_limit"] is not None
    assert payload["provider_id"] == "yfinance"


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


def test_market_ohlcv_route_validates_and_routes(monkeypatch) -> None:
    from investment_assistant.webapi import service

    # Empty tickers are rejected before any fetch.
    status, payload = handle_api("POST", "/api/market/ohlcv", {"tickers": []})
    assert status == 400 and "non-empty" in payload["error"]

    # Too many tickers are rejected.
    status, _ = handle_api("POST", "/api/market/ohlcv", {"tickers": [str(i) for i in range(51)]})
    assert status == 400

    # Yahoo is uncontracted, so production is blocked before fetching.
    status, payload = handle_api(
        "POST", "/api/market/ohlcv", {"tickers": ["8306"], "runtime_mode": "production"}
    )
    assert status == 400 and "not allowed in production" in payload["error"]

    # Development mode routes to the runner (stubbed to avoid network).
    captured: dict[str, object] = {}

    def fake_ohlcv(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ohlcv": {"8306": []}, "counts": {"8306": 0}, "tickers_count": 1}

    monkeypatch.setattr(service.cli, "run_market_ohlcv", fake_ohlcv)
    status, payload = handle_api(
        "POST", "/api/market/ohlcv", {"tickers": "8306, 7203", "range": "5d"}
    )
    assert status == 200
    assert captured["tickers"] == ["8306", "7203"] and captured["range_"] == "5d"


def test_market_bars_alias_can_save_daily_bars(monkeypatch, tmp_path: Path) -> None:
    from investment_assistant.webapi import service

    out = tmp_path / "daily_bars.csv"

    def fake_ohlcv(**kwargs: object) -> dict[str, object]:
        return {
            "provider_id": "yfinance",
            "range": kwargs.get("range_"),
            "interval": kwargs.get("interval"),
            "ohlcv": {
                "8306": [
                    {
                        "date": "2026-06-15",
                        "open": 100.0,
                        "high": 110.0,
                        "low": 90.0,
                        "close": 105.0,
                        "volume": 1000,
                    }
                ]
            },
            "counts": {"8306": 1},
            "tickers_count": 1,
        }

    monkeypatch.setattr(service.cli, "run_market_ohlcv", fake_ohlcv)

    status, payload = handle_api(
        "POST",
        "/api/market/bars",
        {"tickers": ["8306"], "save_csv": True, "daily_bars_path": str(out)},
    )

    assert status == 200
    assert payload["daily_bars_count"] == 1
    assert out.read_text(encoding="utf-8-sig").splitlines() == [
        "ticker,date,open,high,low,close,volume",
        "8306,2026-06-15,100.0,110.0,90.0,105.0,1000",
    ]


def test_market_bars_universe_expands_financials_csv_and_saves(monkeypatch, tmp_path: Path) -> None:
    from investment_assistant.webapi import service

    financials = tmp_path / "financials.csv"
    financials.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "8306,MUFG,2025,100,8.0,41,stable\n"
        "7203,Toyota,2025,200,40.0,75,stable\n"
        "8306,MUFG,2024,90,7.5,39,stable\n",
        encoding="utf-8",
    )
    out = tmp_path / "daily_bars.csv"
    captured: dict[str, object] = {}

    def fake_ohlcv(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "provider_id": "yfinance",
            "ohlcv": {
                "8306": [{"date": "2026-06-15", "close": 101.0}],
                "7203": [{"date": "2026-06-15", "close": 202.0}],
            },
            "counts": {"8306": 1, "7203": 1},
            "tickers_count": 2,
        }

    monkeypatch.setattr(service.cli, "run_market_ohlcv", fake_ohlcv)

    status, payload = handle_api(
        "POST",
        "/api/market/bars/universe",
        {
            "universe": "financials_csv",
            "financials_csv": str(financials),
            "daily_bars_path": str(out),
        },
    )

    assert status == 200
    assert captured["tickers"] == ["8306", "7203"]
    assert captured["max_count"] == 0
    assert payload["daily_bars_count"] == 2
    assert payload["universe_source"].startswith("financials_csv:")
    assert "8306,2026-06-15,,,,101.0," in out.read_text(encoding="utf-8-sig")


def test_market_financials_route_fetches_and_can_save(monkeypatch, tmp_path: Path) -> None:
    from investment_assistant.webapi import service

    out = tmp_path / "yahoo_financials.csv"
    captured: dict[str, object] = {}

    def fake_financials(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "provider_id": "yfinance",
            "financials": {"9432": {"price": 5000.0, "dividend_yield_percent": 3.2}},
            "counts": {"9432": 2},
            "matched_tickers": 1,
            "tickers_count": 1,
            "saved": bool(kwargs.get("save")),
            "output_path": str(kwargs.get("output_path")),
        }

    monkeypatch.setattr(service.cli, "run_market_financials", fake_financials)

    status, payload = handle_api(
        "POST",
        "/api/market/financials",
        {"tickers": "9432", "save_csv": True, "output_path": str(out)},
    )

    assert status == 200
    assert captured["tickers"] == ["9432"]
    assert captured["save"] is True
    assert captured["output_path"] == str(out)
    assert payload["financials"]["9432"]["dividend_yield_percent"] == 3.2
    assert payload["universe_source"] == "tickers"


def test_market_financials_route_expands_financials_csv(monkeypatch, tmp_path: Path) -> None:
    from investment_assistant.webapi import service

    financials = tmp_path / "financials.csv"
    financials.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "8306,MUFG,2025,100,8.0,41,stable\n"
        "7203,Toyota,2025,200,40.0,75,stable\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_financials(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"financials": {}, "counts": {}, "tickers_count": 2, "matched_tickers": 0}

    monkeypatch.setattr(service.cli, "run_market_financials", fake_financials)

    status, payload = handle_api(
        "POST",
        "/api/market/financials",
        {"universe": "financials_csv", "financials_csv": str(financials), "max_count": 1},
    )

    assert status == 200
    assert captured["tickers"] == ["8306", "7203"]
    assert captured["max_count"] == 1
    assert captured["save"] is False
    assert payload["universe_source"].startswith("financials_csv:")


def test_market_intraday_route_validates_and_routes(monkeypatch) -> None:
    from investment_assistant.webapi import service

    status, payload = handle_api("POST", "/api/market/intraday", {"tickers": ""})
    assert status == 400 and "non-empty" in payload["error"]

    def fake_intraday(**kwargs: object) -> dict[str, object]:
        return {"intraday": {"2914": []}, "counts": {"2914": 0}, "tickers_count": 1}

    monkeypatch.setattr(service.cli, "run_yahoo_intraday", fake_intraday)
    status, payload = handle_api("POST", "/api/market/intraday", {"tickers": ["2914"]})
    assert status == 200 and payload["counts"] == {"2914": 0}


def test_data_status_route_reports_local_inventory(tmp_path: Path) -> None:
    financials = tmp_path / "financials.csv"
    financials.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "8306,MUFG,2025,100,8.0,41,stable\n"
        "7203,Toyota,2025,200,40.0,75,stable\n",
        encoding="utf-8",
    )
    bars = tmp_path / "daily_bars.csv"
    bars.write_text(
        "ticker,date,open,high,low,close,volume\n"
        "8306,2026-06-15,100,110,90,105,1000\n",
        encoding="utf-8-sig",
    )
    log = tmp_path / "market_fetch.log"
    log.write_text("retry 8306\nok 8306\n", encoding="utf-8")

    status, payload = handle_api(
        "POST",
        "/api/data/status",
        {
            "financials_csv": str(financials),
            "daily_bars_path": str(bars),
            "market_log_path": str(log),
            "market_financials_path": str(tmp_path / "missing_market.csv"),
            "price_inbox_path": str(tmp_path / "missing_inbox.csv"),
            "edinet_financials_path": str(tmp_path / "missing_edinet.csv"),
            "rag_db_path": str(tmp_path / "missing_rag.sqlite"),
        },
    )

    assert status == 200
    rows = {str(item["id"]): item for item in payload["datasets"]}
    assert rows["selected_financials"]["status"] == "ready"
    assert rows["selected_financials"]["row_count"] == 2
    assert rows["selected_financials"]["ticker_count"] == 2
    assert rows["daily_bars"]["row_count"] == 1
    assert rows["daily_bars"]["latest_value"] == "2026-06-15"
    assert rows["market_fetch_log"]["line_count"] == 2
    assert rows["market_financials"]["status"] == "missing"
    actions = {str(item["id"]): item for item in payload["actions"]}
    assert actions["refresh_market_financials"]["safe_to_run"] is True
    assert actions["check_price_inbox"]["action_type"] == "price_inbox"
    assert actions["prepare_edinet_financials"]["safe_to_run"] is False
    assert payload["summary"]["action_count"] >= 3
    assert payload["summary"]["safe_action_count"] >= 2
    assert payload["auto_trading"] is False
    assert payload["call_real_api"] is False
    assert "POST /api/data/status" in available_routes()
