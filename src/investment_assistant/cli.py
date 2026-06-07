"""Command-line utilities for operating the investment assistant foundation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from investment_assistant.config.loader import load_yaml
from investment_assistant.forecasting import service as forecast_service
from investment_assistant.forecasting.dataset import DEFAULT_DATASET, download_dataset
from investment_assistant.forecasting.timeseries import load_timeseries_csv
from investment_assistant.ingestion.fetcher import (
    DEFAULT_HTTP_CACHE_PATH,
    SafeFetcher,
    reject_path_traversal,
)
from investment_assistant.ingestion.http_cache import HttpCache
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.factory import (
    DEFAULT_GEMINI_CONFIG_PATH,
    build_llm_service,
    load_gemini_runtime_config,
)
from investment_assistant.llm.gemini_client import TextGenerationClient
from investment_assistant.observability import configure_logging
from investment_assistant.orchestration.factory import build_orchestrator
from investment_assistant.orchestration.orchestrator import OrchestrationConfig
from investment_assistant.rag.answer import LocalRagAnswerClient, generate_rag_answer
from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.indexer import index_directory
from investment_assistant.rag.search import (
    SearchResult,
    build_answer_context,
    hybrid_search,
    search_chunks,
)
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH, RagStore
from investment_assistant.rag.tokenize import tokenize
from investment_assistant.scoring.models import ScoreWeights
from investment_assistant.scoring.report import build_scoring_report
from investment_assistant.scoring.scorer import validate_scoring_csv


@dataclass(frozen=True)
class BudgetReport:
    """CLI-friendly budget report."""

    model: str
    daily_limit: int
    monthly_limit: int
    hard_daily_limit: int
    hard_monthly_limit: int
    daily_used: int
    monthly_used: int
    daily_remaining: int
    monthly_remaining: int
    warning: bool


class EchoClient:
    """Local fake client used by the smoke command without calling Gemini."""

    def generate(self, prompt: str, *, model: str) -> str:
        return f"[smoke:{model}] {prompt}"


def build_budget_report(config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH) -> BudgetReport:
    """Build a current UTC daily/monthly budget report without calling Gemini."""

    runtime = load_gemini_runtime_config(config_path)
    service = build_llm_service(config_path, client=EchoClient())
    now = datetime.now(UTC)
    daily_used = service.budget_guard.count_daily(now)
    monthly_used = service.budget_guard.count_monthly(now)
    hard_daily = int(runtime.budget.daily_request_limit * runtime.budget.hard_stop_threshold_ratio)
    hard_monthly = int(
        runtime.budget.monthly_request_limit * runtime.budget.hard_stop_threshold_ratio
    )
    warning = (
        daily_used >= runtime.budget.daily_request_limit * runtime.budget.warning_threshold_ratio
        or monthly_used
        >= runtime.budget.monthly_request_limit * runtime.budget.warning_threshold_ratio
    )
    return BudgetReport(
        model=runtime.model,
        daily_limit=runtime.budget.daily_request_limit,
        monthly_limit=runtime.budget.monthly_request_limit,
        hard_daily_limit=hard_daily,
        hard_monthly_limit=hard_monthly,
        daily_used=daily_used,
        monthly_used=monthly_used,
        daily_remaining=max(0, hard_daily - daily_used),
        monthly_remaining=max(0, hard_monthly - monthly_used),
        warning=warning,
    )


def run_smoke(
    *,
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    task_type: str = "rag_answer",
    prompt: str = "Gemini budget guard smoke test",
    client: TextGenerationClient | None = None,
) -> dict[str, object]:
    """Run a no-network smoke generation through the guarded service path."""

    service = build_llm_service(config_path, client=client or EchoClient())
    response = service.generate(task_type=task_type, prompt=prompt)
    return {
        "text": response.text,
        "source": response.source,
        "warning": response.warning,
        "skipped": response.skipped,
        "cache_key": response.cache_key,
    }


def run_gemini_live(
    *,
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    task_type: str = "rag_answer",
    prompt: str,
) -> dict[str, object]:
    """Manually call the real Gemini API through the guarded service path."""

    service = build_llm_service(config_path)
    response = service.generate(task_type=task_type, prompt=prompt)
    return {
        "text": response.text,
        "source": response.source,
        "warning": response.warning,
        "skipped": response.skipped,
        "cache_key": response.cache_key,
    }


def run_fetch_url(
    *,
    url: str,
    dry_run: bool = False,
    preview_chars: int = 500,
    save_text: str | Path | None = None,
    extract_text: bool = False,
    include_metadata: bool = False,
) -> dict[str, object]:
    """Run a safe URL fetch with robots, rate limiting, cache, and optional text saving."""

    fetcher = SafeFetcher()
    result = fetcher.fetch(
        url,
        dry_run=dry_run,
        preview_chars=preview_chars,
        save_text=save_text,
        extract_text=extract_text,
        include_metadata=include_metadata,
    )
    return asdict(result)


def run_fetch_job(
    *,
    path: str | Path,
    dry_run: bool = False,
    preview_chars: int = 500,
) -> dict[str, object]:
    """Run a YAML-defined batch of safe fetches without LLMs or trading actions."""

    job_path = Path(path)
    config = load_yaml(job_path)
    sources = _fetch_job_sources(config, job_path)
    fetcher = SafeFetcher()
    results: list[dict[str, object]] = []
    for source in sources:
        source_preview_chars = _int_or_default(source.get("preview_chars"), preview_chars)
        extract_text = _bool_or_default(source.get("extract_text"), True)
        include_metadata = _bool_or_default(source.get("include_metadata"), True)
        output_path = str(reject_path_traversal(str(source["output_path"])))
        fetch_result = fetcher.fetch(
            str(source["url"]),
            dry_run=dry_run,
            preview_chars=source_preview_chars,
            save_text=None if dry_run else output_path,
            extract_text=extract_text,
            include_metadata=include_metadata,
        )
        results.append(
            {
                "name": str(source["name"]),
                "url": str(source["url"]),
                "output_path": output_path,
                "query_hint": None
                if source.get("query_hint") is None
                else str(source.get("query_hint")),
                "fetch": asdict(fetch_result),
            }
        )
    return {
        "job_path": str(job_path),
        "dry_run": dry_run,
        "sources_count": len(results),
        "results": results,
    }


def run_rag_index(
    *,
    path: str | Path,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> dict[str, object]:
    """Index a local text/Markdown file into the local RAG store."""

    document = load_document(path)
    chunks = chunk_text(
        source=document.source,
        text=document.text,
        content_hash=document.content_hash,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    store = RagStore(db_path)
    chunk_count = store.upsert_document(document, chunks)
    return {
        "source": document.source,
        "content_hash": document.content_hash,
        "chunks_indexed": chunk_count,
        "db_path": str(db_path),
    }


def run_rag_index_dir(
    *,
    path: str | Path,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> dict[str, object]:
    """Recursively index local text/Markdown files into the local RAG store."""

    return index_directory(
        path=path,
        db_path=db_path,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )



def _search_chunks_for_source(
    store: RagStore,
    *,
    query: str,
    source_filter: str,
    limit: int,
) -> list[SearchResult]:
    """Search chunks only from one exact RAG source path."""

    terms = tokenize(query)
    if not terms or limit <= 0:
        return []

    results: list[SearchResult] = []
    for chunk in store.list_chunks():
        if chunk.source != source_filter:
            continue

        score = _score_source_filtered_text(chunk.text, terms)
        if score <= 0:
            continue

        results.append(
            SearchResult(
                chunk_id=chunk.chunk_id,
                source=chunk.source,
                chunk_index=chunk.chunk_index,
                score=float(score),
                text=chunk.text,
                metadata=chunk.metadata,
            )
        )

    ranked = sorted(results, key=lambda item: (-item.score, item.source, item.chunk_index))
    return _dedupe_source_filtered_results(ranked)[:limit]


def _score_source_filtered_text(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(term.lower()) for term in terms)


def _dedupe_source_filtered_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []

    for result in results:
        key = " ".join(result.text.split())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)

    return deduped

def run_rag_search(
    *,
    query: str,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
    hybrid: bool = False,
    alpha: float = 0.5,
) -> list[dict[str, object]]:
    """Search the local RAG store without calling an LLM."""

    store = RagStore(db_path)
    if hybrid:
        results = hybrid_search(store, query=query, limit=limit, alpha=alpha)
    else:
        results = search_chunks(store, query=query, limit=limit)
    return [asdict(result) for result in results]



def _run_rag_search_for_source(
    *,
    query: str,
    source: str,
    db_path: str | Path,
    limit: int,
) -> list[dict[str, object]]:
    """Search only chunks whose RAG source exactly matches source."""

    terms = tokenize(query)
    if not terms or limit <= 0:
        return []

    store = RagStore(db_path)
    results: list[dict[str, object]] = []

    for chunk in store.list_chunks():
        if chunk.source != source:
            continue

        score = _score_scoped_text(chunk.text, terms)
        if score <= 0:
            continue

        results.append(
            {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "chunk_index": chunk.chunk_index,
                "score": float(score),
                "text": chunk.text,
                "metadata": chunk.metadata,
            }
        )

    ranked = sorted(results, key=_search_result_sort_key)
    return _dedupe_search_dicts_by_text(ranked)[:limit]


def _score_scoped_text(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(term.lower()) for term in terms)


def _search_result_sort_key(result: dict[str, object]) -> tuple[float, str, int]:
    score = result.get("score")
    source = result.get("source")
    chunk_index = result.get("chunk_index")

    score_value = float(score) if isinstance(score, (int, float)) else 0.0
    source_value = source if isinstance(source, str) else ""
    chunk_index_value = chunk_index if isinstance(chunk_index, int) else 0

    return (-score_value, source_value, chunk_index_value)


def _dedupe_search_dicts_by_text(
    results: list[dict[str, object]],
) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []

    for result in results:
        key = " ".join(str(result.get("text", "")).split())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)

    return deduped

def run_rag_search_job(
    *,
    path: str | Path,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
    scope: str = "all",
) -> dict[str, object]:
    """Search the local RAG store for each query_hint in a fetch-job file."""

    job_path = Path(path)
    config = load_yaml(job_path)
    sources = _fetch_job_sources(config, job_path)
    if scope not in {"all", "job-source"}:
        msg = "scope must be one of: all, job-source"
        raise ValueError(msg)
    results: list[dict[str, object]] = []
    for source in sources:
        query = _query_from_fetch_job_source(source)
        if scope == "job-source":
            search_results = _run_rag_search_for_source(
                query=query,
                source=str(source["output_path"]),
                db_path=db_path,
                limit=limit,
            )
        else:
            search_results = run_rag_search(
                query=query,
                db_path=db_path,
                limit=limit,
            )

        results.append(
            {
                "name": str(source["name"]),
                "url": str(source["url"]),
                "output_path": str(source["output_path"]),
                "query": query,
                "query_hint": None
                if source.get("query_hint") is None
                else str(source.get("query_hint")),
                "results": search_results,
            }
        )
    return {
        "job_path": str(job_path),
        "db_path": str(db_path),
        "sources_count": len(results),
        "results": results,
    }


def run_rag_answer_context(
    *,
    query: str,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
) -> dict[str, object]:
    """Return citation-friendly local context for a query without calling an LLM."""

    store = RagStore(db_path)
    results = search_chunks(store, query=query, limit=limit)
    return {
        "query": query,
        "context": build_answer_context(results),
        "results": [asdict(result) for result in results],
    }


def run_rag_answer(
    *,
    query: str,
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
    call_real_api: bool = False,
    client: TextGenerationClient | None = None,
) -> dict[str, object]:
    """Generate a citation-aware answer through the guarded LLM service path."""

    chosen_client = (
        client if client is not None else (None if call_real_api else LocalRagAnswerClient())
    )
    service = build_llm_service(config_path, client=chosen_client)
    result = generate_rag_answer(
        store=RagStore(db_path),
        service=service,
        query=query,
        limit=limit,
    )
    result["call_real_api"] = call_real_api
    return result


def run_orchestrate_answer(
    *,
    query: str,
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
    drafts: int = 1,
    include_critique: bool = True,
    hybrid: bool = False,
    alpha: float = 0.5,
    call_real_api: bool = False,
    source_filter: str | None = None,
) -> dict[str, object]:
    """Run multi-model orchestration over RAG context."""

    store = RagStore(db_path)
    if source_filter:
        results = _search_chunks_for_source(
            store,
            query=query,
            source_filter=source_filter,
            limit=limit,
        )
    elif hybrid:
        results = hybrid_search(store, query=query, limit=limit, alpha=alpha)
    else:
        results = search_chunks(store, query=query, limit=limit)
    context = build_answer_context(results)
    if not results:
        return {
            "query": query,
            "answer": (
                "関連するローカル文書チャンクがないため、"
                "オーケストレーションをスキップしました。"
            ),
            "context": context,
            "results": [],
            "source_filter": source_filter,
            "skipped": True,
        }

    perspectives = [
        "配当・キャッシュフロー・財務安全性だけを評価する。株価トレンドや短期需給には触れない。",
        "株価下落リスク・景気感応度・競争環境だけを評価する。配当利回りやNISA制度には触れない。",
        "NISA長期保有・分散・手数料だけを評価する。短期売買判断やチャート分析には触れない。",
        "データ不足・未検証事項・判断保留すべき危険ポイントだけを評価する。結論を急がない。",
        "反対意見・弱気シナリオだけを評価する。楽観材料は補足に留める。",
    ]
    selected_perspectives = perspectives[:1]

    perspective_block = "\\n".join(
        f"ドラフト{i + 1}の専用観点: {perspective}"
        for i, perspective in enumerate(selected_perspectives)
    )
    query_with_perspectives = (
        query
        + "\\n\\n以下の観点をドラフトごとに厳守してください。"
        + "\\n"
        + perspective_block
        + "\\n各ドラフトは他ドラフトと同じ論点を主軸にしないでください。"
    )

    orchestrator = build_orchestrator(
        config_path,
        config=OrchestrationConfig(
            n_drafts=1,
            include_critique=include_critique,
        ),
        call_real_api=call_real_api,
    )
    outcome = orchestrator.run(query=query_with_perspectives, context=context)
    payload = outcome.to_dict()
    payload["context"] = context
    payload["results"] = [asdict(result) for result in results]
    payload["source_filter"] = source_filter
    payload["call_real_api"] = call_real_api
    payload["perspectives"] = selected_perspectives
    return payload


def run_cache_maintenance(
    *,
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    max_rows: int | None = None,
) -> dict[str, object]:
    """Purge expired entries and enforce row limits on the HTTP and LLM caches."""

    runtime = load_gemini_runtime_config(config_path)
    llm_cache = LlmCache(
        runtime.cache_db_path,
        ttl_days=runtime.cache_ttl_days,
        enabled=True,
        max_rows=max_rows,
    )
    http_cache = HttpCache(DEFAULT_HTTP_CACHE_PATH, max_rows=max_rows)
    llm_expired = llm_cache.purge_expired()
    llm_trimmed = llm_cache.enforce_max_rows() if max_rows is not None else 0
    http_expired = http_cache.purge_expired()
    http_trimmed = http_cache.enforce_max_rows() if max_rows is not None else 0
    return {
        "max_rows": max_rows,
        "llm_cache": {
            "db_path": str(runtime.cache_db_path),
            "expired_removed": llm_expired,
            "trimmed_removed": llm_trimmed,
        },
        "http_cache": {
            "db_path": str(DEFAULT_HTTP_CACHE_PATH),
            "expired_removed": http_expired,
            "trimmed_removed": http_trimmed,
        },
    }


def run_forecast_fetch_data(
    *,
    dataset: str = DEFAULT_DATASET,
    dest: str | Path,
) -> dict[str, object]:
    """Download a real financial dataset for forecasting."""

    return download_dataset(dataset, dest=dest)


def run_forecast_evaluate(
    *,
    path: str | Path,
    value_column: str = "SP500",
    date_column: str = "Date",
    horizon: int = 1,
    step: int = 1,
    tail: int | None = None,
    include_ml: bool = True,
    ensemble_method: str = "weighted",
    space: str = "returns",
    ma_windows: Sequence[int] = (),
) -> dict[str, object]:
    """Walk-forward backtest base models and the ensemble on a local CSV."""

    series = load_timeseries_csv(path, date_column=date_column, value_column=value_column)
    if tail is not None:
        series = series.tail(tail)
    return forecast_service.run_evaluation(
        series,
        horizon=horizon,
        step=step,
        include_ml=include_ml,
        ensemble_method=ensemble_method,
        space=space,
        ma_windows=ma_windows,
    )


def run_forecast_predict(
    *,
    path: str | Path,
    value_column: str = "SP500",
    date_column: str = "Date",
    horizon: int = 1,
    include_ml: bool = True,
    ensemble_method: str = "weighted",
    space: str = "returns",
) -> dict[str, object]:
    """Forecast the next horizon steps with the ensemble."""

    series = load_timeseries_csv(path, date_column=date_column, value_column=value_column)
    return forecast_service.run_forecast(
        series,
        horizon=horizon,
        include_ml=include_ml,
        ensemble_method=ensemble_method,
        space=space,
    )


def run_scoring_rank(
    *,
    path: str | Path,
    limit: int = 10,
    expense_weight: float = 0.35,
    return_weight: float = 0.25,
    volatility_weight: float = 0.25,
    diversification_weight: float = 0.15,
) -> dict[str, object]:
    """Rank local CSV investment candidates without LLMs or trading actions."""

    weights = ScoreWeights(
        expense_ratio=expense_weight,
        annual_return=return_weight,
        volatility=volatility_weight,
        diversification_score=diversification_weight,
    )
    return build_scoring_report(path=path, limit=limit, weights=weights)


def run_scoring_validate(path: str | Path) -> dict[str, object]:
    """Validate a local scoring CSV without LLMs, scoring, or trading actions."""

    return validate_scoring_csv(path)


def _fetch_job_sources(config: dict[str, Any], job_path: Path) -> list[dict[str, object]]:
    raw_sources = config.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        msg = f"fetch job must define a non-empty sources list: {job_path}"
        raise ValueError(msg)

    sources: list[dict[str, object]] = []
    for index, source in enumerate(raw_sources, start=1):
        if not isinstance(source, dict):
            msg = f"source #{index} must be a mapping"
            raise ValueError(msg)
        missing = [key for key in ("name", "url", "output_path") if key not in source]
        if missing:
            msg = f"source #{index} missing required keys: {', '.join(missing)}"
            raise ValueError(msg)
        sources.append(dict(source))
    return sources


def _query_from_fetch_job_source(source: dict[str, object]) -> str:
    query_hint = source.get("query_hint")
    if isinstance(query_hint, str) and query_hint.strip():
        return query_hint.strip()
    return str(source.get("name", "")).strip()


def _bool_or_default(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return default


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))



def _save_report(content: str, path: str | Path) -> str:
    output_path = Path(path)
    if any(part == ".." for part in output_path.parts):
        raise ValueError(f"path traversal is not allowed: {path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return str(output_path)


def _table_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _metadata_value(metadata: object, key: str) -> str:
    if not isinstance(metadata, dict):
        return ""
    raw_value = metadata.get(key)
    return "" if raw_value is None else str(raw_value)


def _metadata_summary(metadata: object) -> str:
    if not isinstance(metadata, dict):
        return ""
    keys = ("source_url", "fetched_at", "status_code", "content_type")
    return " ".join(f"{key}={metadata[key]}" for key in keys if metadata.get(key))


def format_rag_search_table(
    results: list[dict[str, object]],
    *,
    text_preview_chars: int = 120,
    columns: list[str] | None = None,
) -> str:
    selected_columns = columns or ["rank", "score", "source", "chunk", "metadata", "text_preview"]

    rows = [
        "| " + " | ".join(selected_columns) + " |",
        "| " + " | ".join("---" for _ in selected_columns) + " |",
    ]

    for rank, result in enumerate(results, start=1):
        metadata = result.get("metadata")
        values: list[str] = []

        for column in selected_columns:
            if column == "rank":
                value = str(rank)
            elif column == "score":
                value = str(result.get("score", ""))
            elif column == "source":
                value = str(result.get("source", ""))
            elif column == "chunk":
                value = str(result.get("chunk_index", ""))
            elif column == "metadata":
                value = _metadata_summary(metadata)
            elif column == "text_preview":
                normalized = " ".join(str(result.get("text", "")).split())
                value = normalized[:text_preview_chars]
            elif column in {"source_url", "fetched_at", "status_code", "content_type"}:
                value = _metadata_value(metadata, column)
            else:
                value = str(result.get(column, ""))

            values.append(_table_cell(value))

        rows.append("| " + " | ".join(values) + " |")

    return "\n".join(rows)


def format_rag_search_job_table(
    search_job_result: dict[str, object],
    *,
    text_preview_chars: int = 120,
    columns: list[str] | None = None,
) -> str:
    raw_results = search_job_result.get("results")
    if not isinstance(raw_results, list) or not raw_results:
        return "No fetch-job RAG search results."

    blocks: list[str] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", ""))
        query = str(item.get("query", ""))
        url = str(item.get("url", ""))
        blocks.append(f"## {name} | query={query} | url={url}")

        item_results = item.get("results")
        rows = item_results if isinstance(item_results, list) else []
        table_rows = [row for row in rows if isinstance(row, dict)]
        blocks.append(
            format_rag_search_table(
                table_rows,
                text_preview_chars=text_preview_chars,
                columns=columns,
            )
        )

    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""

    configure_logging()
    parser = argparse.ArgumentParser(prog="investment-assistant")
    parser.add_argument("--config", default=str(DEFAULT_GEMINI_CONFIG_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    budget_parser = subparsers.add_parser("budget")
    budget_parser.add_argument("--json", action="store_true")

    smoke_parser = subparsers.add_parser("smoke")
    smoke_parser.add_argument("--prompt", default="hello")

    gemini_live_parser = subparsers.add_parser("gemini-live")
    gemini_live_parser.add_argument("--prompt", required=True)
    gemini_live_parser.add_argument("--task-type", default="rag_answer")
    gemini_live_parser.add_argument("--call-real-api", action="store_true")

    fetch_url_parser = subparsers.add_parser("fetch-url")
    fetch_url_parser.add_argument("--url", required=True)
    fetch_url_parser.add_argument("--dry-run", action="store_true")
    fetch_url_parser.add_argument("--preview-chars", type=int, default=500)
    fetch_url_parser.add_argument("--save-text")
    fetch_url_parser.add_argument("--extract-text", action="store_true")
    fetch_url_parser.add_argument("--include-metadata", action="store_true")

    fetch_job_parser = subparsers.add_parser("fetch-job")
    fetch_job_parser.add_argument("--path", required=True)
    fetch_job_parser.add_argument("--dry-run", action="store_true")
    fetch_job_parser.add_argument("--preview-chars", type=int, default=500)

    rag_index_parser = subparsers.add_parser("rag-index")
    rag_index_parser.add_argument("--path", required=True)
    rag_index_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_index_parser.add_argument("--max-chars", type=int, default=800)
    rag_index_parser.add_argument("--overlap-chars", type=int, default=120)

    rag_index_dir_parser = subparsers.add_parser("rag-index-dir")
    rag_index_dir_parser.add_argument("--path", required=True)
    rag_index_dir_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_index_dir_parser.add_argument("--max-chars", type=int, default=800)
    rag_index_dir_parser.add_argument("--overlap-chars", type=int, default=120)

    rag_search_parser = subparsers.add_parser("rag-search")
    rag_search_parser.add_argument("--query", required=True)
    rag_search_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_search_parser.add_argument("--limit", type=int, default=5)
    rag_search_parser.add_argument("--hybrid", action="store_true")
    rag_search_parser.add_argument("--alpha", type=float, default=0.5)
    rag_search_parser.add_argument("--format", choices=("json", "table"), default="json")
    rag_search_parser.add_argument("--columns")
    rag_search_parser.add_argument("--text-preview-chars", type=int, default=120)


    rag_search_job_parser = subparsers.add_parser("rag-search-job")
    rag_search_job_parser.add_argument("--path", required=True)
    rag_search_job_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_search_job_parser.add_argument("--limit", type=int, default=5)
    rag_search_job_parser.add_argument("--format", choices=("json", "table"), default="json")
    rag_search_job_parser.add_argument("--text-preview-chars", type=int, default=120)
    rag_search_job_parser.add_argument("--columns")
    rag_search_job_parser.add_argument("--save-report")
    rag_search_job_parser.add_argument(
        "--scope",
        choices=("all", "job-source"),
        default="all",
    )

    rag_answer_context_parser = subparsers.add_parser("rag-answer-context")
    rag_answer_context_parser.add_argument("--query", required=True)
    rag_answer_context_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_answer_context_parser.add_argument("--limit", type=int, default=5)

    rag_answer_parser = subparsers.add_parser("rag-answer")
    rag_answer_parser.add_argument("--query", required=True)
    rag_answer_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_answer_parser.add_argument("--limit", type=int, default=5)
    rag_answer_parser.add_argument("--call-real-api", action="store_true")

    orchestrate_parser = subparsers.add_parser("orchestrate-answer")
    orchestrate_parser.add_argument("--query", required=True)
    orchestrate_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    orchestrate_parser.add_argument("--limit", type=int, default=5)
    orchestrate_parser.add_argument("--drafts", type=int, default=1)
    orchestrate_parser.add_argument("--no-critique", action="store_true")
    orchestrate_parser.add_argument("--hybrid", action="store_true")
    orchestrate_parser.add_argument("--alpha", type=float, default=0.5)
    orchestrate_parser.add_argument("--call-real-api", action="store_true")

    scoring_parser = subparsers.add_parser("scoring-rank")
    scoring_parser.add_argument("--path", required=True)
    scoring_parser.add_argument("--limit", type=int, default=10)
    scoring_parser.add_argument("--output")
    scoring_parser.add_argument("--overwrite", action="store_true")
    scoring_parser.add_argument("--format", choices=("json", "table"), default="json")


    scoring_validate_parser = subparsers.add_parser("scoring-validate")
    scoring_validate_parser.add_argument("--path", required=True)

    forecast_eval_parser = subparsers.add_parser("forecast-evaluate")
    forecast_eval_parser.add_argument("--path", required=True)
    forecast_eval_parser.add_argument("--value-column", default="SP500")
    forecast_eval_parser.add_argument("--horizon", type=int, default=1)
    forecast_eval_parser.add_argument("--space", choices=("level", "returns"), default="returns")

    forecast_predict_parser = subparsers.add_parser("forecast-predict")
    forecast_predict_parser.add_argument("--path", required=True)
    forecast_predict_parser.add_argument("--value-column", default="SP500")
    forecast_predict_parser.add_argument("--horizon", type=int, default=1)
    forecast_predict_parser.add_argument("--space", choices=("level", "returns"), default="returns")

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    payload = _dispatch(args)
    if isinstance(payload, int):
        return payload
    if payload is not None:
        _print_json(payload)
    return 0


def _dispatch(args: argparse.Namespace) -> object | None:
    command = str(args.command)
    if command == "budget":
        return asdict(build_budget_report(args.config))
    if command == "smoke":
        return run_smoke(config_path=args.config, prompt=args.prompt)
    if command == "gemini-live":
        if not args.call_real_api:
            print("Refusing to call Gemini API without --call-real-api.")
            return 2
        return run_gemini_live(
            config_path=args.config,
            task_type=args.task_type,
            prompt=args.prompt,
        )
    if command == "fetch-url":
        return run_fetch_url(
            url=args.url,
            dry_run=args.dry_run,
            preview_chars=args.preview_chars,
            save_text=args.save_text,
            extract_text=args.extract_text,
            include_metadata=args.include_metadata,
        )
    if command == "fetch-job":
        return run_fetch_job(
            path=args.path,
            dry_run=args.dry_run,
            preview_chars=args.preview_chars,
        )
    if command == "rag-index":
        return run_rag_index(
            path=args.path,
            db_path=args.db_path,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
        )
    if command == "rag-index-dir":
        return run_rag_index_dir(
            path=args.path,
            db_path=args.db_path,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
        )
    if command == "rag-search":
        results = run_rag_search(
            query=args.query,
            db_path=args.db_path,
            limit=args.limit,
            hybrid=args.hybrid,
            alpha=args.alpha,
        )
        if args.format == "table":
            print(
                format_rag_search_table(
                    results,
                    text_preview_chars=args.text_preview_chars,
                    columns=None if args.columns is None else args.columns.split(","),
                )
            )
            return None
        return results
    if command == "rag-search-job":
        result = run_rag_search_job(
            path=args.path,
            db_path=args.db_path,
            limit=args.limit,
            scope=args.scope,
        )
        if args.format == "table":
            rendered = format_rag_search_job_table(
                result,
                text_preview_chars=args.text_preview_chars,
                columns=None if args.columns is None else args.columns.split(","),
            )
            print(rendered)
            if args.save_report:
                saved_report_path = _save_report(rendered, args.save_report)
                print(f"saved_report_path: {saved_report_path}")
            return None
        if args.save_report:
            result["saved_report_path"] = str(args.save_report)
            _save_report(json.dumps(result, ensure_ascii=False, indent=2), args.save_report)
        return result

    if command == "rag-answer-context":
        return run_rag_answer_context(
            query=args.query,
            db_path=args.db_path,
            limit=args.limit,
        )

    if command == "rag-answer":
        return run_rag_answer(
            query=args.query,
            db_path=args.db_path,
            limit=args.limit,
            call_real_api=args.call_real_api,
        )
    if command == "orchestrate-answer":
        return run_orchestrate_answer(
            query=args.query,
            db_path=args.db_path,
            limit=args.limit,
            drafts=args.drafts,
            include_critique=not args.no_critique,
            hybrid=args.hybrid,
            alpha=args.alpha,
            call_real_api=args.call_real_api,
        )
    if command == "scoring-rank":
        report = run_scoring_rank(path=args.path, limit=args.limit)
        if args.output:
            output_path = Path(args.output)
            if any(part == ".." for part in output_path.parts):
                raise ValueError(f"path traversal is not allowed: {args.output}")
            if output_path.exists() and not args.overwrite:
                print(f"output already exists: {output_path}")
                return 1
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {"output": str(output_path), "count": report.get("count", 0)}
        if args.format == "table":
            lines = ["rank | name | score", "--- | --- | ---"]
            rows = report.get("results")
            for rank, item in enumerate(rows if isinstance(rows, list) else [], start=1):
                if isinstance(item, dict):
                    lines.append(f"{rank} | {item.get('name', '')} | {item.get('score', '')}")
            lines.append(str(report.get("disclaimer", "")))
            print("\n".join(lines))
            return None
        return report
    if command == "scoring-validate":
        result = run_scoring_validate(path=args.path)
        _print_json(result)
        return 0 if bool(result["valid"]) else 1

    if command == "forecast-evaluate":
        return run_forecast_evaluate(
            path=args.path,
            value_column=args.value_column,
            horizon=args.horizon,
            space=args.space,
        )
    if command == "forecast-predict":
        return run_forecast_predict(
            path=args.path,
            value_column=args.value_column,
            horizon=args.horizon,
            space=args.space,
        )
    if command == "serve":
        from investment_assistant.webapi.server import serve

        serve(host=args.host, port=args.port)
        return None
    msg = f"unknown command: {command}"
    raise ValueError(msg)


if __name__ == "__main__":
    raise SystemExit(main())
