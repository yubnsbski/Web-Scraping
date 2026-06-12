"""Framework-agnostic JSON API over the existing CLI run_* functions."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from investment_assistant import cli
from investment_assistant.financials import (
    compare_financials,
    load_financials,
)
from investment_assistant.financials.evidence import (
    DEFAULT_FINANCIALS_CSV,
    build_financial_evidence,
)
from investment_assistant.llm.factory import DEFAULT_GEMINI_CONFIG_PATH
from investment_assistant.portfolio.loader import (
    load_dividends,
    load_performance,
    summarize_dividends,
    summarize_performance,
)
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH
from investment_assistant.webapi.jobs import JOBS

JsonDict = dict[str, Any]
Handler = Callable[[JsonDict], JsonDict]
_REAL_API_ENV = "INVESTMENT_ASSISTANT_WEB_REAL_API"
_REAL_API_RUNTIME_ENABLED = False
_EDINET_API_KEY_RUNTIME_SET = False


class ApiError(Exception):
    """Raised by handlers to return a 4xx with a JSON error body."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def handle_api(method: str, path: str, body: JsonDict | None = None) -> tuple[int, JsonDict]:
    handler = _ROUTES.get((method.upper(), path.rstrip("/") or "/"))
    if handler is None:
        return 404, {"error": f"no such endpoint: {method} {path}"}
    try:
        return 200, handler(body or {})
    except ApiError as exc:
        return exc.status, {"error": exc.message}
    except (ValueError, KeyError, FileNotFoundError, OSError) as exc:
        return 400, {"error": f"{type(exc).__name__}: {exc}"}


# --- handlers --------------------------------------------------------------


def _health(_: JsonDict) -> JsonDict:
    return {"status": "ok", "service": "investment-assistant", "auto_trading": False}


def _edinet_status(_: JsonDict) -> JsonDict:
    from investment_assistant.edinet.client import API_KEY_ENV_VAR

    env_configured_before_dotenv = bool(os.getenv(API_KEY_ENV_VAR, "").strip())
    dotenv_loaded = _ensure_env_from_dotenv(API_KEY_ENV_VAR)
    configured = bool(os.getenv(API_KEY_ENV_VAR, "").strip())
    return {
        "api_key_configured": configured,
        "api_key_env_var": API_KEY_ENV_VAR,
        "api_key_source": _edinet_api_key_source(
            configured=configured,
            env_configured_before_dotenv=env_configured_before_dotenv,
            dotenv_loaded=dotenv_loaded,
        ),
        "default_registry": "examples/source_registry_nikkei225_edinet.yaml",
        "default_output_dir": "local_docs/edinet",
        "default_financials_csv": DEFAULT_FINANCIALS_CSV,
        "structured_refresh_requires_key": True,
        "fallback_without_key": "official_disclosure_scrape_only",
        "auto_trading": False,
        "call_real_api": False,
    }


def _edinet_api_key_set(body: JsonDict) -> JsonDict:
    from investment_assistant.edinet.client import API_KEY_ENV_VAR

    global _EDINET_API_KEY_RUNTIME_SET

    value = str(body.get("api_key") or "").strip()
    if value:
        os.environ[API_KEY_ENV_VAR] = value
        _EDINET_API_KEY_RUNTIME_SET = True
    configured = bool(os.getenv(API_KEY_ENV_VAR, "").strip())
    return {
        "api_key_configured": configured,
        "api_key_env_var": API_KEY_ENV_VAR,
        "api_key_source": "runtime_input" if _EDINET_API_KEY_RUNTIME_SET else "missing",
        "request_api_key_applied": bool(value),
        "auto_trading": False,
        "call_real_api": False,
    }


def _budget(_: JsonDict) -> JsonDict:
    from dataclasses import asdict

    return asdict(cli.build_budget_report(DEFAULT_GEMINI_CONFIG_PATH))


def _runtime_real_api_status(_: JsonDict) -> JsonDict:
    env_allowed = _as_bool(os.getenv(_REAL_API_ENV), False)
    runtime_enabled = bool(_REAL_API_RUNTIME_ENABLED)
    has_key = bool(os.getenv("GEMINI_API_KEY"))
    return {
        "enabled": env_allowed or runtime_enabled,
        "usable": (env_allowed or runtime_enabled) and has_key,
        "env_allowed": env_allowed,
        "runtime_enabled": runtime_enabled,
        "api_key_configured": has_key,
    }


def _runtime_real_api_set(body: JsonDict) -> JsonDict:
    global _REAL_API_RUNTIME_ENABLED

    requested = _as_bool(body.get("enabled"), False)
    request_has_key = _apply_request_api_key(body)
    has_key = bool(os.getenv("GEMINI_API_KEY"))

    if requested and not has_key:
        _REAL_API_RUNTIME_ENABLED = False
        return {
            "enabled": False,
            "usable": False,
            "api_key_configured": False,
            "request_api_key_applied": request_has_key,
            "error": "GEMINI_API_KEY is not configured on backend",
        }

    _REAL_API_RUNTIME_ENABLED = requested
    return {
        "enabled": _REAL_API_RUNTIME_ENABLED,
        "usable": _REAL_API_RUNTIME_ENABLED and has_key,
        "api_key_configured": has_key,
        "request_api_key_applied": request_has_key,
    }


def _rag_stats(body: JsonDict) -> JsonDict:
    raw_keywords = body.get("keywords")
    if isinstance(raw_keywords, list):
        keywords = tuple(str(item).strip() for item in raw_keywords if str(item).strip())
    else:
        keywords = cli.DEFAULT_RAG_STATS_KEYWORDS
    return cli.run_rag_stats(
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        keywords=keywords,
    )


def _rag_search(body: JsonDict) -> JsonDict:
    from dataclasses import asdict
    from typing import cast

    from investment_assistant.rag.search import SearchResult, enhanced_search
    from investment_assistant.rag.store import RagStore

    query = _require_str(body, "query")
    db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
    limit = _as_int(body.get("limit"), 5)
    hybrid = _as_bool(body.get("hybrid"), True)
    alpha = _as_float(body.get("alpha"), 0.5)
    enhanced = _as_bool(body.get("enhanced"), True)
    if not enhanced:
        results = cli.run_rag_search(
            query=query,
            db_path=db_path,
            limit=limit,
            hybrid=hybrid,
            alpha=alpha,
        )
        return {
            "query": query,
            "queries": [query],
            "results": results,
            "diagnostics": {
                "mode": "legacy_hybrid" if hybrid else "legacy_lexical",
                "query_count": 1,
                "candidate_count": len(results),
                "limit": limit,
                "hybrid_alpha": alpha if hybrid else None,
                "operators": [],
                "non_advisory_boundary": (
                    "検索結果は根拠候補の提示のみ。"
                    "売買判断や自動売買には使わない。"
                ),
            },
        }
    payload = enhanced_search(
        RagStore(db_path),
        query=query,
        limit=limit,
        hybrid=hybrid,
        alpha=alpha,
        query_expansion=_as_bool(body.get("query_expansion"), True),
        max_queries=_as_int(body.get("max_queries"), 4),
        rrf_k=_as_int(body.get("rrf_k"), 60),
        max_per_source=_as_int(body.get("max_per_source"), 3),
    )
    search_results = cast(list[SearchResult], payload["results"])
    return {
        **payload,
        "results": [asdict(result) for result in search_results],
        "auto_trading": False,
        "call_real_api": False,
    }


def _rag_answer_context(body: JsonDict) -> JsonDict:
    return cli.run_rag_answer_context(
        query=_require_str(body, "query"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 5),
    )


def _rag_answer(body: JsonDict) -> JsonDict:
    call_real_api, real_api_note = _real_api_decision(body)
    result = cli.run_rag_answer(
        query=_require_str(body, "query"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 5),
        call_real_api=call_real_api,
    )
    if real_api_note:
        result["real_api_note"] = real_api_note
    return result


def _resolve_stock_score(
    body: JsonDict, target_source: str, financials_csv: str
) -> dict[str, object] | None:
    from investment_assistant.financials.evidence import ticker_from_source
    from investment_assistant.scoring.stock import STRATEGY_LABELS, score_for_ticker

    ticker = str(body.get("ticker") or "").strip() or ticker_from_source(target_source or None)
    if not ticker:
        return None
    strategy = str(body.get("strategy") or "balanced")
    row = score_for_ticker(ticker=ticker, financials_csv=financials_csv, strategy=strategy)
    if row is not None:
        row["strategy_label"] = STRATEGY_LABELS.get(strategy, strategy)
    return row


