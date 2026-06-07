"""EDINET (金融庁) document metadata models and selection helpers.

EDINET is the official disclosure system. There is a single public API keyed by
securities/EDINET code that covers every listed company (so every Nikkei 225
name is reachable) — companies do not each expose a private API. This module
models the document-list metadata and provides offline, network-free selection
helpers (filter by ticker / document type, pick the latest filing).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"

# docTypeCode values (subset relevant to financial disclosure).
DOC_TYPE_ANNUAL_REPORT = "120"  # 有価証券報告書
DOC_TYPE_AMENDED_ANNUAL_REPORT = "130"  # 訂正有価証券報告書
DOC_TYPE_QUARTERLY_REPORT = "140"  # 四半期報告書
DOC_TYPE_SEMIANNUAL_REPORT = "160"  # 半期報告書
DOC_TYPE_EXTRAORDINARY_REPORT = "180"  # 臨時報告書

DOC_TYPE_LABELS: dict[str, str] = {
    DOC_TYPE_ANNUAL_REPORT: "有価証券報告書",
    DOC_TYPE_AMENDED_ANNUAL_REPORT: "訂正有価証券報告書",
    DOC_TYPE_QUARTERLY_REPORT: "四半期報告書",
    DOC_TYPE_SEMIANNUAL_REPORT: "半期報告書",
    DOC_TYPE_EXTRAORDINARY_REPORT: "臨時報告書",
}

# Document types that carry the financial statements we care about.
FINANCIAL_DOC_TYPES: frozenset[str] = frozenset(
    {
        DOC_TYPE_ANNUAL_REPORT,
        DOC_TYPE_QUARTERLY_REPORT,
        DOC_TYPE_SEMIANNUAL_REPORT,
    }
)

# Document acquisition "type" query parameter for the documents/{docID} endpoint.
ACQUISITION_XBRL = 1
ACQUISITION_PDF = 2
ACQUISITION_CSV = 5


def securities_code(ticker: str) -> str:
    """Convert a 4-digit ticker to EDINET's 5-digit securities code.

    EDINET ``secCode`` is the 4-digit ticker followed by a trailing ``0``
    (e.g. ``8306`` -> ``83060``). Non-standard inputs are returned upper-cased
    and stripped so the caller can still match exotic codes verbatim.
    """

    cleaned = ticker.strip().upper()
    if len(cleaned) == 4 and cleaned.isdigit():
        return f"{cleaned}0"
    return cleaned


@dataclass(frozen=True)
class EdinetDocument:
    """One row of EDINET's documents.json metadata."""

    doc_id: str
    edinet_code: str | None
    sec_code: str | None
    filer_name: str
    doc_type_code: str | None
    doc_description: str
    period_start: str | None
    period_end: str | None
    submit_datetime: str | None
    has_xbrl: bool
    has_csv: bool
    has_pdf: bool

    @property
    def ticker(self) -> str | None:
        """Return the 4-digit ticker derived from ``sec_code`` if available."""

        if self.sec_code and len(self.sec_code) == 5 and self.sec_code.isdigit():
            return self.sec_code[:4]
        return None

    @property
    def doc_type_label(self) -> str:
        return DOC_TYPE_LABELS.get(self.doc_type_code or "", self.doc_type_code or "unknown")

    @property
    def sort_key(self) -> tuple[str, str]:
        """Stable ordering key: submit time first, then period end."""

        return (self.submit_datetime or "", self.period_end or "")


def parse_documents(payload: object) -> list[EdinetDocument]:
    """Parse the EDINET documents.json payload into typed records.

    Tolerates missing/None fields; only ``docID`` is required for a row to be
    kept, since a document without an id cannot be retrieved.
    """

    if not isinstance(payload, dict):
        raise ValueError("EDINET documents payload must be a JSON object")
    results = payload.get("results")
    if not isinstance(results, list):
        return []

    documents: list[EdinetDocument] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        doc_id = _str_or_none(row.get("docID"))
        if not doc_id:
            continue
        documents.append(
            EdinetDocument(
                doc_id=doc_id,
                edinet_code=_str_or_none(row.get("edinetCode")),
                sec_code=_str_or_none(row.get("secCode")),
                filer_name=_str_or_none(row.get("filerName")) or "",
                doc_type_code=_str_or_none(row.get("docTypeCode")),
                doc_description=_str_or_none(row.get("docDescription")) or "",
                period_start=_str_or_none(row.get("periodStart")),
                period_end=_str_or_none(row.get("periodEnd")),
                submit_datetime=_str_or_none(row.get("submitDateTime")),
                has_xbrl=_flag(row.get("xbrlFlag")),
                has_csv=_flag(row.get("csvFlag")),
                has_pdf=_flag(row.get("pdfFlag")),
            )
        )
    return documents


def filter_by_ticker(
    documents: Iterable[EdinetDocument],
    ticker: str,
) -> list[EdinetDocument]:
    """Keep documents whose securities code matches ``ticker``."""

    target = securities_code(ticker)
    return [doc for doc in documents if doc.sec_code == target]


def filter_by_doc_types(
    documents: Iterable[EdinetDocument],
    doc_types: Iterable[str] = FINANCIAL_DOC_TYPES,
) -> list[EdinetDocument]:
    """Keep documents whose ``doc_type_code`` is in ``doc_types``."""

    allowed = frozenset(doc_types)
    return [doc for doc in documents if (doc.doc_type_code or "") in allowed]


def latest_document(documents: Iterable[EdinetDocument]) -> EdinetDocument | None:
    """Return the most recently submitted document, or ``None`` if empty."""

    ordered = sorted(documents, key=lambda doc: doc.sort_key)
    return ordered[-1] if ordered else None


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _flag(value: object) -> bool:
    return str(value).strip() == "1"
