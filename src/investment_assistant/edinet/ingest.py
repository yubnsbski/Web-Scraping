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

from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from investment_assistant.edinet.client import EdinetApiError, EdinetClient
from investment_assistant.edinet.csv_extract import (
    parse_csv_archive,
    select_metrics,
    to_rag_text,
)
from investment_assistant.edinet.models import (
    ACQUISITION_CSV,
    EdinetDocument,
    filter_by_doc_types,
    filter_by_ticker,
    latest_document,
)
from investment_assistant.edinet.registry import EdinetTarget
from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.observability import get_logger

_logger = get_logger("edinet.ingest")


def recent_dates(end_date: str, days: int) -> list[str]:
    """Return ``days`` submission dates ending at ``end_date`` (most recent first)."""

    end = date.fromisoformat(end_date)
    span = max(1, days)
    return [(end - timedelta(days=offset)).isoformat() for offset in range(span)]


def ingest_targets(
    *,
    client: EdinetClient,
    targets: Sequence[EdinetTarget],
    dates: Sequence[str],
    output_dir: str | Path,
) -> dict[str, object]:
    """Download and extract the latest financial filing for each target.

    Scans ``dates`` once, then for each target picks the most recent matching
    document, downloads its CSV archive, extracts the target metrics, and writes
    a RAG-ready text file under ``output_dir/<ticker>/<doc_id>.txt``.
    """

    base_dir = reject_path_traversal(output_dir)
    documents, scanned_dates = _collect_documents(client, dates)

    results: list[dict[str, object]] = []
    ingested = 0
    for target in targets:
        candidates = filter_by_doc_types(
            filter_by_ticker(documents, target.ticker),
            target.doc_types,
        )
        document = latest_document(candidates)
        if document is None:
            results.append(_status(target, "no_document"))
            continue
        if not document.has_csv:
            results.append(_status(target, "no_csv", doc_id=document.doc_id))
            continue

        try:
            archive = client.download_document(document.doc_id, acquisition_type=ACQUISITION_CSV)
        except (OSError, EdinetApiError) as exc:
            _logger.warning("edinet download failed doc_id=%s error=%s", document.doc_id, exc)
            results.append(_status(target, "download_failed", doc_id=document.doc_id))
            continue

        values = parse_csv_archive(archive)
        text = to_rag_text(document, values, company=target.company)
        out_path = base_dir / target.ticker / f"{document.doc_id}.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        ingested += 1
        results.append(
            {
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
        )

    return {
        "output_dir": str(base_dir),
        "scanned_dates": scanned_dates,
        "documents_seen": len(documents),
        "targets_count": len(targets),
        "ingested_count": ingested,
        "results": results,
    }


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