def _orchestrate(body: JsonDict) -> JsonDict:
    call_real_api, real_api_note = _real_api_decision(body)
    real_api_requested = _as_bool(body.get("call_real_api"), False)
    query = _require_str(body, "query")
    target_source_value = body.get("target_source")

    if target_source_value is not None and not isinstance(target_source_value, str):
        raise ApiError("target_source must be a string")

    target_source = (
        target_source_value.strip()
        if isinstance(target_source_value, str)
        else ""
    )

    source_constraint = (
        "\n\n【対象資料制約】"
        + f"\n対象資料: {target_source}"
        + "\n上記sourceのローカル文書だけを根拠にしてください。"
        + "\n他sourceの情報は混ぜず、不足する場合は不明・要追加取得と明記してください。"
        if target_source
        else ""
    )

    financials_csv = str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV)
    financial_evidence = build_financial_evidence(
        ticker=str(body.get("ticker") or "").strip() or None,
        target_source=target_source or None,
        csv_path=financials_csv,
    )
    # Inject the dividend-quality score for the resolved ticker (Chat <- Score).
    stock_score = _resolve_stock_score(body, target_source, financials_csv)
    if stock_score is not None and financial_evidence:
        financial_evidence += (
            f"\n配当品質スコア: {stock_score['total_score']} / 1.0"
            f"（戦略: {stock_score.get('strategy_label', 'バランス')}）"
        )
    evidence_block = (
        "\n\n"
        + financial_evidence
        + "\n上記の減配履歴・財務トレンド・スコアを根拠として明示的に反映してください。"
        if financial_evidence
        else ""
    )

    # The draft -> critique -> synthesis process and role rules live in the
    # orchestrator's prompts now, so the query only carries genuine grounding
    # (the question + source constraint + financial evidence). Retrieval uses the
    # raw question so injected evidence/constraints don't skew the RAG search.
    generation_query = query + source_constraint + evidence_block

    result = cli.run_orchestrate_answer(
        query=generation_query,
        search_query=query,
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 16),
        drafts=3,
        include_critique=bool(body.get("critique", True)),
        hybrid=bool(body.get("hybrid", True)),
        alpha=_as_float(body.get("alpha"), 0.5),
        call_real_api=call_real_api,
        source_filter=target_source or None,
    )

    result["target_source"] = target_source or None
    result["financial_evidence"] = financial_evidence
    result["stock_score"] = stock_score

    result["orchestration"] = {
        "drafter": "AI 1/2/3",
        "critic": "Reviewer",
        "synthesizer": "Synthesizer",
        "drafts": 3,
        "call_real_api": call_real_api,
        "real_api_requested": real_api_requested,
        "api_key_supplied": bool(_request_api_key(body)),
    }

    if real_api_note:
        result["real_api_note"] = real_api_note

    return _finalize_answer(
        result,
        real_api_requested=real_api_requested,
        query=query,
    )


