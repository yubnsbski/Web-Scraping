"""Command-line utilities for operating the investment assistant foundation."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from investment_assistant.cli_market import (
    DEFAULT_YAHOO_FINANCIALS_PATH,
)
from investment_assistant.cli_market import (
    check_daily_refresh_readiness as check_daily_refresh_readiness,
)
from investment_assistant.cli_market import (
    run_market_bars_backfill as run_market_bars_backfill,
)
from investment_assistant.cli_market import (
    run_market_daily_refresh as run_market_daily_refresh,
)
from investment_assistant.cli_market import (
    run_market_financials as run_market_financials,
)
from investment_assistant.cli_market import (
    run_market_inbox as run_market_inbox,
)
from investment_assistant.cli_market import (
    run_market_ohlcv as run_market_ohlcv,
)
from investment_assistant.cli_market import (
    run_yahoo_intraday as run_yahoo_intraday,
)
from investment_assistant.config.loader import load_yaml
from investment_assistant.crawler.frontier import CrawlReport, FetchedPage, crawl
from investment_assistant.crawler.policy import CrawlLimits, CrawlPolicy
from investment_assistant.crawler.registry import build_crawl_targets_from_registry
from investment_assistant.edinet.client import EdinetClient
from investment_assistant.edinet.csv_extract import parse_csv_archive, select_metrics, to_rag_text
from investment_assistant.edinet.ingest import date_range, ingest_targets, recent_dates
from investment_assistant.edinet.models import (
    EdinetDocument,
    filter_by_doc_types,
    filter_by_ticker,
    securities_code,
)
from investment_assistant.edinet.registry import build_edinet_targets_from_registry
from investment_assistant.feedback import DEFAULT_FEEDBACK_DB_PATH, feedback_source_scores
from investment_assistant.forecasting import service as forecast_service
from investment_assistant.forecasting.dataset import DEFAULT_DATASET, download_dataset
from investment_assistant.forecasting.timeseries import load_timeseries_csv
from investment_assistant.ingestion.fetcher import (
    DEFAULT_HTTP_CACHE_PATH,
    SafeFetcher,
    reject_path_traversal,
)
from investment_assistant.ingestion.http_cache import HttpCache
from investment_assistant.ingestion.source_registry import (
    build_fetch_job_from_registry,
    fetch_job_to_yaml,
)
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
from investment_assistant.rag.embeddings import Embedder, resolve_embedder
from investment_assistant.rag.indexer import index_directory
from investment_assistant.rag.search import (
    SearchResult,
    boost_by_entities,
    boost_by_feedback,
    build_answer_context,
    diversify_results,
    hybrid_search,
    search_chunks,
    search_result_to_dict,
)
from investment_assistant.rag.store import (
    DEFAULT_RAG_DB_PATH,
    RagStore,
    read_stored_embedder_name,
)
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


DEFAULT_RAG_STATS_KEYWORDS: tuple[str, ...] = (
    "配当",
    "株主還元",
    "自己株式",
    "営業CF",
    "営業キャッシュフロー",
    "DOE",
    "配当性向",
    "有価証券報告書",
    "決算短信",
    "統合報告書",
)


@dataclass
class _RagSourceStats:
    source: str
    keyword_hits: dict[str, int]
    chunks: int = 0
    chars: int = 0
    source_url: str | None = None
    fetched_at: str | None = None
    status_code: str | None = None
    content_type: str | None = None


def _rag_source_stats_to_dict(stats: _RagSourceStats) -> dict[str, object]:
    return {
        "source": stats.source,
        "chunks": stats.chunks,
        "chars": stats.chars,
        "source_url": stats.source_url,
        "fetched_at": stats.fetched_at,
        "status_code": stats.status_code,
        "content_type": stats.content_type,
        "keyword_hits": stats.keyword_hits,
    }


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


def run_source_registry_build_fetch_job(
    *,
    path: str | Path,
    output: str | Path | None = None,
) -> dict[str, object]:
    """Convert an approved source registry into a fetch-job payload."""

    result = build_fetch_job_from_registry(path)
    if output is not None:
        output_path = Path(output)
        if any(part == ".." for part in output_path.parts):
            raise ValueError(f"path traversal is not allowed: {output}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fetch_job = result.get("fetch_job")
        if not isinstance(fetch_job, dict):
            raise ValueError("fetch_job result is invalid")
        output_path.write_text(fetch_job_to_yaml(fetch_job), encoding="utf-8")
        result["output"] = str(output_path)
    return result


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


def run_edinet_documents(
    *,
    date: str,
    ticker: str | None = None,
    financial_only: bool = True,
) -> dict[str, object]:
    """List EDINET filings submitted on ``date`` (official public disclosure API).

    Requires network access and the ``EDINET_API_KEY`` environment variable.
    """

    client = EdinetClient()
    documents = client.list_documents(date)
    if ticker:
        documents = filter_by_ticker(documents, ticker)
    if financial_only:
        documents = filter_by_doc_types(documents)
    return {
        "date": date,
        "ticker": ticker,
        "count": len(documents),
        "documents": [
            {
                "doc_id": doc.doc_id,
                "sec_code": doc.sec_code,
                "ticker": doc.ticker,
                "filer_name": doc.filer_name,
                "doc_type": doc.doc_type_label,
                "period_end": doc.period_end,
                "submit_datetime": doc.submit_datetime,
                "has_csv": doc.has_csv,
            }
            for doc in documents
        ],
    }


def run_edinet_extract(
    *,
    zip_path: str | Path,
    doc_id: str,
    ticker: str | None = None,
    company: str | None = None,
    period_end: str | None = None,
    doc_type_code: str = "120",
    save_text: str | Path | None = None,
    preview_chars: int = 800,
) -> dict[str, object]:
    """Extract financial metrics from a downloaded EDINET CSV archive (offline).

    Turns a type=5 CSV ZIP into RAG-ready text containing the structured numbers
    (営業CF / 自己資本比率 / 配当性向) that the RAG store is currently missing.
    """

    data = Path(zip_path).read_bytes()
    values = parse_csv_archive(data)
    document = EdinetDocument(
        doc_id=doc_id,
        edinet_code=None,
        sec_code=securities_code(ticker) if ticker else None,
        filer_name=company or "",
        doc_type_code=doc_type_code,
        doc_description="",
        period_start=None,
        period_end=period_end,
        submit_datetime=None,
        has_xbrl=False,
        has_csv=True,
        has_pdf=False,
    )
    text = to_rag_text(document, values, company=company)
    saved_path: str | None = None
    if save_text is not None:
        saved_path = str(reject_path_traversal(save_text))
        target = Path(saved_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return {
        "doc_id": doc_id,
        "values_extracted": len(values),
        "metrics": sorted(select_metrics(values).keys()),
        "saved_path": saved_path,
        "text_preview": text[: max(0, preview_chars)],
    }


def _safe_crawl_fetch(fetcher: SafeFetcher) -> Callable[[str], FetchedPage]:
    """Adapt SafeFetcher.fetch_document into the frontier's FetchFn."""

    def fetch(url: str) -> FetchedPage:
        document = fetcher.fetch_document(url)
        return FetchedPage(
            url=document.url,
            allowed=document.allowed_by_robots,
            html=document.html,
            status_code=document.status_code,
        )

    return fetch


