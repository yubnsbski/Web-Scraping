"""Command-line utilities for operating the investment assistant foundation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

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


def run_rag_search(
    *,
    query: str,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
    hybrid: bool = False,
    alpha: float = 0.5,
) -> list[dict[str, object]]:
    """Search the local RAG store without calling an LLM.

    With ``hybrid=True`` the lexical BM25 ranking is blended with semantic
    embedding similarity (``alpha`` weights the semantic part).
    """

    store = RagStore(db_path)
    if hybrid:
        results = hybrid_search(store, query=query, limit=limit, alpha=alpha)
    else:
        results = search_chunks(store, query=query, limit=limit)
    return [asdict(result) for result in results]




def format_rag_search_table(
    results: list[dict[str, object]],
    *,
    text_preview_chars: int = 120,
    columns: Sequence[str] | None = None,
) -> str:
    """Format RAG search results as a compact Markdown table for terminal review."""

    if not results:
        return "No RAG search results."

    selected_columns = _parse_table_columns(columns)
    rows = [
        "| " + " | ".join(selected_columns) + " |",
        "| " + " | ".join("---" for _ in selected_columns) + " |",
    ]
    for rank, result in enumerate(results, 1):
        rows.append(
            "| "
            + " | ".join(
                _table_cell(
                    _rag_table_value(
                        column,
                        rank=rank,
                        result=result,
                        text_preview_chars=text_preview_chars,
                    )
                )
                for column in selected_columns
            )
            + " |"
        )
    return "\n".join(rows)




def run_rag_search_job(
    *,
    path: str | Path,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
) -> dict[str, object]:
    """Search the local RAG store for each query_hint in a fetch-job file."""

    job_path = Path(path)
    config = load_yaml(job_path)
    sources = _fetch_job_sources(config, job_path)
    results: list[dict[str, object]] = []
    for source in sources:
        query = _query_from_fetch_job_source(source)
        results.append(
            {
                "name": str(source["name"]),
                "url": str(source["url"]),
                "output_path": str(source["output_path"]),
                "query": query,
                "query_hint": None
                if source.get("query_hint") is None
                else str(source.get("query_hint")),
                "results": run_rag_search(query=query, db_path=db_path, limit=limit),
            }
        )
    return {
        "job_path": str(job_path),
        "db_path": str(db_path),
        "sources_count": len(results),
        "results": results,
    }


def format_rag_search_job_table(
    search_job_result: dict[str, object],
    *,
    text_preview_chars: int = 120,
    columns: Sequence[str] | None = None,
) -> str:
    """Format fetch-job query_hint search results for terminal review."""

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
        raw_search_results = item.get("results")
        search_results = raw_search_results if isinstance(raw_search_results, list) else []
        table_rows = [row for row in search_results if isinstance(row, dict)]
        blocks.append(
            format_rag_search_table(
                table_rows,
                text_preview_chars=text_preview_chars,
                columns=columns,
            )
        )
    return "\n\n".join(blocks)


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
) -> dict[str, object]:
    """Run multi-model orchestration (draft->critique->synthesize) over RAG context."""

    store = RagStore(db_path)
    if hybrid:
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
            "skipped": True,
        }

    orchestrator = build_orchestrator(
        config_path,
        config=OrchestrationConfig(n_drafts=drafts, include_critique=include_critique),
        call_real_api=call_real_api,
    )
    outcome = orchestrator.run(query=query, context=context)
    payload = outcome.to_dict()
    payload["context"] = context
    payload["results"] = [asdict(result) for result in results]
    payload["call_real_api"] = call_real_api
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
    """Download a real financial dataset for forecasting (no auto-trading)."""

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
    """Forecast the next horizon steps with the ensemble (research aid only)."""

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
    expense_weight: float = 0.30,
    return_weight: float = 0.30,
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
    report: dict[str, object] = build_scoring_report(path=path, limit=limit, weights=weights)
    return report


def run_scoring_validate(*, path: str | Path) -> dict[str, object]:
    """Validate a local scoring CSV without LLMs, scoring, or trading actions."""

    return validate_scoring_csv(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""

    configure_logging()
    parser = argparse.ArgumentParser(prog="investment-assistant")
    parser.add_argument("--config", default=str(DEFAULT_GEMINI_CONFIG_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    budget_parser = subparsers.add_parser("budget", help="Show Gemini budget usage")
    budget_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    smoke_parser = subparsers.add_parser("smoke", help="Run a no-network LLM service smoke check")
    smoke_parser.add_argument("--task-type", default="rag_answer")
    smoke_parser.add_argument("--prompt", default="Gemini budget guard smoke test")

    live_parser = subparsers.add_parser(
        "gemini-live",
        help="Manually call the real Gemini API through the guarded service",
    )
    live_parser.add_argument("--task-type", default="rag_answer")
    live_parser.add_argument("--prompt", required=True)
    live_parser.add_argument(
        "--call-real-api",
        action="store_true",
        help="Required safety acknowledgement because this consumes Gemini quota",
    )



    args = parser.parse_args(argv)
    config_path = str(args.config)

    if args.command == "budget":
        report = build_budget_report(config_path)
        if bool(args.json):
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        else:
            print(_format_budget_report(report))
        return 0

    if args.command == "smoke":
        result = run_smoke(
            config_path=config_path,
            task_type=str(args.task_type),
            prompt=str(args.prompt),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "gemini-live":
        if not bool(args.call_real_api):
            print("Refusing to call Gemini API without --call-real-api.")
            return 2
        result = run_gemini_live(
            config_path=config_path,
            task_type=str(args.task_type),
            prompt=str(args.prompt),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0


        

    return 2





_DEFAULT_RAG_TABLE_COLUMNS = ("rank", "score", "source", "chunk", "metadata", "text_preview")
_ALLOWED_RAG_TABLE_COLUMNS = frozenset(
    {
        "rank",
        "score",
        "source",
        "chunk",
        "source_url",
        "fetched_at",
        "status_code",
        "content_type",
        "metadata",
        "text_preview",
    }
)


def _parse_table_columns(columns: Sequence[str] | None) -> tuple[str, ...]:
    if columns is None:
        return _DEFAULT_RAG_TABLE_COLUMNS
    parsed = tuple(column.strip() for column in columns if column.strip())
    if not parsed:
        return _DEFAULT_RAG_TABLE_COLUMNS
    unknown = [column for column in parsed if column not in _ALLOWED_RAG_TABLE_COLUMNS]
    if unknown:
        msg = f"unknown rag-search table column(s): {', '.join(unknown)}"
        raise ValueError(msg)
    return parsed


def _rag_table_value(
    column: str,
    *,
    rank: int,
    result: dict[str, object],
    text_preview_chars: int,
) -> str:
    metadata = result.get("metadata")
    if column == "rank":
        return str(rank)
    if column == "score":
        return str(result.get("score", ""))
    if column == "source":
        return str(result.get("source", ""))
    if column == "chunk":
        return str(result.get("chunk_index", ""))
    if column == "metadata":
        return _metadata_summary(metadata)
    if column == "text_preview":
        return _preview_text(str(result.get("text", "")), text_preview_chars)
    return _metadata_value(metadata, column)


def _metadata_value(value: object, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    raw_value = value.get(key)
    return "" if raw_value is None else str(raw_value)


def _metadata_summary(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    keys = ("source_url", "fetched_at", "status_code", "content_type")
    parts = [f"{key}={value[key]}" for key in keys if value.get(key)]
    return " ".join(parts)


def _preview_text(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max(0, max_chars - 1)]}…"


def _table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _fetch_job_sources(config: dict[str, object], job_path: Path) -> list[dict[str, object]]:
    raw_sources = config.get("sources")
    if not isinstance(raw_sources, list):
        msg = f"fetch job must contain a sources list: {job_path}"
        raise ValueError(msg)

    sources: list[dict[str, object]] = []
    for index, raw_source in enumerate(raw_sources, start=1):
        if not isinstance(raw_source, dict):
            msg = f"fetch job source #{index} must be a mapping"
            raise ValueError(msg)
        source = {str(key): value for key, value in raw_source.items()}
        for field in ("name", "url", "output_path"):
            if not source.get(field):
                msg = f"fetch job source #{index} is missing required field: {field}"
                raise ValueError(msg)
        sources.append(source)
    return sources






def _save_report(content: str, path: str | Path) -> str:
    report_path = reject_path_traversal(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
    return str(report_path)


def _query_from_fetch_job_source(source: dict[str, object]) -> str:
    query_hint = source.get("query_hint")
    if query_hint is not None and str(query_hint).strip():
        return str(query_hint)
    return str(source["name"])


def _parse_int_list(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    windows = tuple(int(part.strip()) for part in str(value).split(",") if part.strip())
    if any(window < 1 for window in windows):
        msg = "moving-average windows must be positive integers"
        raise ValueError(msg)
    return windows


def _int_or_default(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    return default


def _bool_or_default(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return default


def _write_scoring_output(result: dict[str, object], output: str, *, overwrite: bool) -> int:
    """Write a scoring-rank result to a file, refusing to overwrite by default."""

    output_path = reject_path_traversal(output)
    if output_path.exists() and not overwrite:
        print(
            json.dumps(
                {
                    "error": "output file already exists; pass --overwrite to replace it",
                    "output": str(output_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "count": result.get("count"),
                "call_real_api": False,
                "auto_trading": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _format_scoring_rank_table(report: dict[str, object]) -> str:
    """Format scoring-rank JSON as a compact comparison table for humans."""

    headers = (
        "rank",
        "name",
        "total_score",
        "expense_ratio",
        "annual_return",
        "volatility",
        "diversification_score",
    )
    rows: list[tuple[str, ...]] = [headers]
    raw_results = report.get("results", [])
    results = raw_results if isinstance(raw_results, list) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        metrics = item.get("metrics", {})
        score = item.get("score", {})
        metrics = metrics if isinstance(metrics, dict) else {}
        score = score if isinstance(score, dict) else {}
        rows.append(
            (
                _format_table_value(item.get("rank", "")),
                _format_table_value(item.get("name", "")),
                _format_table_value(score.get("total_score", "")),
                _format_table_value(metrics.get("expense_ratio", "")),
                _format_table_value(metrics.get("annual_return", "")),
                _format_table_value(metrics.get("volatility", "")),
                _format_table_value(metrics.get("diversification_score", "")),
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(headers))]
    table_lines = [
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()
        for row in rows
    ]
    lines = [
        f"source: {report.get('source', '')}",
        f"limit: {report.get('limit', '')}",
        f"call_real_api: {str(bool(report.get('call_real_api', False))).lower()}",
        f"auto_trading: {str(bool(report.get('auto_trading', False))).lower()}",
        "",
        *table_lines,
        "",
        str(
            report.get(
                "disclaimer", "投資助言・売買推奨ではありません。最終判断はユーザー本人が行います。"
            )
        ),
    ]
    return "\n".join(lines)


def _format_table_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _format_budget_report(report: BudgetReport) -> str:
    return "\n".join(
        (
            f"model: {report.model}",
            f"daily: {report.daily_used}/{report.hard_daily_limit} "
            f"hard-stop requests used ({report.daily_remaining} remaining)",
            f"monthly: {report.monthly_used}/{report.hard_monthly_limit} "
            f"hard-stop requests used ({report.monthly_remaining} remaining)",
            f"warning: {str(report.warning).lower()}",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
