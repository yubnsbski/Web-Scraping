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
import os
from collections.abc import Sequence
from dataclasses import replace
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
    summary_dividend_by_year,
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
    # Per-ticker split-adjusted dividend maps from each run's newest filing, kept
    # so the correction also reaches fiscal years that survive only in durable
    # history (their filing files pruned) at merge time.
    corrections: dict[str, dict[int, float]] = {}
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

        target_points: list[FinancialPoint] = []
        newest_dividends: dict[int, float] = {}
        newest_period = ""
        for document in selected:
            record, point, dividends = _ingest_document(client, target, document, base_dir)
            status = record["status"]
            if status == "ingested":
                ingested += 1
            elif status == "cached":
                cached += 1
            if point is not None:
                target_points.append(point)
            period = document.period_end or ""
            if dividends and period > newest_period:
                newest_dividends = dividends
                newest_period = period
            results.append(record)

        # The newest filing's 5-year summary table is split-adjusted; use it to
        # correct the per-share dividend on every point for this ticker so a stock
        # split cannot leave a spurious cut/jump in the series.
        if newest_dividends:
            target_points = [_apply_dividend_correction(p, newest_dividends) for p in target_points]
            corrections[target.ticker] = newest_dividends
        points.extend(target_points)

    deduped = dedupe_points(points)
    # Merge with the durable history so pruning bulky filing files never loses
    # the (tiny) dividend record. This run's points win on overlap; the split-
    # adjusted correction is also applied to history-only years so a pruned
    # pre-split value can't survive next to corrected post-split ones.
    csv_path = base_dir / FINANCIALS_CSV_NAME
    existing = [
        _apply_dividend_correction(p, corrections.get(p.ticker, {}))
        for p in _load_existing_points(csv_path)
    ]
    merged = dedupe_points([*deduped, *existing])
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


def _apply_dividend_correction(
    point: FinancialPoint, dividends: dict[int, float]
) -> FinancialPoint:
    """Override a point's dividend with the split-adjusted summary-table value."""

    corrected = dividends.get(point.fiscal_year)
    if corrected is None or corrected == point.dividend_per_share:
        return point
    return replace(point, dividend_per_share=corrected)


def _load_existing_points(csv_path: Path) -> list[FinancialPoint]:
    if not csv_path.is_file():
        return []
    try:
        return load_financials(csv_path)
    except (ValueError, OSError):
        return []


EDINET_DOC_URL_TEMPLATE_ENV = "EDINET_DOC_URL_TEMPLATE"


def _edinet_front_matter(document: EdinetDocument, ticker: str) -> str:
    """Build YAML front matter (provenance + an opt-in viewer URL).

    EDINET has no public, key-less per-document URL — document acquisition goes
    through the API and requires the Subscription-Key, which must not be embedded
    in saved files. So ``source_url`` is written only when the operator opts in
    via the ``EDINET_DOC_URL_TEMPLATE`` env (a ``{doc_id}`` template they have
    verified), keeping provenance accurate without fabricating links.
    """

    lines = ["---", f"edinet_doc_id: {document.doc_id}"]
    if ticker:
        lines.append(f"ticker: {ticker}")
    if document.period_end:
        lines.append(f"period_end: {document.period_end}")
    template = os.getenv(EDINET_DOC_URL_TEMPLATE_ENV, "").strip()
    if template and "{doc_id}" in template:
        lines.append(f"source_url: {template.replace('{doc_id}', document.doc_id)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _ingest_document(
    client: EdinetClient,
    target: EdinetTarget,
    document: EdinetDocument,
    base_dir: Path,
) -> tuple[dict[str, object], FinancialPoint | None, dict[int, float]]:
    if not document.has_csv:
        return _status(target, "no_csv", doc_id=document.doc_id), None, {}

    out_path = base_dir / target.ticker / f"{document.doc_id}.txt"
    sidecar = out_path.with_name(f"{document.doc_id}.points.json")
    if out_path.exists():
        record = _status(target, "cached", doc_id=document.doc_id)
        record["saved_path"] = str(out_path)
        record["period_end"] = document.period_end
        point, dividends = _read_sidecar(sidecar)
        return record, point, dividends

    try:
        archive = client.download_document(document.doc_id, acquisition_type=ACQUISITION_CSV)
    except (OSError, EdinetApiError) as exc:
        _logger.warning("edinet download failed doc_id=%s error=%s", document.doc_id, exc)
        return _status(target, "download_failed", doc_id=document.doc_id), None, {}

    values = parse_csv_archive(archive)
    text = _edinet_front_matter(document, target.ticker) + to_rag_text(
        document, values, company=target.company
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    point = build_financial_point(document, values, ticker=target.ticker, company=target.company)
    dividends = summary_dividend_by_year(document, values)
    if point is not None:
        sidecar.write_text(
            json.dumps(_sidecar_payload(point, dividends), ensure_ascii=False),
            encoding="utf-8",
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
    return record, point, dividends


def _sidecar_payload(point: FinancialPoint, dividends: dict[int, float]) -> dict[str, object]:
    payload: dict[str, object] = {"point": point_to_row(point)}
    if dividends:
        payload["dividend_by_year"] = {str(year): value for year, value in dividends.items()}
    return payload


def _read_sidecar(sidecar: Path) -> tuple[FinancialPoint | None, dict[int, float]]:
    """Read a point and its split-adjusted dividend map (legacy bare-row aware)."""

    if not sidecar.is_file():
        return None, {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, {}
    if not isinstance(data, dict):
        return None, {}
    # New format: {"point": {...}, "dividend_by_year": {...}}.
    if "point" in data and isinstance(data["point"], dict):
        point = point_from_mapping(data["point"])
        dividends: dict[int, float] = {}
        raw = data.get("dividend_by_year")
        if isinstance(raw, dict):
            for key, value in raw.items():
                year = _to_int(key)
                number = _to_number(value)
                if year is not None and number is not None:
                    dividends[year] = number
        return point, dividends
    # Legacy format: a bare CSV-row mapping.
    return point_from_mapping(data), {}


def _to_int(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _to_number(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


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
