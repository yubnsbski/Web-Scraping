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
    assert "answer" in payload


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
