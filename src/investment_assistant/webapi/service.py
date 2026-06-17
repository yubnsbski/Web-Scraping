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
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH
from investment_assistant.webapi import data_status as data_status_api
from investment_assistant.webapi import edinet as edinet_api
from investment_assistant.webapi import investments as investment_api
from investment_assistant.webapi import market as market_api
from investment_assistant.webapi import portfolio as portfolio_api
from investment_assistant.webapi import reports as report_api
from investment_assistant.webapi.errors import ApiError
from investment_assistant.webapi.jobs import JOBS

JsonDict = dict[str, Any]
Handler = Callable[[JsonDict], JsonDict]
_REAL_API_ENV = "INVESTMENT_ASSISTANT_WEB_REAL_API"
_REAL_API_RUNTIME_ENABLED = False


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
    query = _require_str(body, "query")
    results = cli.run_rag_search(
        query=query,
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 5),
        hybrid=bool(body.get("hybrid", False)),
        alpha=_as_float(body.get("alpha"), 0.5),
    )
    return {"query": query, "results": results}


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



def _edinet_ingest(body: JsonDict) -> JsonDict:
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


def _financials_compare(body: JsonDict) -> JsonDict:
    path = str(body.get("path") or "examples/financials_sample.csv")
    return compare_financials(load_financials(path))


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
    ("POST", "/api/orchestrate"): _orchestrate,
    ("POST", "/api/rag/index-dir"): _rag_index_dir,
    ("POST", "/api/manual-doc/save"): _manual_doc_save,
    ("POST", "/api/scoring/rank"): _scoring_rank,
    ("POST", "/api/scoring/stocks"): _scoring_stocks,
    ("POST", "/api/forecast/evaluate"): _forecast_evaluate,
    ("POST", "/api/forecast/predict"): _forecast_predict,
    ("POST", "/api/portfolio/dividends"): portfolio_api.portfolio_dividends,
    ("POST", "/api/portfolio/simulate"): portfolio_api.portfolio_simulate,
    ("POST", "/api/portfolio/target"): portfolio_api.portfolio_target,
    ("POST", "/api/portfolio/universe"): portfolio_api.portfolio_universe,
    ("POST", "/api/market/prices"): market_api.market_prices,
    ("POST", "/api/market/ohlcv"): market_api.market_ohlcv,
    ("POST", "/api/market/bars"): market_api.market_bars,
    ("POST", "/api/market/bars/universe"): market_api.market_bars_universe,
    ("POST", "/api/market/financials"): market_api.market_financials,
    ("POST", "/api/market/intraday"): market_api.market_intraday,
    ("POST", "/api/market/inbox"): market_api.market_inbox,
    ("POST", "/api/data/status"): data_status_api.data_status,
    ("POST", "/api/financials/preview"): data_status_api.financials_preview,
    ("POST", "/api/providers/policy"): _provider_policy_ledger,
    ("POST", "/api/portfolio/performance"): portfolio_api.portfolio_performance,
    ("POST", "/api/holdings/import"): investment_api.holdings_import,
    ("POST", "/api/holdings/validate"): investment_api.holdings_validate,
    ("POST", "/api/holdings/template"): investment_api.holdings_template,
    ("POST", "/api/funds/validate"): investment_api.funds_validate,
    ("POST", "/api/funds/template"): investment_api.funds_template,
    ("POST", "/api/portfolio/analyze"): investment_api.portfolio_analyze,
    ("POST", "/api/investment/detail"): investment_api.investment_detail,
    ("POST", "/api/candidates/screen"): investment_api.candidates_screen,
    ("POST", "/api/reports/investment-monthly"): report_api.investment_monthly_report,
    ("POST", "/api/reports/investment-monthly/audit"): report_api.investment_report_audit,
    ("POST", "/api/reports/investment-monthly/markdown"): report_api.investment_report_markdown,
    (
        "POST",
        "/api/reports/investment-monthly/markdown/save",
    ): report_api.investment_report_markdown_save,
    ("GET", "/api/reports/investment-monthly/history"): report_api.investment_report_history,
    ("POST", "/api/reports/investment-monthly/history"): report_api.investment_report_history,
    (
        "POST",
        "/api/reports/investment-monthly/history/load",
    ): report_api.investment_report_history_load,
    (
        "POST",
        "/api/reports/investment-monthly/history/delete",
    ): report_api.investment_report_history_delete,
    (
        "POST",
        "/api/reports/investment-monthly/history/verify",
    ): report_api.investment_report_history_verify,
    (
        "POST",
        "/api/reports/investment-monthly/history/compare",
    ): report_api.investment_report_history_compare,
    ("POST", "/api/financials/compare"): _financials_compare,
    ("POST", "/api/cache/maintenance"): _cache_maintenance,
    ("POST", "/api/fetch-job/dry-run"): lambda body: _fetch_job(body, dry_run=True),
    ("POST", "/api/fetch-job/run"): lambda body: _fetch_job(body, dry_run=False),
    ("POST", "/api/fetch-job/auto"): _fetch_job_auto,
    ("POST", "/api/edinet/status"): edinet_api.edinet_status,
    ("POST", "/api/edinet/api-key"): edinet_api.edinet_save_api_key,
    ("POST", "/api/edinet/ingest"): _edinet_ingest,
    ("POST", "/api/edinet/ingest-async"): _edinet_ingest_async,
    ("POST", "/api/jobs/status"): _job_status,
    ("POST", "/api/storage/prune"): _storage_prune,
    ("POST", "/api/knowledge/diff"): _knowledge_diff,
    ("POST", "/api/feedback"): _feedback,
    ("POST", "/api/feedback/stats"): _feedback_stats,
}


def available_routes() -> list[str]:
    return sorted(f"{method} {path}" for method, path in _ROUTES)
