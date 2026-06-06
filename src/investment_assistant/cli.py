"""Command-line utilities for operating the investment assistant foundation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.config.loader import load_yaml
from investment_assistant.ingestion.fetcher import SafeFetcher, reject_path_traversal
from investment_assistant.llm.factory import (
    DEFAULT_GEMINI_CONFIG_PATH,
    build_llm_service,
    load_gemini_runtime_config,
)
from investment_assistant.llm.gemini_client import TextGenerationClient
from investment_assistant.rag.answer import LocalRagAnswerClient, generate_rag_answer
from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.indexer import index_directory
from investment_assistant.rag.search import build_answer_context, search_chunks
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH, RagStore
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


def run_rag_search(
    *,
    query: str,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Search the local RAG store without calling an LLM."""

    store = RagStore(db_path)
    return [asdict(result) for result in search_chunks(store, query=query, limit=limit)]




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

    fetch_parser = subparsers.add_parser(
        "fetch-url",
        help="Safely fetch an http(s) URL with robots.txt, cache, and rate limiting",
    )
    fetch_parser.add_argument("--url", required=True)
    fetch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check robots.txt and planned fetch safety; do not fetch target URL",
    )
    fetch_parser.add_argument("--preview-chars", type=int, default=500)
    fetch_parser.add_argument(
        "--save-text",
        help=(
            "Save the fetched response text to this local path, for example "
            "local_docs/page.txt. Dry-runs and robots-blocked URLs are not saved."
        ),
    )
    fetch_parser.add_argument(
        "--extract-text",
        action="store_true",
        help="Normalize HTML into readable text before previewing and saving.",
    )
    fetch_parser.add_argument(
        "--include-metadata",
        action="store_true",
        help="Prefix saved text with source URL, fetch time, status, and content-type metadata.",
    )

    fetch_job_parser = subparsers.add_parser(
        "fetch-job",
        help="Run a YAML-defined batch of safe fetch-url jobs",
    )
    fetch_job_parser.add_argument("--path", required=True)
    fetch_job_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check robots.txt for each source without fetching or saving target pages",
    )
    fetch_job_parser.add_argument("--preview-chars", type=int, default=500)

    rag_index_parser = subparsers.add_parser(
        "rag-index",
        help="Index a local text/Markdown file into the local RAG store",
    )
    rag_index_parser.add_argument("--path", required=True)
    rag_index_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_index_parser.add_argument("--max-chars", type=int, default=800)
    rag_index_parser.add_argument("--overlap-chars", type=int, default=120)

    rag_index_dir_parser = subparsers.add_parser(
        "rag-index-dir",
        help="Recursively index local .txt/.md/.markdown files into the local RAG store",
    )
    rag_index_dir_parser.add_argument("--path", required=True)
    rag_index_dir_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_index_dir_parser.add_argument("--max-chars", type=int, default=800)
    rag_index_dir_parser.add_argument("--overlap-chars", type=int, default=120)

    rag_search_parser = subparsers.add_parser(
        "rag-search",
        help="Search indexed local RAG chunks without calling an LLM",
    )
    rag_search_parser.add_argument("--query", required=True)
    rag_search_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_search_parser.add_argument("--limit", type=int, default=5)
    rag_search_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output JSON for automation or a compact Markdown table for terminal review.",
    )
    rag_search_parser.add_argument(
        "--text-preview-chars",
        type=int,
        default=120,
        help="Maximum result text characters shown in --format table output.",
    )
    rag_search_parser.add_argument(
        "--columns",
        help=(
            "Comma-separated columns for --format table. Available: "
            "rank,score,source,chunk,source_url,fetched_at,status_code,content_type,metadata,text_preview."
        ),
    )

    rag_search_job_parser = subparsers.add_parser(
        "rag-search-job",
        help="Search local RAG chunks using query_hint values from a fetch-job YAML file",
    )
    rag_search_job_parser.add_argument("--path", required=True)
    rag_search_job_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_search_job_parser.add_argument("--limit", type=int, default=5)
    rag_search_job_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output JSON for automation or compact Markdown tables for terminal review.",
    )
    rag_search_job_parser.add_argument(
        "--text-preview-chars",
        type=int,
        default=120,
        help="Maximum result text characters shown in --format table output.",
    )
    rag_search_job_parser.add_argument(
        "--columns",
        help=(
            "Comma-separated columns for --format table. Available: "
            "rank,score,source,chunk,source_url,fetched_at,status_code,content_type,metadata,text_preview."
        ),
    )
    rag_search_job_parser.add_argument(
        "--save-report",
        help="Save rag-search-job output to this local .md or .json report path.",
    )

    rag_context_parser = subparsers.add_parser(
        "rag-answer-context",
        help="Print citation-friendly local context for a query without calling an LLM",
    )
    rag_context_parser.add_argument("--query", required=True)
    rag_context_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_context_parser.add_argument("--limit", type=int, default=5)

    rag_answer_parser = subparsers.add_parser(
        "rag-answer",
        help="Generate a guarded citation-aware RAG answer; dry-run uses a local fake client",
    )
    rag_answer_parser.add_argument("--query", required=True)
    rag_answer_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_answer_parser.add_argument("--limit", type=int, default=5)
    rag_answer_parser.add_argument(
        "--call-real-api",
        action="store_true",
        help="Use the real Gemini client through LlmService; omitted means local fake client",
    )

    scoring_parser = subparsers.add_parser(
        "scoring-rank",
        help="Rank local CSV investment candidates without Gemini or auto-trading",
    )
    scoring_parser.add_argument("--path", required=True)
    scoring_parser.add_argument("--limit", type=int, default=10)
    scoring_parser.add_argument("--expense-weight", type=float, default=0.30)
    scoring_parser.add_argument("--return-weight", type=float, default=0.30)
    scoring_parser.add_argument("--volatility-weight", type=float, default=0.25)
    scoring_parser.add_argument("--diversification-weight", type=float, default=0.15)

    scoring_validate_parser = subparsers.add_parser(
        "scoring-validate",
        help="Validate a local scoring CSV without Gemini, scoring, or auto-trading",
    )
    scoring_validate_parser.add_argument("--path", required=True)

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

    if args.command == "fetch-url":
        result = run_fetch_url(
            url=str(args.url),
            dry_run=bool(args.dry_run),
            preview_chars=int(args.preview_chars),
            save_text=None if args.save_text is None else str(args.save_text),
            extract_text=bool(args.extract_text),
            include_metadata=bool(args.include_metadata),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "fetch-job":
        result = run_fetch_job(
            path=str(args.path),
            dry_run=bool(args.dry_run),
            preview_chars=int(args.preview_chars),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rag-index":
        result = run_rag_index(
            path=str(args.path),
            db_path=str(args.db_path),
            max_chars=int(args.max_chars),
            overlap_chars=int(args.overlap_chars),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rag-index-dir":
        result = run_rag_index_dir(
            path=str(args.path),
            db_path=str(args.db_path),
            max_chars=int(args.max_chars),
            overlap_chars=int(args.overlap_chars),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rag-search":
        search_result = run_rag_search(
            query=str(args.query),
            db_path=str(args.db_path),
            limit=int(args.limit),
        )
        if str(args.format) == "table":
            print(
                format_rag_search_table(
                    search_result,
                    text_preview_chars=int(args.text_preview_chars),
                    columns=None if args.columns is None else str(args.columns).split(","),
                )
            )
        else:
            print(json.dumps(search_result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rag-search-job":
        search_job_result = run_rag_search_job(
            path=str(args.path),
            db_path=str(args.db_path),
            limit=int(args.limit),
        )
        save_report_path = None if args.save_report is None else str(args.save_report)
        if str(args.format) == "table":
            table_output = format_rag_search_job_table(
                search_job_result,
                text_preview_chars=int(args.text_preview_chars),
                columns=None if args.columns is None else str(args.columns).split(","),
            )
            print(table_output)
            if save_report_path is not None:
                saved_report_path = _save_report(table_output, save_report_path)
                print(f"saved_report_path: {saved_report_path}")
        else:
            if save_report_path is not None:
                search_job_result["saved_report_path"] = str(Path(save_report_path))
                _save_report(
                    json.dumps(search_job_result, ensure_ascii=False, indent=2),
                    save_report_path,
                )
            print(json.dumps(search_job_result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rag-answer-context":
        context_result = run_rag_answer_context(
            query=str(args.query),
            db_path=str(args.db_path),
            limit=int(args.limit),
        )
        print(json.dumps(context_result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rag-answer":
        answer_result = run_rag_answer(
            query=str(args.query),
            config_path=config_path,
            db_path=str(args.db_path),
            limit=int(args.limit),
            call_real_api=bool(args.call_real_api),
        )
        print(json.dumps(answer_result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "scoring-validate":
        validation_result = run_scoring_validate(path=str(args.path))
        print(json.dumps(validation_result, ensure_ascii=False, indent=2))
        return 0 if bool(validation_result["valid"]) else 1

    if args.command == "scoring-rank":
        result = run_scoring_rank(
            path=str(args.path),
            limit=int(args.limit),
            expense_weight=float(args.expense_weight),
            return_weight=float(args.return_weight),
            volatility_weight=float(args.volatility_weight),
            diversification_weight=float(args.diversification_weight),
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
