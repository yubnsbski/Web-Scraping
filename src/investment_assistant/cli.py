"""Command-line utilities for operating the investment assistant foundation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.ingestion.fetcher import SafeFetcher
from investment_assistant.llm.factory import (
    DEFAULT_GEMINI_CONFIG_PATH,
    build_llm_service,
    load_gemini_runtime_config,
)
from investment_assistant.llm.gemini_client import TextGenerationClient
from investment_assistant.rag.answer import LocalRagAnswerClient, generate_rag_answer
from investment_assistant.rag.chunker import chunk_text, load_document
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
) -> dict[str, object]:
    """Run a safe URL fetch with robots, rate limiting, and cache."""

    fetcher = SafeFetcher()
    result = fetcher.fetch(url, dry_run=dry_run, preview_chars=preview_chars)
    return asdict(result)


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


def run_rag_search(
    *,
    query: str,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Search the local RAG store without calling an LLM."""

    store = RagStore(db_path)
    return [asdict(result) for result in search_chunks(store, query=query, limit=limit)]


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

    rag_index_parser = subparsers.add_parser(
        "rag-index",
        help="Index a local text/Markdown file into the local RAG store",
    )
    rag_index_parser.add_argument("--path", required=True)
    rag_index_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_index_parser.add_argument("--max-chars", type=int, default=800)
    rag_index_parser.add_argument("--overlap-chars", type=int, default=120)

    rag_search_parser = subparsers.add_parser(
        "rag-search",
        help="Search indexed local RAG chunks without calling an LLM",
    )
    rag_search_parser.add_argument("--query", required=True)
    rag_search_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_search_parser.add_argument("--limit", type=int, default=5)

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
    scoring_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output JSON by default, or print a compact local-only table",
    )
    scoring_parser.add_argument(
        "--output",
        help="Write scoring-rank JSON result to this file instead of printing the full report",
    )

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
        if str(getattr(args, "format", "json")) == "table" and not getattr(args, "output", None):
            print(_format_scoring_rank_table(result))
            return 0
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

    if args.command == "rag-search":
        search_result = run_rag_search(
            query=str(args.query),
            db_path=str(args.db_path),
            limit=int(args.limit),
        )
        print(json.dumps(search_result, ensure_ascii=False, indent=2))
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
        if getattr(args, "output", None):
            output_path = Path(str(args.output))
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps({"output_path": str(output_path)}, ensure_ascii=False, indent=2))
            return 0
        if str(getattr(args, "format", "json")) == "table":
            print(_format_scoring_rank_table(result))
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 2


def _count_report_results(report: dict[str, object]) -> int:
    """Return the number of result rows in a JSON-like report."""

    results = report.get("results", [])
    if isinstance(results, list):
        return len(results)
    return 0


def _format_scoring_rank_table(report: dict[str, object]) -> str:
    """Format a compact non-advisory scoring rank table for terminal output."""

    header = "rank | name | total_score | expense | return | volatility | diversification"
    separator = "-" * len(header)
    lines = [header, separator]
    results = report.get("results", [])
    if not isinstance(results, list):
        results = []
    for item in results:
        if not isinstance(item, dict):
            continue
        metrics = item.get("metrics", {})
        score = item.get("score", {})
        if not isinstance(metrics, dict) or not isinstance(score, dict):
            continue
        lines.append(
            " | ".join(
                (
                    str(item.get("rank", "")),
                    str(item.get("name", "")),
                    _format_table_number(score.get("total_score")),
                    _format_table_number(metrics.get("expense_ratio")),
                    _format_table_number(metrics.get("annual_return")),
                    _format_table_number(metrics.get("volatility")),
                    _format_table_number(metrics.get("diversification_score")),
                )
            )
        )

    disclaimer = report.get("disclaimer")
    if disclaimer:
        lines.extend(("", str(disclaimer)))
    return "\n".join(lines)


def _format_table_number(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
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
