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