def run_crawl(
    *,
    path: str | Path,
    output_dir: str | Path = "local_docs/crawl",
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    max_pages: int | None = None,
    dry_run: bool = False,
    index_after: bool = True,
    fetch: Callable[[str], FetchedPage] | None = None,
) -> dict[str, object]:
    """Run targeted IR crawls defined in a source registry (Phase 3).

    Descends from each issuer_ir crawl start page toward dividend-policy /
    financial body pages and saves the substantive ones for RAG. Requires
    network for live runs; ``fetch`` is injectable for offline testing.
    """

    targets = build_crawl_targets_from_registry(path)
    base_dir = reject_path_traversal(output_dir)
    fetch_fn = fetch or _safe_crawl_fetch(SafeFetcher())

    if dry_run:
        return {
            "path": str(path),
            "dry_run": True,
            "targets": [
                {"name": str(t.get("name") or ""), "url": str(t.get("url") or "")}
                for t in targets
            ],
        }

    results: list[dict[str, object]] = []
    saved_total = 0
    for target in targets:
        policy = CrawlPolicy.from_registry_source(target)
        if max_pages is not None:
            policy.limits = CrawlLimits(
                max_depth=policy.limits.max_depth,
                max_pages=max_pages,
                max_elapsed_seconds=policy.limits.max_elapsed_seconds,
            )
        report = crawl(policy, start_url=str(target["url"]), fetch=fetch_fn)
        folder = str(target.get("ticker") or target.get("name") or "crawl")
        saved = _save_crawl_pages(report, base_dir / folder)
        saved_total += len(saved)
        summary = report.as_dict()
        summary["name"] = str(target.get("name") or "")
        summary["saved_paths"] = saved
        results.append(summary)

    output: dict[str, object] = {
        "path": str(path),
        "output_dir": str(base_dir),
        "targets_count": len(targets),
        "saved_pages": saved_total,
        "results": results,
    }
    if index_after and saved_total:
        # Crawled IR pages are saved with a plain "source_url: ..." header, not
        # YAML front matter, so the default content-only filter (and its
        # paired prune) would wrongly treat every crawled page as an
        # operational file and delete them from the store. Index every file
        # here and leave pruning to the dedicated maintenance path.
        output["index"] = run_rag_index_dir(
            path=str(base_dir), db_path=db_path, content_only=False, prune=False
        )
    return output


