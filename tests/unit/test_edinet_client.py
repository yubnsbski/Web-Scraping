from __future__ import annotations

import json

import pytest

from investment_assistant.edinet.client import EdinetApiError, EdinetClient
from investment_assistant.ingestion.rate_limit import DomainRateLimiter
from investment_assistant.ingestion.transport import HttpResponse


class _FakeTransport:
    """Records the requested URL and returns a canned response."""

    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requested_url: str | None = None
        self.user_agent: str | None = None

    def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
        self.requested_url = url
        self.user_agent = user_agent
        return self.response


def _json_response(payload: dict[str, object], status: int = 200) -> HttpResponse:
    return HttpResponse(
        url="https://api.edinet-fsa.go.jp/api/v2/documents.json",
        status_code=status,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


def test_documents_url_includes_date_and_key() -> None:
    client = EdinetClient(transport=_FakeTransport(_json_response({})), api_key="secret-key")
    url = client.documents_url("2024-06-21")
    assert "date=2024-06-21" in url
    assert "type=2" in url
    assert "Subscription-Key=secret-key" in url


def test_documents_url_omits_key_when_absent() -> None:
    client = EdinetClient(transport=_FakeTransport(_json_response({})), api_key="")
    assert "Subscription-Key" not in client.documents_url("2024-06-21")


def test_list_documents_parses_results() -> None:
    payload = {
        "results": [
            {
                "docID": "S100AAA1",
                "secCode": "83060",
                "filerName": "三菱UFJ",
                "docTypeCode": "120",
                "docDescription": "有価証券報告書",
                "periodEnd": "2024-03-31",
                "submitDateTime": "2024-06-21 09:00",
                "csvFlag": "1",
            }
        ]
    }
    transport = _FakeTransport(_json_response(payload))
    client = EdinetClient(transport=transport, api_key="k")

    documents = client.list_documents("2024-06-21")

    assert transport.requested_url is not None
    assert "documents.json" in transport.requested_url
    assert len(documents) == 1
    assert documents[0].doc_id == "S100AAA1"
    assert documents[0].ticker == "8306"


def test_list_documents_raises_on_error_status() -> None:
    transport = _FakeTransport(_json_response({}, status=403))
    client = EdinetClient(transport=transport, api_key="k")
    with pytest.raises(EdinetApiError, match="status=403"):
        client.list_documents("2024-06-21")


def test_download_document_returns_bytes_and_builds_url() -> None:
    archive = b"PK\x03\x04 fake-zip-bytes"
    transport = _FakeTransport(
        HttpResponse(
            url="https://api.edinet-fsa.go.jp/api/v2/documents/S100AAA1",
            status_code=200,
            headers={"content-type": "application/octet-stream"},
            body=archive,
        )
    )
    client = EdinetClient(transport=transport, api_key="k")

    data = client.download_document("S100AAA1")

    assert data == archive
    assert transport.requested_url is not None
    assert "documents/S100AAA1" in transport.requested_url
    assert "type=5" in transport.requested_url


def test_download_document_raises_on_error_status() -> None:
    transport = _FakeTransport(
        HttpResponse(url="x", status_code=404, headers={}, body=b"")
    )
    client = EdinetClient(transport=transport, api_key="k")
    with pytest.raises(EdinetApiError, match="status=404"):
        client.download_document("S100MISSING")


def test_client_rate_limits_requests_to_same_host() -> None:
    waits: list[float] = []
    ticks = iter([0.0, 0.0, 0.0])  # first wait, then two clock reads
    limiter = DomainRateLimiter(
        min_interval_seconds=0.5,
        clock=lambda: next(ticks, 0.0),
        sleeper=waits.append,
    )
    client = EdinetClient(
        transport=_FakeTransport(_json_response({"results": []})),
        api_key="k",
        rate_limiter=limiter,
    )

    # First call has no prior timestamp -> no wait; second must be spaced.
    client.list_documents("2024-06-21")
    client.list_documents("2024-06-22")

    assert waits == [0.5]



def test_list_documents_raises_on_api_error_payload() -> None:
    from investment_assistant.edinet.client import EdinetApiError, EdinetClient
    from investment_assistant.ingestion.transport import HttpResponse

    class FakeTransport:
        def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
            _ = url, timeout_seconds, user_agent
            return HttpResponse(
                url="https://api.edinet-fsa.go.jp/api/v2/documents.json",
                status_code=200,
                body=(
                    b'{"StatusCode":401,'
                    b'"message":"Access denied due to invalid subscription key."}'
                ),
                headers={},
            )

    client = EdinetClient(transport=FakeTransport(), api_key="invalid")

    try:
        client.list_documents("2026-06-05")
    except EdinetApiError as exc:
        assert "api_status=401" in str(exc)
        assert "invalid subscription key" in str(exc)
    else:
        raise AssertionError("EdinetApiError was not raised")
