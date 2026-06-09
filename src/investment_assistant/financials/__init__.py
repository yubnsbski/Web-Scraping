"""Cross-company financial comparison (non-advisory)."""

from investment_assistant.financials.evidence import (
    build_financial_evidence,
    dividend_evidence_text,
    ticker_from_source,
)
from investment_assistant.financials.loader import (
    DISCLAIMER,
    compare_financials,
    load_financials,
)
from investment_assistant.financials.models import (
    FINANCIAL_COLUMNS,
    FinancialPoint,
)

__all__ = [
    "DISCLAIMER",
    "FINANCIAL_COLUMNS",
    "FinancialPoint",
    "build_financial_evidence",
    "compare_financials",
    "dividend_evidence_text",
    "load_financials",
    "ticker_from_source",
]