def run_storage_prune(
    *,
    docs_dirs: list[str] | None = None,
    keep_per_dir: int = 8,
    http_max_rows: int = 500,
    prune_cache: bool = True,
) -> dict[str, object]:
    """Bound disk growth: keep recent filings per ticker and trim the HTTP cache."""

    from investment_assistant import maintenance

    roots: list[str | Path] = list(docs_dirs or ["local_docs/edinet", "local_docs/crawl"])
    return maintenance.run_storage_prune(
        docs_roots=roots,
        cache_path=DEFAULT_HTTP_CACHE_PATH if prune_cache else None,
        keep_per_dir=keep_per_dir,
        http_max_rows=http_max_rows,
    )


def _save_crawl_pages(report: CrawlReport, folder: Path) -> list[str]:
    saved: list[str] = []
    for index, page in enumerate(report.target_pages, start=1):
        path = folder / f"page_{index:02d}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        header = f"source_url: {page.url}\n\n"
        path.write_text(header + page.text + "\n", encoding="utf-8")
        saved.append(str(path))
    return saved


def run_edinet_ingest(
    *,
    registry_path: str | Path = "examples/source_registry_edinet_sample.yaml",
    end_date: str | None = None,
    days: int = 7,
    start_date: str | None = None,
    years: int | None = None,
    output_dir: str | Path = "local_docs/edinet",
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    index_after: bool = True,
    max_periods: int | None = None,
    client: EdinetClient | None = None,
) -> dict[str, object]:
    """Run the end-to-end EDINET ingest and optionally index the result into RAG.

    By default scans the last ``days`` submission dates (ending at ``end_date``,
    default today). For a multi-year backfill, pass ``start_date`` (explicit
    range to ``end_date``) or ``years`` (that many years back from ``end_date``);
    weekends are skipped and the scan is capped for safety. Downloads each
    ticker's recent filings, extracts metrics, and indexes the saved text.
    Requires network for live runs; the ``client`` is injectable for testing.
    """

    targets = build_edinet_targets_from_registry(registry_path)
    edinet_client = client or EdinetClient()
    effective_end = end_date or datetime.now(UTC).date().isoformat()
    if start_date:
        dates = date_range(start_date, effective_end)
        scan_mode = "range"
    elif years and years > 0:
        backfill_start = (
            datetime.fromisoformat(effective_end).date() - timedelta(days=365 * years)
        ).isoformat()
        dates = date_range(backfill_start, effective_end)
        scan_mode = f"backfill_{years}y"
    else:
        dates = recent_dates(effective_end, days)
        scan_mode = "recent"

    result = ingest_targets(
        client=edinet_client,
        targets=targets,
        dates=dates,
        output_dir=output_dir,
        max_periods_override=max_periods,
    )
    result["registry_path"] = str(registry_path)
    result["end_date"] = effective_end
    result["days"] = days
    result["scan_mode"] = scan_mode
    result["scanned_days_requested"] = len(dates)

    if index_after and result.get("ingested_count"):
        result["index"] = run_rag_index_dir(path=str(output_dir), db_path=db_path)
    return result


def _index_embedder(embeddings: str | None) -> Embedder:
    """Resolve the embedder for indexing from a flag or ``RAG_EMBEDDINGS`` env."""

    return resolve_embedder(embeddings or os.getenv("RAG_EMBEDDINGS"))


