"""End-to-end EDINET ingestion: list → select → download → extract → save.

Orchestrates the pieces in this package into a single pass that turns approved
registry targets into RAG-ready text files. Network access is confined to the
injected :class:`EdinetClient`, so the orchestration is fully testable offline
with a fake client. RAG indexing is intentionally left to the caller (the CLI /
web handler indexes the output directory afterward), mirroring the existing
fetch-job/auto flow.

Robustness: a failure on one submission date or one download is logged and
skipped so a single bad response never aborts the whole run.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from investment_assistant.edinet.client import EdinetApiError, EdinetClient
from investment_assistant.edinet.csv_extract import (
    parse_csv_archive,
    select_metrics,
    to_rag_text,
)
from investment_assistant.edinet.financials_bridge import (
    build_financial_point,
    dedupe_points,
    point_from_mapping,
    point_to_row,
    write_financials_csv,
)
from investment_assistant.edinet.models import (
    ACQUISITION_CSV,
    EdinetDocument,
    filter_by_doc_types,
    filter_by_ticker,
    select_recent_documents,
)
from investment_assistant.edinet.registry import EdinetTarget
from investment_assistant.financials import compare_financials, load_financials
from investment_assistant.financials.models import FinancialPoint
from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.observability import get_logger

_logger = get_logger("edinet.ingest")

FINANCIALS_CSV_NAME = "financials.csv"

# Safety ceiling so a multi-year backfill cannot scan an unbounded number of
# submission dates (each is one API call). ~900 business days ≈ 3.6 years.
DEFAULT_MAX_SCAN_DAYS = 900


def recent_dates(end_date: str, days: int) -> list[str]:
    """Return ``days`` submission dates ending at ``end_date`` (most recent first)."""

    end = date.fromisoformat(end_date)
    span = max(1, days)
    return [(end - timedelta(days=offset)).isoformat() for offset in range(span)]


def date_range(
    start_date: str,
    end_date: str,
    *,
    skip_weekends: bool = True,
    max_days: int = DEFAULT_MAX_SCAN_DAYS,
) -> list[str]:
    """Return submission dates between ``start_date`` and ``end_date``.

    Most recent first. Weekends are skipped by default (EDINET does not accept
    filings then), and the result is capped at ``max_days`` to keep a backfill
    from issuing an unbounded number of API calls — the most recent dates are
    kept when the range is larger than the cap.
    """

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        start, end = end, start

    dates: list[str] = []
    current = end
    while current >= start and len(dates) < max(1, max_days):
        if not (skip_weekends and current.weekday() >= 5):
            dates.append(current.isoformat())
        current -= timedelta(days=1)
    return dates


def ingest_targets(
    *,
    client: EdinetClient,
    targets: Sequence[EdinetTarget],
    dates: Sequence[str],
    output_dir: str | Path,
    max_periods_override: int | None = None,
) -> dict[str, object]:
    """Download and extract recent financial filings for each target.

    Scans ``dates`` once, then for each target selects up to ``max_periods``
    most-recent matching documents (annual and/or quarterly), downloads each CSV
    archive, extracts the target metrics, and writes a RAG-ready text file under
    ``output_dir/<ticker>/<doc_id>.txt``. A document already saved on disk is
    skipped (status ``cached``) so repeated/weekly runs accumulate history
    without re-downloading.
    """

    base_dir = reject_path_traversal(output_dir)
    documents, scanned_dates = _collect_documents(client, dates)

    results: list[dict[str, object]] = []
    points: list[FinancialPoint] = []
    ingested = 0
    cached = 0
    for target in targets:
        candidates = filter_by_doc_types(
            filter_by_ticker(documents, target.ticker),
            target.doc_types,
        )
        limit = max_periods_override if max_periods_override is not None else target.max_periods
        selected = select_recent_documents(candidates, limit)
        if not selected:
            results.append(_status(target, "no_document"))
            continue

        for document in selected:
            record, point = _ingest_document(client, target, document, base_dir)
            status = record["status"]
            if status == "ingested":
                ingested += 1
            elif status == "cached":
                cached += 1
            if point is not None:
                points.append(point)
            results.append(record)

    deduped = dedupe_points(points)
    # Merge with the durable history so pruning bulky filing files never loses
    # the (tiny) dividend record. This run's points win on overlap.
    csv_path = base_dir / FINANCIALS_CSV_NAME
    merged = dedupe_points([*deduped, *_load_existing_points(csv_path)])
    summary: dict[str, object] = {
        "output_dir": str(base_dir),
        "scanned_dates": scanned_dates,
        "documents_seen": len(documents),
        "targets_count": len(targets),
        "ingested_count": ingested,
        "cached_count": cached,
        "financial_points": len(deduped),
        "financial_points_total": len(merged),
        "results": results,
    }
    if merged:
        summary["financials_csv"] = write_financials_csv(merged, csv_path)
        summary["comparison"] = compare_financials(merged)
    return summary


def _load_existing_points(csv_path: Path) -> list[FinancialPoint]:
    if not csv_path.is_file():
        return []
    try:
        return load_financials(csv_path)
    except (ValueError, OSError):
        return []


def _ingest_document(
    client: EdinetClient,
    target: EdinetTarget,
    document: EdinetDocument,
    base_dir: Path,
) -> tuple[dict[str, object], FinancialPoint | None]:
    if not document.has_csv:
        return _status(target, "no_csv", doc_id=document.doc_id), None

    out_path = base_dir / target.ticker / f"{document.doc_id}.txt"
    sidecar = out_path.with_name(f"{document.doc_id}.points.json")
    if out_path.exists():
        record = _status(target, "cached", doc_id=document.doc_id)
        record["saved_path"] = str(out_path)
        record["period_end"] = document.period_end
        return record, _read_sidecar_point(sidecar)

    try:
        archive = client.download_document(document.doc_id, acquisition_type=ACQUISITION_CSV)
    except (OSError, EdinetApiError) as exc:
        _logger.warning("edinet download failed doc_id=%s error=%s", document.doc_id, exc)
        return _status(target, "download_failed", doc_id=document.doc_id), None

    values = parse_csv_archive(archive)
    text = to_rag_text(document, values, company=target.company)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    point = build_financial_point(document, values, ticker=target.ticker, company=target.company)
    if point is not None:
        sidecar.write_text(
            json.dumps(point_to_row(point), ensure_ascii=False), encoding="utf-8"
        )

    record = {
        "name": target.name,
        "ticker": target.ticker,
        "status": "ingested",
        "doc_id": document.doc_id,
        "doc_type": document.doc_type_label,
        "period_end": document.period_end,
        "saved_path": str(out_path),
        "values_extracted": len(values),
        "metrics": sorted(select_metrics(values).keys()),
    }
    return record, point


def _read_sidecar_point(sidecar: Path) -> FinancialPoint | None:
    if not sidecar.is_file():
        return None
    try:
        row = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(row, dict):
        return None
    return point_from_mapping(row)


def _collect_documents(
    client: EdinetClient,
    dates: Sequence[str],
) -> tuple[list[EdinetDocument], list[str]]:
    documents: list[EdinetDocument] = []
    scanned: list[str] = []
    for day in dates:
        try:
            documents.extend(client.list_documents(day))
            scanned.append(day)
        except (OSError, EdinetApiError) as exc:
            _logger.warning("edinet list failed date=%s error=%s", day, exc)
    return documents, scanned


def _status(target: EdinetTarget, status: str, *, doc_id: str | None = None) -> dict[str, object]:
    record: dict[str, object] = {
        "name": target.name,
        "ticker": target.ticker,
        "status": status,
    }
    if doc_id is not None:
        record["doc_id"] = doc_id
    return record