def _rag_index_dir(body: JsonDict) -> JsonDict:
    return cli.run_rag_index_dir(
        path=_require_str(body, "path"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
    )


def _manual_doc_save(body: JsonDict) -> JsonDict:
    text = _require_str(body, "text")
    if len(text) > _MAX_MANUAL_TEXT_CHARS:
        raise ApiError(f"text is too long: max {_MAX_MANUAL_TEXT_CHARS} characters")

    title = str(body.get("title") or "manual-note").strip() or "manual-note"
    db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
    raw_source_url = body.get("source_url")
    source_url = raw_source_url.strip() if isinstance(raw_source_url, str) else ""

    manual_dir = Path("local_docs") / "manual"
    manual_dir.mkdir(parents=True, exist_ok=True)
    save_path = _unique_path(manual_dir / _safe_manual_doc_filename(title))

    saved_at = datetime.now(UTC).isoformat()
    metadata = [
        "# Manual imported investment document",
        f"title: {title}",
        f"saved_at: {saved_at}",
    ]
    if source_url:
        metadata.append(f"source_url: {source_url}")
    content = "\n".join(metadata) + "\n\n" + text.strip() + "\n"
    save_path.write_text(content, encoding="utf-8")

    indexed = cli.run_rag_index(path=save_path, db_path=db_path)
    return {
        "saved_path": str(save_path),
        "chars": len(text),
        "source_url": source_url or None,
        "indexed": indexed,
    }


def _scoring_rank(body: JsonDict) -> JsonDict:
    csv_text = body.get("csv_text")
    if csv_text:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".csv",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(str(csv_text))
            path = handle.name
        try:
            return cli.run_scoring_rank(path=path, limit=_as_int(body.get("limit"), 10))
        finally:
            Path(path).unlink(missing_ok=True)
    return cli.run_scoring_rank(
        path=_require_str(body, "path"),
        limit=_as_int(body.get("limit"), 10),
    )


def _scoring_stocks(body: JsonDict) -> JsonDict:
    from investment_assistant.scoring.stock import run_stock_scoring

    min_equity = body.get("min_equity_ratio")
    limit_value = _as_int(body.get("limit"), 0)
    return run_stock_scoring(
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        strategy=str(body.get("strategy") or "balanced"),
        exclude_dividend_cut=_as_bool(body.get("exclude_dividend_cut"), False),
        min_equity_ratio=_as_float(min_equity, 0.0) if min_equity is not None else None,
        min_periods=_as_int(body.get("min_periods"), 1),
        limit=limit_value or None,
    )


def _forecast_evaluate(body: JsonDict) -> JsonDict:
    return cli.run_forecast_evaluate(
        path=str(body.get("path") or _SAMPLE_SP500),
        value_column=str(body.get("value_column") or "SP500"),
        horizon=_as_int(body.get("horizon"), 1),
        step=_as_int(body.get("step"), 1),
        tail=None if body.get("tail") is None else _as_int(body.get("tail"), 0),
        include_ml=bool(body.get("include_ml", False)),
        ensemble_method=str(body.get("ensemble_method") or "weighted"),
        space=str(body.get("space") or "returns"),
        ma_windows=_as_int_tuple(body.get("ma_windows")),
    )


def _forecast_predict(body: JsonDict) -> JsonDict:
    return cli.run_forecast_predict(
        path=str(body.get("path") or _SAMPLE_SP500),
        value_column=str(body.get("value_column") or "SP500"),
        horizon=_as_int(body.get("horizon"), 1),
        include_ml=bool(body.get("include_ml", False)),
        space=str(body.get("space") or "returns"),
    )


def _cache_maintenance(body: JsonDict) -> JsonDict:
    max_rows = body.get("max_rows")
    return cli.run_cache_maintenance(
        config_path=DEFAULT_GEMINI_CONFIG_PATH,
        max_rows=None if max_rows is None else _as_int(max_rows, 0),
    )


def _fetch_job(body: JsonDict, *, dry_run: bool) -> JsonDict:
    path = body.get("path")
    if path:
        return cli.run_fetch_job(path=str(path), dry_run=dry_run)
    return _run_fetch_job_sources(_require_sources(body), dry_run=dry_run)


def _fetch_job_auto(body: JsonDict) -> JsonDict:
    sources = _require_sources(body)
    db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
    index_path = str(body.get("index_path") or "local_docs")
    index_after_fetch = _as_bool(body.get("index_after_fetch"), True)

    dry_run = _run_fetch_job_sources(sources, dry_run=True)
    allowed_sources, blocked = _filter_allowed_sources(sources, dry_run)
    run_result: JsonDict | None = None
    index_result: JsonDict | None = None

    if allowed_sources:
        run_result = _run_fetch_job_sources(allowed_sources, dry_run=False)
        if index_after_fetch:
            index_result = cli.run_rag_index_dir(path=index_path, db_path=db_path)

    return {
        "status": "completed" if allowed_sources else "blocked",
        "policy": {
            "robots_checked": True,
            "robots_blocked_count": len(blocked),
            "ssrf_protection": True,
            "rate_limit": True,
            "response_size_limit": True,
            "auto_trading": False,
        },
        "dry_run": dry_run,
        "run": run_result,
        "index": index_result,
        "allowed_sources_count": len(allowed_sources),
        "blocked_results": blocked,
    }


def _financials_refresh(body: JsonDict) -> JsonDict:
    """Refresh financial data through the safest available official path.

    Structured financial metrics come from EDINET API CSV/XBRL, because the
    report and screening engine need deterministic, auditable values. When the
    EDINET API key is not configured, we still run the official disclosure-page
    scraping path for RAG grounding, but we intentionally do not claim that the
    structured ``financials.csv`` was updated.
    """

    from investment_assistant.edinet.client import API_KEY_ENV_VAR

    _ensure_env_from_dotenv(API_KEY_ENV_VAR)
    registry_path = str(
        body.get("registry_path") or "examples/source_registry_nikkei225_edinet.yaml"
    )
    output_dir = str(body.get("output_dir") or "local_docs/edinet")
    financials_csv = str(Path(output_dir) / "financials.csv")
    db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
    index_after_fetch = _as_bool(body.get("index_after_fetch"), True)

    if os.getenv(API_KEY_ENV_VAR, "").strip():
        result = _edinet_ingest(
            {
                **body,
                "registry_path": registry_path,
                "output_dir": output_dir,
                "db_path": db_path,
                "index_after_fetch": index_after_fetch,
            }
        )
        result["mode"] = "edinet_api"
        result["api_key_configured"] = True
        result["financials_updated"] = bool(result.get("financials_csv"))
        result["financials_csv"] = str(result.get("financials_csv") or financials_csv)
        result["official_sources"] = [
            {
                "label": "EDINET API v2",
                "url": "https://disclosure2.edinet-fsa.go.jp/",
                "purpose": "有価証券報告書等の公式CSV/XBRL取得",
            }
        ]
        result["hint"] = (
            "EDINET公式APIのCSV/XBRLから財務データを更新しました。"
            "候補抽出、詳細、レポートはこのCSVを参照します。"
        )
        return result

    scrape_result = _fetch_job_auto(
        {
            "sources": _default_disclosure_sources(),
            "db_path": db_path,
            "index_path": "local_docs",
            "index_after_fetch": index_after_fetch,
        }
    )
    return {
        "mode": "disclosure_scrape_only",
        "api_key_configured": False,
        "financials_updated": False,
        "financials_csv": financials_csv,
        "scrape": scrape_result,
        "official_sources": [
            {
                "label": "EDINET 閲覧サイト",
                "url": "https://disclosure2.edinet-fsa.go.jp/",
                "purpose": "開示ページの確認とRAG根拠取得",
            },
            {
                "label": "TDnet",
                "url": "https://www.release.tdnet.info/inbs/I_main_00.html",
                "purpose": "適時開示ページの確認とRAG根拠取得",
            },
            {
                "label": "JPX 東証上場銘柄一覧",
                "url": "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html",
                "purpose": "市場区分と銘柄名の確認",
            },
        ],
        "hint": (
            "EDINET API KEYがバックエンドに未設定のため、構造化された財務CSVは更新していません。"
            "公式ページの取得とRAG登録だけを実行しました。"
            "財務数値の更新はAPI KEY設定後に再実行してください。"
        ),
        "auto_trading": False,
        "call_real_api": False,
    }


def _financials_refresh_async(body: JsonDict) -> JsonDict:
    job_id = JOBS.start("financials-refresh", lambda: _financials_refresh(body))
    return {"job_id": job_id, "status": "running", "kind": "financials-refresh"}



def _edinet_ingest(body: JsonDict) -> JsonDict:
    from investment_assistant.edinet.client import API_KEY_ENV_VAR

    _ensure_env_from_dotenv(API_KEY_ENV_VAR)
    registry_path = str(
        body.get("registry_path") or "examples/source_registry_edinet_sample.yaml"
    )
    end_date_value = body.get("end_date")
    end_date = str(end_date_value).strip() if end_date_value else None
    max_periods_value = body.get("max_periods")
    max_periods = _as_int(max_periods_value, 0) if max_periods_value is not None else None
    years_value = body.get("years")
    years = _as_int(years_value, 0) if years_value is not None else None
    return cli.run_edinet_ingest(
        registry_path=registry_path,
        end_date=end_date or None,
        days=_as_int(body.get("days"), 7),
        years=years if years and years > 0 else None,
        output_dir=str(body.get("output_dir") or "local_docs/edinet"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        index_after=_as_bool(body.get("index_after_fetch"), True),
        max_periods=max_periods if max_periods and max_periods > 0 else None,
    )


def _operators_catalog(_: JsonDict) -> JsonDict:
    from investment_assistant.investment.operators import operator_catalog

    return operator_catalog()


def _edinet_ingest_async(body: JsonDict) -> JsonDict:
    """Start an EDINET ingest in the background and return a job id to poll.

    A multi-year / many-ticker ingest runs for minutes and would otherwise time
    out the editor's port-forward proxy as an HTTP 504. The work runs on a
    daemon thread; the frontend polls ``/api/jobs/status``.
    """

    job_id = JOBS.start("edinet-ingest", lambda: _edinet_ingest(body))
    return {"job_id": job_id, "status": "running", "kind": "edinet-ingest"}


def _job_status(body: JsonDict) -> JsonDict:
    job_id = _require_str(body, "job_id")
    job = JOBS.get(job_id)
    if job is None:
        raise ApiError(f"unknown job_id: {job_id}")
    return job


def _feedback(body: JsonDict) -> JsonDict:
    from investment_assistant.feedback import DEFAULT_FEEDBACK_DB_PATH, FeedbackStore

    raw_sources = body.get("sources")
    sources = [str(item) for item in raw_sources] if isinstance(raw_sources, list) else []
    store = FeedbackStore(str(body.get("feedback_db") or DEFAULT_FEEDBACK_DB_PATH))
    try:
        result = store.record(
            rating=_require_str(body, "rating"),
            sources=sources,
            question=str(body.get("question") or ""),
            answer_preview=str(body.get("answer_preview") or ""),
        )
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    result["summary"] = store.summary()
    return result


def _feedback_stats(body: JsonDict) -> JsonDict:
    from investment_assistant.feedback import DEFAULT_FEEDBACK_DB_PATH, FeedbackStore

    return FeedbackStore(str(body.get("feedback_db") or DEFAULT_FEEDBACK_DB_PATH)).summary()


def _knowledge_diff(body: JsonDict) -> JsonDict:
    from investment_assistant import knowledge

    return knowledge.run_knowledge_diff(
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        snapshot_path=str(body.get("snapshot_path") or knowledge.DEFAULT_SNAPSHOT_PATH),
        save=_as_bool(body.get("save"), True),
    )


def _storage_prune(body: JsonDict) -> JsonDict:
    from investment_assistant import maintenance
    from investment_assistant.ingestion.fetcher import DEFAULT_HTTP_CACHE_PATH

    raw_roots = body.get("docs_roots")
    roots: list[str | Path] = (
        [str(item) for item in raw_roots]
        if isinstance(raw_roots, list) and raw_roots
        else ["local_docs/edinet", "local_docs/crawl"]
    )
    prune_cache = _as_bool(body.get("prune_cache"), True)
    cache_path = str(body.get("cache_path") or DEFAULT_HTTP_CACHE_PATH) if prune_cache else None
    return maintenance.run_storage_prune(
        docs_roots=roots,
        cache_path=cache_path,
        keep_per_dir=_as_int(body.get("keep_per_dir"), 8),
        http_max_rows=_as_int(body.get("http_max_rows"), 500),
    )


def _portfolio_dividends(body: JsonDict) -> JsonDict:
    path = str(body.get("path") or "examples/portfolio_dividends_sample.csv")
    return summarize_dividends(load_dividends(path))


def _portfolio_simulate(body: JsonDict) -> JsonDict:
    from investment_assistant.portfolio.simulator import simulate_portfolio

    raw = body.get("holdings")
    holdings = [h for h in raw if isinstance(h, dict)] if isinstance(raw, list) else []
    return simulate_portfolio(
        budget=_as_float(body.get("budget"), 0.0),
        holdings=holdings,
        years=_as_int(body.get("years"), 10),
        reinvest=_as_bool(body.get("reinvest"), True),
        growth_rate=_as_float(body.get("growth_rate"), 0.0),
        auto_weight=str(body.get("auto_weight") or "equal"),
        optimization=str(body.get("optimization") or "none"),
        dividend_basis=str(body.get("dividend_basis") or "conservative"),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
    )


def _portfolio_target(body: JsonDict) -> JsonDict:
    from investment_assistant.portfolio.simulator import plan_for_target_dividend

    raw = body.get("holdings")
    holdings = [h for h in raw if isinstance(h, dict)] if isinstance(raw, list) else []
    return plan_for_target_dividend(
        target_annual_dividend=_as_float(body.get("target_annual_dividend"), 0.0),
        net_target=_as_bool(body.get("net_target"), False),
        holdings=holdings,
        years=_as_int(body.get("years"), 10),
        reinvest=_as_bool(body.get("reinvest"), True),
        growth_rate=_as_float(body.get("growth_rate"), 0.0),
        auto_weight=str(body.get("auto_weight") or "equal"),
        optimization=str(body.get("optimization") or "none"),
        dividend_basis=str(body.get("dividend_basis") or "conservative"),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
    )


def _portfolio_universe(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.universe import build_market_universe
    from investment_assistant.portfolio.simulator import build_universe

    raw_prices = body.get("prices")
    prices = (
        {str(k): _as_float(v, 0.0) for k, v in raw_prices.items()}
        if isinstance(raw_prices, dict)
        else None
    )
    financials_csv = str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV)
    if not Path(financials_csv).is_file():
        return {
            "available": False,
            "universe": [],
            "count": 0,
            "source_ref": financials_csv,
            "hint": (
                "財務データがまだ作成されていません。DataタブでEDINET取得/手動保存を行うか、"
                "サンプルデータに切り替えてください。"
            ),
            "auto_trading": False,
            "call_real_api": False,
        }
    try:
        universe = build_universe(financials_csv, prices=prices)
    except FileNotFoundError:
        return {
            "available": False,
            "universe": [],
            "count": 0,
            "source_ref": financials_csv,
            "hint": (
                "財務データがまだ作成されていません。DataタブでEDINET取得/手動保存を行うか、"
                "サンプルデータに切り替えてください。"
            ),
            "auto_trading": False,
            "call_real_api": False,
        }
    scope = str(body.get("scope") or "financials")
    market = build_market_universe(
        financials_csv=financials_csv,
        jpx_listed_path=str(body.get("jpx_listed_path") or "local_docs/jpx/listed_issues.csv"),
        query="",
        scope="all",
        limit=10000,
    )
    raw_market_rows = market.get("securities")
    market_rows = {
        str(row.get("ticker") or row.get("code") or ""): row
        for row in (raw_market_rows if isinstance(raw_market_rows, list) else [])
        if isinstance(row, dict)
    }
    enriched: list[dict[str, object]] = []
    for row in universe:
        ticker = str(row.get("ticker") or "")
        meta = market_rows.get(ticker, {})
        enriched_row = {
            **row,
            "market_segment": meta.get("market_segment", "未取込"),
            "sector": meta.get("sector", ""),
            "is_prime": bool(meta.get("is_prime")),
            "is_nikkei225": bool(meta.get("is_nikkei225")),
            "has_financials": True,
        }
        if _market_scope_matches(enriched_row, scope):
            enriched.append(enriched_row)
    return {
        "available": True,
        "universe": enriched,
        "count": len(enriched),
        "scope": scope,
        "source_ref": financials_csv,
        "market_sources": market.get("sources"),
        "jpx_listed_available": market.get("jpx_listed_available"),
        "hint": market.get("hint"),
        "auto_trading": False,
        "call_real_api": False,
    }


def _market_universe(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.universe import build_market_universe

    return build_market_universe(
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        jpx_listed_path=str(body.get("jpx_listed_path") or "local_docs/jpx/listed_issues.csv"),
        nikkei225_registry=str(
            body.get("nikkei225_registry") or "examples/source_registry_nikkei225_edinet.yaml"
        ),
        query=str(body.get("query") or ""),
        scope=str(body.get("scope") or body.get("universe") or "prime"),
        limit=max(_as_int(body.get("limit"), 50), 1),
    )


def _jpx_listed_template(_: JsonDict) -> JsonDict:
    from investment_assistant.investment.universe import jpx_listed_issue_template

    return jpx_listed_issue_template()


def _jpx_listed_import(body: JsonDict) -> JsonDict:
    from investment_assistant.ingestion.fetcher import reject_path_traversal
    from investment_assistant.investment.universe import (
        DEFAULT_JPX_LISTED_ISSUES_PATH,
        parse_jpx_listed_issues_text,
        source_manifest,
        write_jpx_listed_issues,
    )

    text = str(body.get("csv_text") or body.get("text") or "")
    source_ref = "screen_input"
    path_value = str(body.get("path") or "").strip()
    if not text.strip() and path_value:
        path = Path(path_value)
        if path.suffix.lower() == ".xls":
            raise ApiError(
                "JPX公式ファイルは旧Excel形式です。Excel等でCSV/TSVに変換してから取り込んでください。"
            )
        text = path.read_text(encoding="utf-8")
        source_ref = str(path)
    if not text.strip():
        raise ApiError("JPX上場銘柄一覧データを貼り付けるか、CSV/TSV path を指定してください。")

    issues = parse_jpx_listed_issues_text(text, source_ref=source_ref)
    output_path = str(body.get("output_path") or DEFAULT_JPX_LISTED_ISSUES_PATH)
    saved_path: str | None = None
    if _as_bool(body.get("save"), True):
        target = reject_path_traversal(output_path)
        saved_path = write_jpx_listed_issues(issues, target)
    prime_count = sum(1 for issue in issues if issue.is_prime)
    return {
        "available": True,
        "count": len(issues),
        "prime_count": prime_count,
        "saved": saved_path is not None,
        "saved_path": saved_path,
        "sample": [issue.to_dict() for issue in issues[:20]],
        "sources": source_manifest(),
        "disclaimer": "市場区分は銘柄選択補助です。投資助言や売買推奨ではありません。",
        "auto_trading": False,
        "call_real_api": False,
    }


def _jpx_listed_download(body: JsonDict) -> JsonDict:
    from investment_assistant.ingestion.fetcher import SafeFetcher, reject_path_traversal
    from investment_assistant.investment.universe import (
        JPX_LISTED_ISSUES_FILE_URL,
        JPX_LISTED_ISSUES_PAGE_URL,
        source_manifest,
    )

    url = str(body.get("url") or JPX_LISTED_ISSUES_FILE_URL)
    output_path = str(body.get("output_path") or "local_docs/jpx/data_j.xls")
    fetcher = SafeFetcher(timeout_seconds=30.0)
    decision = fetcher.robots.can_fetch(url)
    if not decision.allowed:
        return {
            "available": False,
            "downloaded": False,
            "source_url": url,
            "robots_url": decision.robots_url,
            "reason": decision.reason,
            "hint": "robots.txtで許可されていないため自動取得しません。",
            "sources": source_manifest(),
            "auto_trading": False,
            "call_real_api": False,
        }
    response = fetcher.transport.get(
        url,
        timeout_seconds=30.0,
        user_agent=fetcher.user_agent,
    )
    if response.status_code >= 400:
        raise ApiError(f"JPXファイル取得に失敗しました: status={response.status_code}")
    target = reject_path_traversal(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.body)
    is_legacy_xls = response.body.startswith(bytes.fromhex("d0cf11e0a1b11ae1"))
    return {
        "available": True,
        "downloaded": True,
        "saved_path": str(target),
        "bytes": len(response.body),
        "status_code": response.status_code,
        "source_url": url,
        "source_page_url": JPX_LISTED_ISSUES_PAGE_URL,
        "robots_url": decision.robots_url,
        "parse_supported": not is_legacy_xls,
        "file_format": "legacy_xls" if is_legacy_xls else "text_or_unknown",
        "hint": (
            "公式ファイルを取得しました。旧Excel形式のため、Excel等でCSV/TSVに変換して"
            "市場区分データとして保存してください。"
            if is_legacy_xls
            else "取得ファイルを市場区分データとして取り込めます。"
        ),
        "sources": source_manifest(),
        "auto_trading": False,
        "call_real_api": False,
    }


def _market_prices(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.provider_policy import ensure_provider_allowed
    from investment_assistant.portfolio.prices import fetch_prices

    raw = body.get("tickers")
    tickers = [str(t) for t in raw] if isinstance(raw, list) else []
    provider_id = str(body.get("provider_id") or "stooq_public_csv")
    runtime_mode = str(
        body.get("runtime_mode")
        or os.getenv("INVESTMENT_ASSISTANT_RUNTIME_MODE")
        or "development"
    )
    try:
        policy = ensure_provider_allowed(provider_id, runtime_mode=runtime_mode)
    except ValueError as exc:
        raise ApiError(str(exc), status=400) from exc
    result = fetch_prices(tickers)
    result["provider_policy"] = policy.to_dict()
    return result


def _provider_policy_ledger(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.provider_policy import provider_policy_ledger

    raw_provider_ids = body.get("provider_ids")
    provider_ids = (
        [str(provider_id) for provider_id in raw_provider_ids]
        if isinstance(raw_provider_ids, list)
        else None
    )
    return provider_policy_ledger(
        runtime_mode=str(body.get("runtime_mode") or "development"),
        provider_ids=provider_ids,
    )


def _portfolio_performance(body: JsonDict) -> JsonDict:
    path = str(body.get("path") or "examples/portfolio_performance_sample.csv")
    return summarize_performance(load_performance(path))


def _financials_compare(body: JsonDict) -> JsonDict:
    path = str(body.get("path") or "examples/financials_sample.csv")
    return compare_financials(load_financials(path))


def _financials_status(body: JsonDict) -> JsonDict:
    path = Path(str(body.get("path") or body.get("financials_csv") or DEFAULT_FINANCIALS_CSV))
    stale_after_days = max(_as_int(body.get("stale_after_days"), 7), 1)
    if not path.is_file():
        return {
            "available": False,
            "status": "missing",
            "path": str(path),
            "point_count": 0,
            "company_count": 0,
            "latest_fiscal_year": None,
            "modified_at": None,
            "age_days": None,
            "stale_after_days": stale_after_days,
            "hint": (
                "財務データがまだありません。"
                "DataタブでEDINET取得または手動保存を行ってください。"
            ),
            "auto_trading": False,
            "call_real_api": False,
        }
    try:
        points = load_financials(path)
        comparison = compare_financials(points)
    except (ValueError, OSError) as exc:
        return {
            "available": False,
            "status": "invalid",
            "path": str(path),
            "point_count": 0,
            "company_count": 0,
            "latest_fiscal_year": None,
            "modified_at": None,
            "age_days": None,
            "stale_after_days": stale_after_days,
            "hint": f"財務データを読み込めません: {type(exc).__name__}: {exc}",
            "auto_trading": False,
            "call_real_api": False,
        }
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
    age_days = (datetime.now(UTC) - modified_at).total_seconds() / 86400
    companies = comparison.get("companies")
    rows = companies if isinstance(companies, list) else []
    latest_years = [
        _as_int(row.get("latest_fiscal_year"), 0)
        for row in rows
        if isinstance(row, dict)
    ]
    is_stale = age_days > stale_after_days
    return {
        "available": True,
        "status": "stale" if is_stale else "fresh",
        "path": str(path),
        "point_count": len(points),
        "company_count": len(rows),
        "latest_fiscal_year": max(latest_years) if latest_years else None,
        "modified_at": modified_at.isoformat(),
        "age_days": round(age_days, 2),
        "stale_after_days": stale_after_days,
        "hint": (
            "更新推奨です。Dataタブで最新7日取得またはバックフィルを実行してください。"
            if is_stale
            else "財務データは利用可能です。必要に応じてDataタブから更新できます。"
        ),
        "auto_trading": False,
        "call_real_api": False,
    }


def _financials_import(body: JsonDict) -> JsonDict:
    from investment_assistant.financials.models import FINANCIAL_COLUMNS
    from investment_assistant.ingestion.fetcher import reject_path_traversal

    raw_csv_text = body.get("csv_text")
    csv_text = raw_csv_text if isinstance(raw_csv_text, str) else ""
    save = _as_bool(body.get("save"), False)
    cleanup: Path | None = None
    source = "path"
    source_ref: str
    normalized_csv: str

    if csv_text.strip():
        if len(csv_text) > _MAX_MANUAL_TEXT_CHARS:
            raise ApiError(f"csv_text is too long: max {_MAX_MANUAL_TEXT_CHARS} characters")
        normalized_csv = csv_text.strip() + "\n"
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".csv",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(normalized_csv)
            source_ref = handle.name
        cleanup = Path(source_ref)
        source = "csv_text"
    else:
        source_ref = _require_str(body, "path")
        normalized_csv = Path(source_ref).read_text(encoding="utf-8")

    try:
        points = load_financials(source_ref)
    finally:
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)

    comparison = compare_financials(points)
    saved_path: str | None = None
    output_path = str(body.get("output_path") or DEFAULT_FINANCIALS_CSV)
    if save:
        target = reject_path_traversal(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(normalized_csv, encoding="utf-8")
        saved_path = str(target)

    companies = comparison.get("companies")
    company_count = len(companies) if isinstance(companies, list) else 0
    return {
        "available": True,
        "source": source,
        "source_ref": None if source == "csv_text" else source_ref,
        "saved": save,
        "saved_path": saved_path,
        "financials_csv": saved_path or (None if source == "csv_text" else source_ref),
        "columns": list(FINANCIAL_COLUMNS),
        "count": len(points),
        "company_count": company_count,
        "comparison": comparison,
        "disclaimer": comparison.get("disclaimer"),
        "auto_trading": False,
        "call_real_api": False,
    }


def _financials_securities(body: JsonDict) -> JsonDict:
    path = str(
        body.get("financials_csv")
        or body.get("path")
        or DEFAULT_FINANCIALS_CSV
    )
    query = str(body.get("query") or "").strip().lower()
    limit = max(_as_int(body.get("limit"), 20), 1)
    if not Path(path).is_file():
        return {
            "available": False,
            "query": query,
            "source_ref": path,
            "count": 0,
            "securities": [],
            "hint": (
                "財務データが見つかりません。DataタブでEDINET取得/手動保存を行うか、"
                "上部の財務データをサンプルデータに切り替えてください。"
            ),
            "auto_trading": False,
            "call_real_api": False,
        }
    comparison = compare_financials(load_financials(path))
    companies = comparison.get("companies")
    rows = companies if isinstance(companies, list) else []
    matches: list[dict[str, object]] = []
    for company in rows:
        if not isinstance(company, dict):
            continue
        ticker = str(company.get("ticker") or "")
        name = str(company.get("name") or "")
        haystack = f"{ticker} {name}".lower()
        if query and query not in haystack:
            continue
        matches.append(
            {
                "ticker": ticker,
                "code": ticker,
                "name": name,
                "latest_fiscal_year": company.get("latest_fiscal_year"),
                "latest_equity_ratio": company.get("latest_equity_ratio"),
                "latest_dividend_per_share": company.get("latest_dividend_per_share"),
                "dividend_cut_years": company.get("dividend_cut_years"),
                "operating_cf_trend": company.get("operating_cf_trend"),
                "source_ref": path,
            }
        )
        if len(matches) >= limit:
            break
    return {
        "available": True,
        "query": query,
        "source_ref": path,
        "count": len(matches),
        "securities": matches,
        "auto_trading": False,
        "call_real_api": False,
    }


def _holdings_import(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.loader import (
        holding_input_warnings,
        holdings_from_payload,
    )
    from investment_assistant.investment.models import (
        DISCLAIMER,
        HOLDING_COLUMNS,
        HOLDING_RECOMMENDED_COLUMNS,
    )

    holdings = holdings_from_payload(body)
    return {
        "count": len(holdings),
        "holdings": [holding.to_dict() for holding in holdings],
        "required_columns": list(HOLDING_COLUMNS),
        "recommended_columns": list(HOLDING_RECOMMENDED_COLUMNS),
        "input_warnings": holding_input_warnings(body, holdings),
        "disclaimer": DISCLAIMER,
        "auto_trading": False,
        "call_real_api": False,
    }


def _holdings_validate(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import validate_holdings_payload

    return validate_holdings_payload(body)


def _holdings_template(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import holding_csv_template

    return holding_csv_template(include_examples=_as_bool(body.get("include_examples"), False))


def _funds_validate(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import validate_fund_profiles_payload

    return validate_fund_profiles_payload(body)


def _funds_template(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import fund_profile_csv_template

    return fund_profile_csv_template(
        include_examples=_as_bool(body.get("include_examples"), False)
    )


def _portfolio_analyze(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import analyze_portfolio, holdings_from_payload

    return analyze_portfolio(
        holdings_from_payload(body),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        runtime_mode=str(body.get("runtime_mode") or "development"),
    )


def _investment_detail(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import (
        build_investment_detail,
        fund_profiles_from_payload,
        holdings_from_payload,
    )

    holdings = holdings_from_payload(body) if _has_any(body, "holdings", "csv_text", "path") else []
    return build_investment_detail(
        code=str(body.get("code") or body.get("ticker_or_fund_code") or ""),
        asset_type=str(body.get("asset_type") or ""),
        holdings=holdings,
        funds=fund_profiles_from_payload(body),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
    )


def _candidates_screen(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import fund_profiles_from_payload, screen_candidates
    from investment_assistant.investment.candidates import screen_from_values

    raw_asset_types = body.get("asset_types")
    asset_types = (
        [str(item) for item in raw_asset_types]
        if isinstance(raw_asset_types, list)
        else ["stock", "fund"]
    )
    limit_value = body.get("limit")
    screen = screen_from_values(
        asset_types=asset_types,
        exclude_dividend_cut=_as_bool(body.get("exclude_dividend_cut"), False),
        min_equity_ratio=_optional_float(body.get("min_equity_ratio")),
        max_expense_ratio=_optional_float(body.get("max_expense_ratio")),
        nisa_eligible_only=_as_bool(body.get("nisa_eligible_only"), False),
        min_diversification_score=_optional_float(body.get("min_diversification_score")),
        sort_by=str(body.get("sort_by") or "score"),
        limit=None if limit_value is None else _as_int(limit_value, 0),
    )
    return screen_candidates(
        screen=screen,
        funds=fund_profiles_from_payload(body),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        runtime_mode=str(body.get("runtime_mode") or "development"),
    )


def _investment_monthly_report(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import (
        build_investment_monthly_report,
        holdings_from_payload,
    )
    from investment_assistant.investment.report_history import save_investment_report
    from investment_assistant.portfolio.simulator import plan_for_target_dividend

    raw_candidates = body.get("candidates")
    candidates: list[dict[str, object]] = []
    if isinstance(raw_candidates, list):
        candidates = [
            {str(key): value for key, value in item.items()}
            for item in raw_candidates
            if isinstance(item, dict)
        ]
    holdings = holdings_from_payload(body)
    financials_csv = str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV)
    target_result: JsonDict | None = None
    target_annual_dividend = _as_float(body.get("target_annual_dividend"), 0.0)
    if target_annual_dividend > 0:
        target_result = plan_for_target_dividend(
            target_annual_dividend=target_annual_dividend,
            holdings=_target_planner_holdings(holdings),
            years=_as_int(body.get("years"), 10),
            reinvest=_as_bool(body.get("reinvest"), True),
            growth_rate=_as_float(body.get("growth_rate"), 0.0),
            auto_weight=str(body.get("auto_weight") or "equal"),
            optimization=str(body.get("optimization") or "balanced"),
            dividend_basis=str(body.get("dividend_basis") or "conservative"),
            financials_csv=financials_csv,
        )
    report = build_investment_monthly_report(
        holdings,
        candidates=candidates,
        target_result=target_result,
        financials_csv=financials_csv,
        runtime_mode=str(body.get("runtime_mode") or "development"),
    )
    if _as_bool(body.get("save_history"), True):
        report["history"] = save_investment_report(
            report,
            history_dir=_optional_history_dir(body),
            max_entries=_as_int(body.get("history_limit"), 50),
        )
    return report


def _investment_report_history(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import list_investment_reports

    return list_investment_reports(
        history_dir=_optional_history_dir(body),
        limit=_as_int(body.get("limit"), 20),
    )


def _investment_report_history_load(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import load_investment_report

    report_id = str(body.get("id") or body.get("report_id") or "").strip()
    if not report_id:
        raise ApiError("report history id is required")
    return load_investment_report(report_id, history_dir=_optional_history_dir(body))


def _investment_report_history_delete(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import delete_investment_report

    report_id = str(body.get("id") or body.get("report_id") or "").strip()
    if not report_id:
        raise ApiError("report history id is required")
    return delete_investment_report(report_id, history_dir=_optional_history_dir(body))


def _investment_report_history_verify(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import verify_investment_report_history

    report_id = str(body.get("id") or body.get("report_id") or "").strip()
    if not report_id:
        raise ApiError("report history id is required")
    return verify_investment_report_history(report_id, history_dir=_optional_history_dir(body))


def _investment_report_history_compare(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_compare import compare_investment_reports
    from investment_assistant.investment.report_history import load_investment_report

    base_id = str(body.get("base_id") or "").strip()
    compare_id = str(body.get("compare_id") or "").strip()
    if not base_id or not compare_id:
        raise ApiError("base_id and compare_id are required")
    history_dir = _optional_history_dir(body)
    return compare_investment_reports(
        load_investment_report(base_id, history_dir=history_dir),
        load_investment_report(compare_id, history_dir=history_dir),
    )


def _investment_report_markdown(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import load_investment_report
    from investment_assistant.investment.report_markdown import render_investment_report_markdown

    report = body.get("report")
    if not isinstance(report, dict):
        report_id = str(body.get("id") or body.get("report_id") or "").strip()
        if not report_id:
            raise ApiError("report or report history id is required")
        entry = load_investment_report(report_id, history_dir=_optional_history_dir(body))
        loaded_report = entry.get("report")
        if not isinstance(loaded_report, dict):
            raise ApiError("saved report is invalid")
        report = loaded_report
    return {
        "markdown": render_investment_report_markdown(report),
        "auto_trading": False,
        "call_real_api": False,
    }


def _investment_report_audit(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_audit import audit_investment_report
    from investment_assistant.investment.report_history import load_investment_report

    report = body.get("report")
    if not isinstance(report, dict):
        report_id = str(body.get("id") or body.get("report_id") or "").strip()
        if not report_id:
            raise ApiError("report or report history id is required")
        entry = load_investment_report(report_id, history_dir=_optional_history_dir(body))
        loaded_report = entry.get("report")
        if not isinstance(loaded_report, dict):
            raise ApiError("saved report is invalid")
        report = loaded_report
    return audit_investment_report(report)


def _target_planner_holdings(holdings: list[Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for holding in holdings:
        quantity = _as_float(getattr(holding, "quantity", 0.0), 0.0)
        price = _as_float(
            getattr(holding, "current_price", None),
            _as_float(getattr(holding, "avg_cost", 0.0), 0.0),
        )
        if quantity <= 0 or price <= 0:
            continue
        asset_type = str(getattr(holding, "asset_type", "") or "").lower()
        row: dict[str, object] = {
            "ticker": str(getattr(holding, "ticker_or_fund_code", "") or ""),
            "name": str(getattr(holding, "name", "") or ""),
            "price": price,
            "shares": quantity,
            "lot": 100 if asset_type == "stock" else 1,
        }
        dividend_per_unit = _dividend_per_unit_for_target(holding, quantity)
        if dividend_per_unit is not None:
            row["dividend_per_share"] = dividend_per_unit
        rows.append(row)
    return rows


def _dividend_per_unit_for_target(holding: Any, quantity: float) -> float | None:
    annual_income = _optional_float(getattr(holding, "annual_income", None))
    if annual_income is not None and quantity > 0:
        return max(annual_income / quantity, 0.0)
    distribution_per_unit = _optional_float(getattr(holding, "distribution_per_unit", None))
    if distribution_per_unit is not None:
        return max(distribution_per_unit, 0.0)
    return None


def _optional_history_dir(body: JsonDict) -> str | None:
    raw = body.get("history_dir")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


# --- helpers ---------------------------------------------------------------

_SAMPLE_SP500 = str(
    Path(__file__).resolve().parents[3] / "examples" / "sp500_monthly_sample.csv"
)
_MAX_MANUAL_TEXT_CHARS = 200_000


def _request_api_key(body: JsonDict) -> str:
    return str(body.get("api_key") or "").strip()


def _apply_request_api_key(body: JsonDict) -> bool:
    key = _request_api_key(body)
    if not key:
        return False
    os.environ["GEMINI_API_KEY"] = key
    return True


def _looks_like_internal_prompt(text: str) -> bool:
    markers = (
        "あなたはアシスタントです",
        "あなたは投資調査アシスタントです",
        "以下のドラフト群とレビュー指摘",
        "最終回答を作成してください",
        "ユーザーに見せる最終回答だけを書いてください",
        "ローカル文書コンテキスト",
        "出力要件",
        "ドラフト群",
        "レビュー指摘",
        "【生成プロセス】",
    )
    return any(marker in text for marker in markers)


def _clean_user_answer(text: object) -> str:
    raw = str(text or "").strip()
    if not raw or _looks_like_internal_prompt(raw):
        return ""

    remove_markers = (
        "統合最終回答（ローカル擬似・実API未使用）",
        "ドラフト回答（ローカル擬似・実API未使用）",
        "ドラフト回答",
        "統合担当",
        "レビュー担当",
        "厳格なレビュアー",
        "ローカル擬似",
        "実API未使用",
        "担当:",
        "担当：",
    )

    cleaned = raw
    for marker in remove_markers:
        cleaned = cleaned.replace(marker, "")

    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.startswith(("質問:", "質問：")):
            continue
        if stripped.startswith(("専用観点:", "専用観点：")):
            continue
        if stripped.startswith("ドラフト"):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def _direct_final_answer(query: str) -> JsonDict:
    prompt = "\n".join(
        (
            "ユーザーに見せる最終回答だけを書いてください。",
            "内部プロンプト、担当名、ドラフト名、レビュー名は出さないでください。",
            "事実が不明な場合は不明と明記してください。",
            "",
            "出力形式:",
            "1. 弱点指摘（誤り優先）",
            "2. 重大リスク",
            "3. 現実的代替案",
            "4. 【危険ポイント】",
            "5. 次アクション",
            "",
            "質問:",
            query,
        )
    )
    try:
        direct = cli.run_gemini_live(
            task_type="direct_final_answer",
            prompt=prompt,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "text": "",
            "source": "direct_gemini_error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    source = str(direct.get("source") or "")
    text = str(direct.get("text") or "").strip()

    if source.startswith("fallback") or direct.get("skipped"):
        return {
            "text": "",
            "source": source,
            "error": "Gemini returned fallback instead of final answer",
        }

    return {
        "text": text,
        "source": source,
        "warning": direct.get("warning"),
        "skipped": direct.get("skipped"),
        "cache_key": direct.get("cache_key"),
    }



def _local_final_answer(query: str, result: JsonDict) -> str:
    """Build a user-facing final answer when Gemini/orchestration returns no answer."""
    results = result.get("results") or []
    source_count = len(results) if isinstance(results, list) else 0

    evidence_lines: list[str] = []
    if isinstance(results, list):
        for item in results[:3]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "取得資料")
            text = str(item.get("text") or "").strip()
            if text:
                evidence_lines.append(f"- {source}: {text[:180]}")

    evidence = (
        "\n".join(evidence_lines)
        if evidence_lines
        else "取得済み資料から十分な根拠を抽出できませんでした。"
    )

    return "\n".join(
        (
            "1. 弱点指摘（誤り優先）",
            "現時点では、取得済み資料だけでは十分な比較根拠が不足しています。",
            "そのため、結論は暫定です。",
            "",
            "2. 重大リスク",
            f"RAG検索で利用できた根拠候補は {source_count} 件です。",
            "根拠が少ない場合、S&P500と高配当ETFの長期保有上の弱点比較は不完全になります。",
            "",
            "3. 現実的代替案",
            "最小案: 取得済み資料だけで、判断保留点を整理する。",
            "標準案: 有価証券報告書、決算短信、財務諸表、IR資料を追加取得してから再回答する。",
            "強化案: PDF/XBRL本文も抽出し、配当方針・営業CF・自己資本比率・減配履歴を比較する。",
            "",
            "4. 【危険ポイント】",
            "Gemini API失敗、API KEY未反映、RAG未登録、PDF/XBRL未抽出があると回答精度が落ちます。",
            "特に高配当ETFは構成銘柄・分配方針・減配リスクを確認しないと評価が反転し得ます。",
            "",
            "5. 次アクション",
            "Data Intakeで開示資料を一括取得し、RAG登録完了後に同じ質問を再実行してください。",
            "",
            "根拠候補:",
            evidence,
        )
    )


def _finalize_answer(
    result: JsonDict,
    *,
    real_api_requested: bool,
    query: str,
) -> JsonDict:
    raw_answer = result.get("answer", "")
    clean_answer = _clean_user_answer(raw_answer)
    direct_result: JsonDict | None = None

    if real_api_requested and result.get("call_real_api") and not clean_answer:
        direct_result = _direct_final_answer(query)
        clean_answer = _clean_user_answer(direct_result.get("text", ""))

    result["generation_process"] = {
        "raw_answer": raw_answer,
        "drafts": result.get("drafts"),
        "critique": result.get("critique"),
        "orchestration": result.get("orchestration"),
        "call_real_api": result.get("call_real_api"),
        "real_api_requested": real_api_requested,
        "real_api_note": result.get("real_api_note"),
        "direct_gemini": direct_result,
    }

    if not clean_answer:
        local_answer = _local_final_answer(query, result)
        result["answer"] = local_answer
        result["final_answer"] = local_answer
        result["warning"] = (
            "Geminiの最終回答生成に失敗したため、"
            "ローカルRAG結果から暫定回答を作成しました。"
        )
        result.pop("error", None)
        return result

    result["answer"] = clean_answer
    result["final_answer"] = clean_answer
    result.pop("error", None)
    return result


def _real_api_decision(body: JsonDict) -> tuple[bool, str | None]:
    requested = _as_bool(body.get("call_real_api"), False)
    if not requested:
        return False, None

    request_has_key = _apply_request_api_key(body)
    env_allowed = _as_bool(os.getenv(_REAL_API_ENV), False)
    runtime_allowed = bool(_REAL_API_RUNTIME_ENABLED)
    has_key = bool(os.getenv("GEMINI_API_KEY"))

    if has_key and (request_has_key or env_allowed or runtime_allowed):
        return True, None

    if not has_key:
        return False, "GEMINI_API_KEY is not configured on backend"

    return False, "real API is not enabled"


def _ensure_env_from_dotenv(key: str) -> bool:
    if os.getenv(key, "").strip():
        return True
    for env_path in (Path(".env"), Path(".env.local")):
        if not env_path.is_file():
            continue
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                name, value = stripped.split("=", 1)
                if name.strip() != key:
                    continue
                cleaned = value.strip().strip('"').strip("'")
                if cleaned:
                    os.environ[key] = cleaned
                    return True
        except OSError:
            continue
    return False


def _edinet_api_key_source(
    *,
    configured: bool,
    env_configured_before_dotenv: bool,
    dotenv_loaded: bool,
) -> str:
    if not configured:
        return "missing"
    if _EDINET_API_KEY_RUNTIME_SET:
        return "runtime_input"
    if env_configured_before_dotenv:
        return "process_env"
    if dotenv_loaded:
        return "dotenv"
    return "unknown"


def _require_str(body: JsonDict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"missing required string field: {key}")
    return value


def _require_sources(body: JsonDict) -> list[Any]:
    sources = body.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ApiError("provide a non-empty 'sources' list")
    for source in sources:
        if not isinstance(source, dict):
            raise ApiError("each source must be an object")
    return sources


def _default_disclosure_sources() -> list[JsonDict]:
    return [
        {
            "name": "edinet_portal",
            "url": "https://disclosure2.edinet-fsa.go.jp/",
            "output_path": "local_docs/disclosure/edinet_portal.txt",
            "query_hint": "EDINET 有価証券報告書 半期報告書 四半期報告書 財務諸表",
            "extract_text": True,
            "include_metadata": True,
            "preview_chars": 500,
        },
        {
            "name": "tdnet_portal",
            "url": "https://www.release.tdnet.info/inbs/I_main_00.html",
            "output_path": "local_docs/disclosure/tdnet_portal.txt",
            "query_hint": "TDnet 適時開示 決算短信 配当 予想 修正",
            "extract_text": True,
            "include_metadata": True,
            "preview_chars": 500,
        },
        {
            "name": "jpx_listed_issues",
            "url": "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html",
            "output_path": "local_docs/disclosure/jpx_listed_issues.txt",
            "query_hint": "JPX 東証上場銘柄一覧 プライム スタンダード グロース",
            "extract_text": True,
            "include_metadata": True,
            "preview_chars": 500,
        },
    ]


def _run_fetch_job_sources(sources: list[Any], *, dry_run: bool) -> JsonDict:
    yaml_text = _sources_to_yaml(sources)
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".yaml",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(yaml_text)
        temp_path = handle.name
    try:
        return cli.run_fetch_job(path=temp_path, dry_run=dry_run)
    finally:
        Path(temp_path).unlink(missing_ok=True)


def _filter_allowed_sources(
    sources: list[Any],
    dry_run: JsonDict,
) -> tuple[list[Any], list[JsonDict]]:
    dry_results = dry_run.get("results")
    if not isinstance(dry_results, list):
        return [], []

    allowed_names: set[str] = set()
    blocked: list[JsonDict] = []
    for item in dry_results:
        if not isinstance(item, dict):
            continue
        fetch = item.get("fetch")
        if isinstance(fetch, dict) and fetch.get("allowed_by_robots") is True:
            allowed_names.add(str(item.get("name", "")))
        else:
            blocked.append(item)

    allowed_sources = [
        source
        for source in sources
        if isinstance(source, dict) and str(source.get("name", "")) in allowed_names
    ]
    return allowed_sources, blocked


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _market_scope_matches(row: JsonDict, scope: str) -> bool:
    normalized = scope.strip().lower()
    if normalized in {"prime", "tse_prime", "tosho_prime"}:
        return bool(row.get("is_prime"))
    if normalized in {"nikkei225", "nikkei_225", "n225"}:
        return bool(row.get("is_nikkei225"))
    if normalized in {"financials", "edinet", "financials_available"}:
        return bool(row.get("has_financials"))
    return True


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _as_float(value, 0.0)


def _has_any(body: JsonDict, *keys: str) -> bool:
    return any(key in body and body.get(key) not in (None, "") for key in keys)


def _as_int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_as_int(item, 0) for item in value if _as_int(item, 0) > 0)


def _safe_manual_doc_filename(title: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z一-龯ぁ-んァ-ンー_-]+", "-", title).strip("-_")
    safe = normalized[:80] if normalized else "manual-note"
    return f"{safe}.txt"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.stem}-{stamp}{path.suffix}")


def _sources_to_yaml(sources: list[Any]) -> str:
    lines = ["sources:"]
    for source in sources:
        if not isinstance(source, dict):
            raise ApiError("each source must be an object")
        items = list(source.items())
        if not items:
            raise ApiError("source objects must not be empty")
        first_key, first_value = items[0]
        lines.append(f"  - {first_key}: {_yaml_scalar(first_value)}")
        for key, value in items[1:]:
            lines.append(f"    {key}: {_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


_ROUTES: dict[tuple[str, str], Handler] = {
    ("GET", "/api/health"): _health,
    ("GET", "/api/budget"): _budget,
    ("GET", "/api/runtime/real-api"): _runtime_real_api_status,
    ("POST", "/api/runtime/real-api"): _runtime_real_api_set,
    ("POST", "/api/rag/stats"): _rag_stats,
    ("POST", "/api/rag/search"): _rag_search,
    ("POST", "/api/rag/answer-context"): _rag_answer_context,
    ("POST", "/api/rag/answer"): _rag_answer,
    ("GET", "/api/operators/catalog"): _operators_catalog,
    ("POST", "/api/operators/catalog"): _operators_catalog,
    ("POST", "/api/orchestrate"): _orchestrate,
    ("POST", "/api/rag/index-dir"): _rag_index_dir,
    ("POST", "/api/manual-doc/save"): _manual_doc_save,
    ("POST", "/api/scoring/rank"): _scoring_rank,
    ("POST", "/api/scoring/stocks"): _scoring_stocks,
    ("POST", "/api/forecast/evaluate"): _forecast_evaluate,
    ("POST", "/api/forecast/predict"): _forecast_predict,
    ("POST", "/api/portfolio/dividends"): _portfolio_dividends,
    ("POST", "/api/portfolio/simulate"): _portfolio_simulate,
    ("POST", "/api/portfolio/target"): _portfolio_target,
    ("POST", "/api/portfolio/universe"): _portfolio_universe,
    ("POST", "/api/market/universe"): _market_universe,
    ("POST", "/api/market/jpx-listed/template"): _jpx_listed_template,
    ("POST", "/api/market/jpx-listed/import"): _jpx_listed_import,
    ("POST", "/api/market/jpx-listed/download"): _jpx_listed_download,
    ("POST", "/api/market/prices"): _market_prices,
    ("POST", "/api/providers/policy"): _provider_policy_ledger,
    ("POST", "/api/portfolio/performance"): _portfolio_performance,
    ("POST", "/api/holdings/import"): _holdings_import,
    ("POST", "/api/holdings/validate"): _holdings_validate,
    ("POST", "/api/holdings/template"): _holdings_template,
    ("POST", "/api/funds/validate"): _funds_validate,
    ("POST", "/api/funds/template"): _funds_template,
    ("POST", "/api/portfolio/analyze"): _portfolio_analyze,
    ("POST", "/api/investment/detail"): _investment_detail,
    ("POST", "/api/candidates/screen"): _candidates_screen,
    ("POST", "/api/reports/investment-monthly"): _investment_monthly_report,
    ("POST", "/api/reports/investment-monthly/audit"): _investment_report_audit,
    ("POST", "/api/reports/investment-monthly/markdown"): _investment_report_markdown,
    ("GET", "/api/reports/investment-monthly/history"): _investment_report_history,
    ("POST", "/api/reports/investment-monthly/history"): _investment_report_history,
    ("POST", "/api/reports/investment-monthly/history/load"): _investment_report_history_load,
    ("POST", "/api/reports/investment-monthly/history/delete"): _investment_report_history_delete,
    ("POST", "/api/reports/investment-monthly/history/verify"): _investment_report_history_verify,
    ("POST", "/api/reports/investment-monthly/history/compare"): _investment_report_history_compare,
    ("POST", "/api/financials/compare"): _financials_compare,
    ("GET", "/api/financials/status"): _financials_status,
    ("POST", "/api/financials/status"): _financials_status,
    ("POST", "/api/financials/import"): _financials_import,
    ("POST", "/api/financials/refresh"): _financials_refresh,
    ("POST", "/api/financials/refresh-async"): _financials_refresh_async,
    ("POST", "/api/financials/securities"): _financials_securities,
    ("POST", "/api/cache/maintenance"): _cache_maintenance,
    ("POST", "/api/fetch-job/dry-run"): lambda body: _fetch_job(body, dry_run=True),
    ("POST", "/api/fetch-job/run"): lambda body: _fetch_job(body, dry_run=False),
    ("POST", "/api/fetch-job/auto"): _fetch_job_auto,
    ("POST", "/api/edinet/ingest"): _edinet_ingest,
    ("POST", "/api/edinet/ingest-async"): _edinet_ingest_async,
    ("GET", "/api/edinet/status"): _edinet_status,
    ("POST", "/api/edinet/api-key"): _edinet_api_key_set,
    ("POST", "/api/jobs/status"): _job_status,
    ("POST", "/api/storage/prune"): _storage_prune,
    ("POST", "/api/knowledge/diff"): _knowledge_diff,
    ("POST", "/api/feedback"): _feedback,
    ("POST", "/api/feedback/stats"): _feedback_stats,
}


def available_routes() -> list[str]:
    return sorted(f"{method} {path}" for method, path in _ROUTES)