def run_rag_index(
    *,
    path: str | Path,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    max_chars: int = 800,
    overlap_chars: int = 120,
    embeddings: str | None = None,
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
    store = RagStore(db_path, embedder=_index_embedder(embeddings))
    chunk_count = store.upsert_document(document, chunks)
    return {
        "source": document.source,
        "content_hash": document.content_hash,
        "chunks_indexed": chunk_count,
        "embedder": store.stored_embedder_name(),
        "db_path": str(db_path),
    }


def run_rag_index_dir(
    *,
    path: str | Path,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    max_chars: int = 800,
    overlap_chars: int = 120,
    embeddings: str | None = None,
    content_only: bool = True,
    prune: bool = True,
) -> dict[str, object]:
    """Recursively index local text/Markdown files into the local RAG store."""

    return index_directory(
        path=path,
        db_path=db_path,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        embedder=_index_embedder(embeddings),
        content_only=content_only,
        prune=prune,
    )



def _source_filter_matches(chunk_source: str, source_filter: str) -> bool:
    """Match a chunk source against a target filter flexibly.

    Accepts an exact path, a directory prefix (e.g. ``local_docs/edinet/9432``),
    or a 4-digit ticker code appearing as a path segment — so selecting a ticker
    in the UI matches its documents regardless of which corpus directory holds
    them (EDINET filings live under ``local_docs/edinet/<ticker>/...`` while IR
    crawls live under ``local_docs/nikkei225/<ticker>/...``).
    """

    target = source_filter.strip()
    if not target:
        return True
    if chunk_source == target:
        return True
    if chunk_source.startswith(target.rstrip("/") + "/"):
        return True
    match = re.search(r"\d{4}", target)
    return bool(match and f"/{match.group(0)}/" in f"/{chunk_source}")


def _search_chunks_for_source(
    store: RagStore,
    *,
    query: str,
    source_filter: str,
    limit: int,
) -> list[SearchResult]:
    """Search chunks restricted to one target source (exact path, prefix, or ticker)."""

    terms = tokenize(query)
    if not terms or limit <= 0:
        return []

    results: list[SearchResult] = []
    for chunk in store.list_chunks():
        if not _source_filter_matches(chunk.source, source_filter):
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

def run_rag_stats(
    *,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    keywords: Sequence[str] = DEFAULT_RAG_STATS_KEYWORDS,
) -> dict[str, object]:
    """Summarize local RAG DB contents without calling an LLM."""

    keyword_list = tuple(keyword for keyword in keywords if keyword)
    store = RagStore(db_path)
    chunks = store.list_chunks()

    stats_by_source: dict[str, _RagSourceStats] = {}
    keyword_totals = {keyword: 0 for keyword in keyword_list}
    total_chars = 0

    for chunk in chunks:
        total_chars += len(chunk.text)
        stats = stats_by_source.get(chunk.source)
        if stats is None:
            stats = _RagSourceStats(
                source=chunk.source,
                keyword_hits={keyword: 0 for keyword in keyword_list},
            )
            stats_by_source[chunk.source] = stats

        stats.chunks += 1
        stats.chars += len(chunk.text)

        if stats.source_url is None:
            stats.source_url = chunk.metadata.get("source_url")
        if stats.fetched_at is None:
            stats.fetched_at = chunk.metadata.get("fetched_at")
        if stats.status_code is None:
            stats.status_code = chunk.metadata.get("status_code")
        if stats.content_type is None:
            stats.content_type = chunk.metadata.get("content_type")

        for keyword in keyword_list:
            count = chunk.text.count(keyword)
            if count:
                stats.keyword_hits[keyword] += count
                keyword_totals[keyword] += count

    sources = sorted(
        (_rag_source_stats_to_dict(stats) for stats in stats_by_source.values()),
        key=lambda item: str(item["source"]),
    )

    return {
        "db_path": str(db_path),
        "sources_count": len(sources),
        "chunks_count": len(chunks),
        "total_chars": total_chars,
        "keywords": list(keyword_list),
        "keyword_totals": keyword_totals,
        "sources": sources,
    }


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
    return [search_result_to_dict(result) for result in results]



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
            search_result_to_dict(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    source=chunk.source,
                    chunk_index=chunk.chunk_index,
                    score=float(score),
                    text=chunk.text,
                    metadata=chunk.metadata,
                )
            )
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

    from investment_assistant.rag.search import evidence_highlights

    store = RagStore(db_path)
    results = search_chunks(store, query=query, limit=limit)
    return {
        "query": query,
        "context": build_answer_context(results),
        "highlights": evidence_highlights(results),
        "results": [search_result_to_dict(result) for result in results],
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
    search_query: str | None = None,
    feedback_db: str | Path = DEFAULT_FEEDBACK_DB_PATH,
) -> dict[str, object]:
    """Run multi-model orchestration over RAG context.

    ``query`` is the full prompt shown to the models; ``search_query`` (when
    given) is used for retrieval instead, so injected grounding text (financial
    evidence, source constraints) does not skew the RAG search. Draft diversity
    is owned by the orchestrator's perspectives — one specialized draft per
    requested ``drafts``.
    """

    # Embed queries in the same space the corpus was indexed with (gemini vs
    # hashing), read from DB meta so old hashing DBs keep working.
    embedder = resolve_embedder(read_stored_embedder_name(db_path))
    store = RagStore(db_path, embedder=embedder)
    retrieval_query = search_query or query
    # Retrieve a larger candidate pool, then diversify down so the context spans
    # more documents instead of many redundant passages from one filing.
    pool = max(limit, min(limit * 3, 48))
    if source_filter:
        candidates = _search_chunks_for_source(
            store,
            query=retrieval_query,
            source_filter=source_filter,
            limit=pool,
        )
        max_per_source = limit  # single source: dedup only, do not cap
    elif hybrid:
        candidates = hybrid_search(
            store, query=retrieval_query, limit=pool, alpha=alpha, embedder=embedder
        )
        max_per_source = 3
    else:
        candidates = search_chunks(store, query=retrieval_query, limit=pool)
        max_per_source = 3
    # Learning loop: gently re-rank the pool by accumulated user feedback per
    # source, then diversify down so feedback influences which docs are kept.
    candidates = boost_by_feedback(candidates, feedback_source_scores(feedback_db))
    # Entity-aware boost: when the query names a specific ticker/company, make
    # sure its market-data doc surfaces even if BM25's OR-sum over common
    # sentence words favors longer, more generic documents.
    candidates = boost_by_entities(candidates, retrieval_query)
    results = diversify_results(candidates, limit=limit, max_per_source=max_per_source)
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

    config = OrchestrationConfig(
        n_drafts=max(1, drafts),
        include_critique=include_critique,
    )
    orchestrator = build_orchestrator(config_path, config=config, call_real_api=call_real_api)
    outcome = orchestrator.run(query=query, context=context)
    payload = outcome.to_dict()
    payload["context"] = context
    payload["results"] = [search_result_to_dict(result) for result in results]
    payload["source_filter"] = source_filter
    payload["call_real_api"] = call_real_api
    payload["perspectives"] = list(config.perspectives[: config.n_drafts])
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

    subparsers.add_parser("demo", help="Run the offline end-to-end pipeline demo")

    ohlcv_parser = subparsers.add_parser(
        "market-ohlcv", help="Scrape daily OHLCV from Yahoo Finance (tickers or registry)"
    )
    ohlcv_parser.add_argument("--tickers", help="Comma-separated tickers, e.g. 8306,7203")
    ohlcv_parser.add_argument("--registry", help="Source registry to expand into tickers")
    ohlcv_parser.add_argument("--max", type=int, default=0, help="Cap the universe (0=all)")
    ohlcv_parser.add_argument("--range", default="1mo")
    ohlcv_parser.add_argument("--interval", default="1d")
    ohlcv_parser.add_argument("--output-dir", help="Write one <ticker>.csv per ticker here")

    financials_parser = subparsers.add_parser(
        "market-financials",
        help="Fetch Yahoo Finance PER/PBR/yield/EPS/DPS/market cap",
    )
    financials_parser.add_argument("--tickers", help="Comma-separated tickers, e.g. 8306,7203")
    financials_parser.add_argument("--registry", help="Source registry to expand into tickers")
    financials_parser.add_argument("--max", type=int, default=0, help="Cap the universe (0=all)")
    financials_parser.add_argument("--save", action="store_true", help="Write one CSV")
    financials_parser.add_argument("--output", default=DEFAULT_YAHOO_FINANCIALS_PATH)

    intraday_parser = subparsers.add_parser(
        "market-intraday",
        help="Scrape today's minute-bar prices from Yahoo Finance Japan",
    )
    intraday_parser.add_argument("--tickers", help="Comma-separated tickers, e.g. 8306,7203")
    intraday_parser.add_argument("--registry", help="Source registry to expand into tickers")
    intraday_parser.add_argument("--max", type=int, default=0, help="Cap the universe (0=all)")
    intraday_parser.add_argument("--output-dir", help="Write one <ticker>.csv per ticker here")

    inbox_parser = subparsers.add_parser(
        "market-inbox", help="Report the manually-dropped price CSV inbox status"
    )
    inbox_parser.add_argument("--path", help="Inbox CSV path (default local_docs/market/...)")

    universe_parser = subparsers.add_parser(
        "market-universe-build",
        help="Build the domestic-stock universe CSV from a JPX listed-issues file",
    )
    universe_parser.add_argument("--jpx", required=True, help="Path to JPX data_j CSV export")
    universe_parser.add_argument(
        "--output",
        default="local_docs/market/domestic_universe.csv",
        help="Where to write the universe CSV",
    )
    universe_parser.add_argument(
        "--scope",
        default="domestic",
        help="domestic|all|prime|standard|growth (segment filter)",
    )

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

    source_registry_parser = subparsers.add_parser("source-registry-build-fetch-job")
    source_registry_parser.add_argument("--path", required=True)
    source_registry_parser.add_argument("--output")

    fetch_job_parser = subparsers.add_parser("fetch-job")
    fetch_job_parser.add_argument("--path", required=True)
    fetch_job_parser.add_argument("--dry-run", action="store_true")
    fetch_job_parser.add_argument("--preview-chars", type=int, default=500)

    edinet_documents_parser = subparsers.add_parser("edinet-documents")
    edinet_documents_parser.add_argument("--date", required=True)
    edinet_documents_parser.add_argument("--ticker")
    edinet_documents_parser.add_argument("--all-doc-types", action="store_true")

    storage_prune_parser = subparsers.add_parser("storage-prune")
    storage_prune_parser.add_argument("--docs-dir", action="append", dest="docs_dirs")
    storage_prune_parser.add_argument("--keep-per-dir", type=int, default=8)
    storage_prune_parser.add_argument("--http-max-rows", type=int, default=500)
    storage_prune_parser.add_argument("--no-cache", action="store_true")

    knowledge_diff_parser = subparsers.add_parser("knowledge-diff")
    knowledge_diff_parser.add_argument("--db-path", default=DEFAULT_RAG_DB_PATH)
    knowledge_diff_parser.add_argument("--financials-csv")
    knowledge_diff_parser.add_argument("--snapshot-path")
    knowledge_diff_parser.add_argument("--no-save", action="store_true")

    crawl_parser = subparsers.add_parser("crawl")
    crawl_parser.add_argument("--path", required=True)
    crawl_parser.add_argument("--output-dir", default="local_docs/crawl")
    crawl_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    crawl_parser.add_argument("--max-pages", type=int)
    crawl_parser.add_argument("--dry-run", action="store_true")
    crawl_parser.add_argument("--no-index", action="store_true")

    edinet_ingest_parser = subparsers.add_parser("edinet-ingest")
    edinet_ingest_parser.add_argument(
        "--registry",
        dest="registry_path",
        default="examples/source_registry_edinet_sample.yaml",
    )
    edinet_ingest_parser.add_argument("--end-date")
    edinet_ingest_parser.add_argument("--days", type=int, default=7)
    edinet_ingest_parser.add_argument("--start-date")
    edinet_ingest_parser.add_argument("--years", type=int)
    edinet_ingest_parser.add_argument("--output-dir", default="local_docs/edinet")
    edinet_ingest_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    edinet_ingest_parser.add_argument("--max-periods", type=int)
    edinet_ingest_parser.add_argument("--no-index", action="store_true")

    edinet_extract_parser = subparsers.add_parser("edinet-extract")
    edinet_extract_parser.add_argument("--zip", dest="zip_path", required=True)
    edinet_extract_parser.add_argument("--doc-id", required=True)
    edinet_extract_parser.add_argument("--ticker")
    edinet_extract_parser.add_argument("--company")
    edinet_extract_parser.add_argument("--period-end")
    edinet_extract_parser.add_argument("--doc-type-code", default="120")
    edinet_extract_parser.add_argument("--save-text")
    edinet_extract_parser.add_argument("--preview-chars", type=int, default=800)

    rag_index_parser = subparsers.add_parser("rag-index")
    rag_index_parser.add_argument("--path", required=True)
    rag_index_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_index_parser.add_argument("--max-chars", type=int, default=800)
    rag_index_parser.add_argument("--overlap-chars", type=int, default=120)
    rag_index_parser.add_argument("--embeddings", choices=["hashing", "gemini"])

    rag_index_dir_parser = subparsers.add_parser("rag-index-dir")
    rag_index_dir_parser.add_argument("--path", required=True)
    rag_index_dir_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_index_dir_parser.add_argument("--max-chars", type=int, default=800)
    rag_index_dir_parser.add_argument("--overlap-chars", type=int, default=120)
    rag_index_dir_parser.add_argument("--embeddings", choices=["hashing", "gemini"])
    rag_index_dir_parser.add_argument(
        "--all-files",
        action="store_true",
        help="index all files regardless of front matter, not just recognized content",
    )
    rag_index_dir_parser.add_argument(
        "--no-prune",
        action="store_true",
        help="do not delete previously-indexed documents that are no longer eligible",
    )

    market_rag_parser = subparsers.add_parser(
        "market-rag-build",
        help="Render per-ticker RAG evidence notes from market CSVs and index them",
    )
    market_rag_parser.add_argument(
        "--financials-csv", default=str(DEFAULT_YAHOO_FINANCIALS_PATH)
    )
    market_rag_parser.add_argument("--daily-bars-csv", default="local_docs/market/daily_bars.csv")
    market_rag_parser.add_argument("--output-dir", default="local_docs/market/rag")
    market_rag_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    market_rag_parser.add_argument(
        "--no-index", action="store_true", help="Only write notes; skip RAG indexing"
    )
    market_rag_parser.add_argument(
        "--forecast",
        action="store_true",
        help="Embed a statistical next-horizon forecast in each note (uses daily bars)",
    )

    market_forecast_parser = subparsers.add_parser(
        "market-forecast",
        help="Forecast next-horizon closes for a ticker from daily_bars.csv",
    )
    market_forecast_parser.add_argument("--ticker", required=True)
    market_forecast_parser.add_argument(
        "--daily-bars-csv", default="local_docs/market/daily_bars.csv"
    )
    market_forecast_parser.add_argument("--horizon", type=int, default=5)
    market_forecast_parser.add_argument(
        "--no-ml", action="store_true", help="Skip scikit-learn models (classical only)"
    )
    market_forecast_parser.add_argument(
        "--no-evaluate", action="store_true", help="Skip the walk-forward RMSE backtest"
    )

    forecast_screen_parser = subparsers.add_parser(
        "market-forecast-screen",
        help="Rank all tickers in daily_bars.csv by forecast expected return",
    )
    forecast_screen_parser.add_argument(
        "--daily-bars-csv", default="local_docs/market/daily_bars.csv"
    )
    forecast_screen_parser.add_argument("--horizon", type=int, default=5)
    forecast_screen_parser.add_argument("--top", type=int, default=50)
    forecast_screen_parser.add_argument(
        "--output", default="local_docs/market/forecast_screen.csv"
    )
    forecast_screen_parser.add_argument(
        "--no-ml", action="store_true", help="Skip scikit-learn models (classical only)"
    )
    forecast_screen_parser.add_argument(
        "--max-abs-return",
        type=float,
        default=30.0,
        help="Drop forecasts whose |expected return %%| exceeds this (0 = no filter)",
    )

    daily_refresh_parser = subparsers.add_parser(
        "market-daily-refresh",
        help="One-shot daily refresh: OHLCV -> daily_bars, financials, RAG rebuild",
    )
    daily_refresh_parser.add_argument(
        "--universe-csv", default="local_docs/market/domestic_universe.csv"
    )
    daily_refresh_parser.add_argument(
        "--tickers", help="Comma-separated codes (overrides universe)"
    )
    daily_refresh_parser.add_argument("--range", default="1y")
    daily_refresh_parser.add_argument("--max", type=int, default=0, help="Cap tickers (0=all)")
    daily_refresh_parser.add_argument("--daily-bars", default="local_docs/market/daily_bars.csv")
    daily_refresh_parser.add_argument("--financials-out", default=DEFAULT_YAHOO_FINANCIALS_PATH)
    daily_refresh_parser.add_argument("--rag-dir", default="local_docs/market/rag")
    daily_refresh_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    daily_refresh_parser.add_argument(
        "--no-rag", action="store_true", help="Skip the RAG rebuild step"
    )
    daily_refresh_parser.add_argument(
        "--check",
        action="store_true",
        help="Validate config (tickers, writable paths) without fetching",
    )

    rag_stats_parser = subparsers.add_parser("rag-stats")
    rag_stats_parser.add_argument("--db-path", default=str(DEFAULT_RAG_DB_PATH))
    rag_stats_parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_RAG_STATS_KEYWORDS),
    )

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

    score_stocks_parser = subparsers.add_parser("score-stocks")
    score_stocks_parser.add_argument("--financials-csv")
    score_stocks_parser.add_argument(
        "--strategy",
        choices=("balanced", "high_yield", "defensive", "growth"),
        default="balanced",
    )
    score_stocks_parser.add_argument("--exclude-cut", action="store_true")
    score_stocks_parser.add_argument("--min-equity", type=float)
    score_stocks_parser.add_argument("--limit", type=int, default=0)


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
    if command == "demo":
        from investment_assistant.demo import run_offline_demo

        return run_offline_demo()
    if command == "market-ohlcv":
        cli_tickers = [t.strip() for t in str(args.tickers or "").split(",") if t.strip()]
        return run_market_ohlcv(
            tickers=cli_tickers or None,
            registry_path=args.registry,
            max_count=int(args.max),
            range_=args.range,
            interval=args.interval,
            output_dir=args.output_dir,
        )
    if command == "market-financials":
        financial_tickers = [
            t.strip() for t in str(args.tickers or "").split(",") if t.strip()
        ]
        return run_market_financials(
            tickers=financial_tickers or None,
            registry_path=args.registry,
            max_count=int(args.max),
            save=bool(args.save),
            output_path=args.output,
        )
    if command == "market-intraday":
        intraday_tickers = [t.strip() for t in str(args.tickers or "").split(",") if t.strip()]
        return run_yahoo_intraday(
            tickers=intraday_tickers or None,
            registry_path=args.registry,
            max_count=int(args.max),
            output_dir=args.output_dir,
        )
    if command == "market-inbox":
        return run_market_inbox(path=args.path)
    if command == "market-universe-build":
        from investment_assistant.portfolio.jpx_universe import build_domestic_universe_csv

        return build_domestic_universe_csv(
            args.jpx, output_path=args.output, scope=args.scope
        )
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
    if command == "source-registry-build-fetch-job":
        return run_source_registry_build_fetch_job(
            path=args.path,
            output=args.output,
        )

    if command == "fetch-job":
        return run_fetch_job(
            path=args.path,
            dry_run=args.dry_run,
            preview_chars=args.preview_chars,
        )
    if command == "edinet-documents":
        return run_edinet_documents(
            date=args.date,
            ticker=args.ticker,
            financial_only=not args.all_doc_types,
        )
    if command == "storage-prune":
        return run_storage_prune(
            docs_dirs=args.docs_dirs,
            keep_per_dir=args.keep_per_dir,
            http_max_rows=args.http_max_rows,
            prune_cache=not args.no_cache,
        )
    if command == "knowledge-diff":
        from investment_assistant import knowledge
        from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV

        return knowledge.run_knowledge_diff(
            db_path=args.db_path,
            financials_csv=args.financials_csv or DEFAULT_FINANCIALS_CSV,
            snapshot_path=args.snapshot_path or knowledge.DEFAULT_SNAPSHOT_PATH,
            save=not args.no_save,
        )
    if command == "crawl":
        return run_crawl(
            path=args.path,
            output_dir=args.output_dir,
            db_path=args.db_path,
            max_pages=args.max_pages,
            dry_run=args.dry_run,
            index_after=not args.no_index,
        )
    if command == "edinet-ingest":
        return run_edinet_ingest(
            registry_path=args.registry_path,
            end_date=args.end_date,
            days=args.days,
            start_date=args.start_date,
            years=args.years,
            output_dir=args.output_dir,
            db_path=args.db_path,
            index_after=not args.no_index,
            max_periods=args.max_periods,
        )
    if command == "edinet-extract":
        return run_edinet_extract(
            zip_path=args.zip_path,
            doc_id=args.doc_id,
            ticker=args.ticker,
            company=args.company,
            period_end=args.period_end,
            doc_type_code=args.doc_type_code,
            save_text=args.save_text,
            preview_chars=args.preview_chars,
        )
    if command == "rag-index":
        return run_rag_index(
            path=args.path,
            db_path=args.db_path,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
            embeddings=args.embeddings,
        )
    if command == "rag-index-dir":
        return run_rag_index_dir(
            path=args.path,
            db_path=args.db_path,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
            embeddings=args.embeddings,
            content_only=not args.all_files,
            prune=not args.no_prune,
        )
    if command == "market-daily-refresh":
        if args.tickers:
            tickers = [t.strip() for t in str(args.tickers).split(",") if t.strip()]
        elif Path(args.universe_csv).is_file():
            from investment_assistant.portfolio.jpx_universe import (
                load_domestic_universe_tickers,
            )

            tickers = load_domestic_universe_tickers(args.universe_csv)
        else:
            tickers = []
        if args.check:
            return check_daily_refresh_readiness(
                tickers=tickers,
                daily_bars_path=args.daily_bars,
                financials_path=args.financials_out,
                rag_dir=args.rag_dir,
                build_rag=not args.no_rag,
            )
        if not tickers:
            print(
                "no tickers: provide --tickers or build the universe first "
                "(market-universe-build)"
            )
            return 2
        return run_market_daily_refresh(
            tickers=tickers,
            range_=args.range,
            max_count=int(args.max),
            daily_bars_path=args.daily_bars,
            financials_path=args.financials_out,
            rag_dir=args.rag_dir,
            rag_db_path=args.db_path,
            build_rag=not args.no_rag,
        )
    if command == "market-rag-build":
        from investment_assistant.portfolio.market_rag import build_market_evidence_docs

        daily_bars = args.daily_bars_csv if Path(args.daily_bars_csv).is_file() else None
        result = build_market_evidence_docs(
            financials_csv=args.financials_csv,
            output_dir=args.output_dir,
            daily_bars_csv=daily_bars,
            include_forecast=bool(args.forecast),
        )
        if not args.no_index and result["documents_written"]:
            result["index"] = run_rag_index_dir(path=args.output_dir, db_path=args.db_path)
        return result
    if command == "market-forecast":
        from investment_assistant.portfolio.market_forecast import forecast_ticker

        return forecast_ticker(
            daily_bars_csv=args.daily_bars_csv,
            ticker=args.ticker,
            horizon=args.horizon,
            include_ml=not args.no_ml,
            evaluate=not args.no_evaluate,
        )
    if command == "market-forecast-screen":
        from investment_assistant.portfolio._market_common import render_csv
        from investment_assistant.portfolio.market_forecast import screen_by_forecast

        ranked = screen_by_forecast(
            args.daily_bars_csv,
            horizon=args.horizon,
            include_ml=not args.no_ml,
            top=args.top,
            max_abs_return_pct=args.max_abs_return,
        )
        columns = (
            "ticker",
            "last_close",
            "forecast_close",
            "expected_return_pct",
            "horizon",
            "backtest_best_model",
            "backtest_rmse",
            "rmse_pct",
            "observations",
        )
        output_path = reject_path_traversal(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_csv(columns, ranked), encoding="utf-8-sig")
        return {
            "ranked_count": len(ranked),
            "top": args.top,
            "horizon": args.horizon,
            "output_path": str(output_path),
            "top_results": ranked[:10],
            "auto_trading": False,
            "call_real_api": False,
        }
    if command == "rag-stats":
        keywords = tuple(
            keyword.strip()
            for keyword in str(args.keywords).split(",")
            if keyword.strip()
        )
        return run_rag_stats(db_path=args.db_path, keywords=keywords)

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
    if command == "score-stocks":
        from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
        from investment_assistant.scoring.stock import run_stock_scoring

        return run_stock_scoring(
            financials_csv=args.financials_csv or DEFAULT_FINANCIALS_CSV,
            strategy=args.strategy,
            exclude_dividend_cut=args.exclude_cut,
            min_equity_ratio=args.min_equity,
            limit=args.limit or None,
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
