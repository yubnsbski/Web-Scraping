"""EDINET (金融庁) public-API connector.

Provides the structured financial numbers the RAG store is missing (営業CF /
自己資本比率 / 配当性向) by reading official filings through the EDINET API and
rendering them as RAG-ingestable text. All network access is delegated to an
injectable transport, so the connector is fully testable offline.
"""

from investment_assistant.edinet.client import (
    API_KEY_ENV_VAR,
    EdinetApiError,
    EdinetClient,
)
from investment_assistant.edinet.csv_extract import (
    DEFAULT_METRIC_KEYWORDS,
    FinancialValue,
    parse_csv_archive,
    select_metrics,
    to_rag_text,
)
from investment_assistant.edinet.ingest import ingest_targets, recent_dates
from investment_assistant.edinet.models import (
    ACQUISITION_CSV,
    ACQUISITION_PDF,
    ACQUISITION_XBRL,
    FINANCIAL_DOC_TYPES,
    EdinetDocument,
    filter_by_doc_types,
    filter_by_ticker,
    latest_document,
    parse_documents,
    securities_code,
)
from investment_assistant.edinet.registry import (
    EdinetTarget,
    build_edinet_targets_from_registry,
)

__all__ = [
    "ACQUISITION_CSV",
    "ACQUISITION_PDF",
    "ACQUISITION_XBRL",
    "API_KEY_ENV_VAR",
    "DEFAULT_METRIC_KEYWORDS",
    "FINANCIAL_DOC_TYPES",
    "EdinetApiError",
    "EdinetClient",
    "EdinetDocument",
    "EdinetTarget",
    "FinancialValue",
    "build_edinet_targets_from_registry",
    "ingest_targets",
    "recent_dates",
    "filter_by_doc_types",
    "filter_by_ticker",
    "latest_document",
    "parse_csv_archive",
    "parse_documents",
    "securities_code",
    "select_metrics",
    "to_rag_text",
]
