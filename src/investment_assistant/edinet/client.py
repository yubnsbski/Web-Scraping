"""EDINET API v2 client.

Thin, testable wrapper over the documents list and document acquisition
endpoints. Network access is delegated to an injected
:class:`~investment_assistant.ingestion.transport.HttpTransport`, so the client
can be exercised entirely offline with a fake transport (the project's standard
pattern). EDINET API v2 requires a subscription key, read from the
``EDINET_API_KEY`` environment variable; it is sent as a query parameter and
never logged.

Compliance posture: EDINET is official public disclosure. This client only
reads published filings, identifies itself with a contactable User-Agent, and
leaves rate limiting / scheduling to the caller. Retrieved data is for local
RAG grounding, not redistribution.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode

from investment_assistant.edinet.models import (
    ACQUISITION_CSV,
    EDINET_API_BASE,
    EdinetDocument,
    parse_documents,
)
from investment_assistant.ingestion.rate_limit import DomainRateLimiter
from investment_assistant.ingestion.transport import (
    HttpResponse,
    HttpTransport,
    UrlLibHttpTransport,
)
from investment_assistant.observability import get_logger

_logger = get_logger("edinet.client")

API_KEY_ENV_VAR = "EDINET_API_KEY"
DEFAULT_USER_AGENT = "investment-assistant/0.1 (+edinet-reader; contact: local-user)"
# Be polite to the shared public API: space requests to the same host so a large
# registry (close to the full Nikkei 225) stays well within EDINET's limits.
DEFAULT_MIN_INTERVAL_SECONDS = 0.5


class EdinetApiError(RuntimeError):
    """Raised when EDINET returns an error status for a request."""


class EdinetClient:
    """Read EDINET document metadata and acquire document archives."""

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        api_key: str | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = 30.0,
        api_base: str = EDINET_API_BASE,
        rate_limiter: DomainRateLimiter | None = None,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    ) -> None:
        self.transport = transport or UrlLibHttpTransport()
        self.api_key = api_key if api_key is not None else os.getenv(API_KEY_ENV_VAR, "").strip()
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.api_base = api_base.rstrip("/")
        self.rate_limiter = rate_limiter or DomainRateLimiter(
            min_interval_seconds=min_interval_seconds
        )

    def _get(self, url: str) -> HttpResponse:
        """Fetch ``url`` after honoring the per-host rate limit."""

        self.rate_limiter.wait_for_url(url)
        return self.transport.get(
            url,
            timeout_seconds=self.timeout_seconds,
            user_agent=self.user_agent,
        )

    def documents_url(self, date: str, *, doc_type: int = 2) -> str:
        """Build the documents.json URL for a submission ``date`` (YYYY-MM-DD)."""

        query = self._query({"date": date, "type": str(doc_type)})
        return f"{self.api_base}/documents.json?{query}"

    def document_url(self, doc_id: str, *, acquisition_type: int = ACQUISITION_CSV) -> str:
        """Build the document acquisition URL for ``doc_id``."""

        query = self._query({"type": str(acquisition_type)})
        return f"{self.api_base}/documents/{doc_id}?{query}"

    def list_documents(self, date: str) -> list[EdinetDocument]:
        """Fetch and parse the list of documents submitted on ``date``."""

        url = self.documents_url(date)
        response = self._get(url)
        if response.status_code >= 400:
            raise EdinetApiError(f"EDINET documents request failed: status={response.status_code}")
        payload = json.loads(response.body.decode("utf-8", errors="replace"))
        self._raise_for_api_error(payload, context="documents")
        documents = parse_documents(payload)
        _logger.info("edinet documents date=%s count=%d", date, len(documents))
        return documents

    def download_document(
        self,
        doc_id: str,
        *,
        acquisition_type: int = ACQUISITION_CSV,
    ) -> bytes:
        """Download a document archive (CSV/XBRL/PDF) as raw bytes."""

        url = self.document_url(doc_id, acquisition_type=acquisition_type)
        response = self._get(url)
        if response.status_code >= 400:
            raise EdinetApiError(
                f"EDINET document download failed: doc_id={doc_id} status={response.status_code}"
            )
        _logger.info(
            "edinet download doc_id=%s type=%d bytes=%d",
            doc_id,
            acquisition_type,
            len(response.body),
        )
        return response.body

    def _raise_for_api_error(self, payload: object, *, context: str) -> None:
        if not isinstance(payload, dict):
            return

        status_code = payload.get("StatusCode")
        message = payload.get("message") or payload.get("Message")

        if status_code is None:
            return

        raise EdinetApiError(
            f"EDINET {context} request failed: api_status={status_code} message={message}"
        )

    def _query(self, params: dict[str, str]) -> str:
        if self.api_key:
            params = {**params, "Subscription-Key": self.api_key}
        return urlencode(params)
