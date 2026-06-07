from __future__ import annotations

from investment_assistant.edinet.models import (
    DOC_TYPE_ANNUAL_REPORT,
    DOC_TYPE_QUARTERLY_REPORT,
    EdinetDocument,
    filter_by_doc_types,
    filter_by_ticker,
    latest_document,
    parse_documents,
    securities_code,
    select_recent_documents,
)

_SAMPLE_PAYLOAD = {
    "metadata": {"resultset": {"count": 3}},
    "results": [
        {
            "docID": "S100AAA1",
            "edinetCode": "E00001",
            "secCode": "83060",
            "filerName": "三菱UFJフィナンシャル・グループ",
            "docTypeCode": "120",
            "docDescription": "有価証券報告書",
            "periodStart": "2023-04-01",
            "periodEnd": "2024-03-31",
            "submitDateTime": "2024-06-21 09:00",
            "xbrlFlag": "1",
            "csvFlag": "1",
            "pdfFlag": "1",
        },
        {
            "docID": "S100AAA2",
            "secCode": "83060",
            "filerName": "三菱UFJフィナンシャル・グループ",
            "docTypeCode": "140",
            "docDescription": "四半期報告書",
            "periodEnd": "2023-12-31",
            "submitDateTime": "2024-02-14 09:00",
            "csvFlag": "1",
        },
        {
            "docID": "S100BBB1",
            "secCode": "72030",
            "filerName": "トヨタ自動車",
            "docTypeCode": "120",
            "docDescription": "有価証券報告書",
            "periodEnd": "2024-03-31",
            "submitDateTime": "2024-06-20 09:00",
            "csvFlag": "1",
        },
        {"filerName": "no doc id row"},
    ],
}


def test_securities_code_pads_four_digit_ticker() -> None:
    assert securities_code("8306") == "83060"
    assert securities_code(" 7203 ") == "72030"
    # Non 4-digit inputs are returned cleaned but unpadded.
    assert securities_code("E00001") == "E00001"


def test_parse_documents_skips_rows_without_doc_id() -> None:
    documents = parse_documents(_SAMPLE_PAYLOAD)
    assert len(documents) == 3
    first = documents[0]
    assert first.doc_id == "S100AAA1"
    assert first.ticker == "8306"
    assert first.has_csv is True
    assert first.doc_type_label == "有価証券報告書"


def test_parse_documents_handles_empty_or_invalid_payload() -> None:
    assert parse_documents({"results": []}) == []
    assert parse_documents({}) == []


def test_filter_by_ticker_matches_securities_code() -> None:
    documents = parse_documents(_SAMPLE_PAYLOAD)
    mufg = filter_by_ticker(documents, "8306")
    assert {doc.doc_id for doc in mufg} == {"S100AAA1", "S100AAA2"}


def test_filter_by_doc_types_defaults_to_financial_reports() -> None:
    documents = parse_documents(_SAMPLE_PAYLOAD)
    annual = filter_by_doc_types(documents, {DOC_TYPE_ANNUAL_REPORT})
    assert {doc.doc_id for doc in annual} == {"S100AAA1", "S100BBB1"}
    quarterly = filter_by_doc_types(documents, {DOC_TYPE_QUARTERLY_REPORT})
    assert {doc.doc_id for doc in quarterly} == {"S100AAA2"}


def test_latest_document_picks_most_recent_submission() -> None:
    documents = filter_by_ticker(parse_documents(_SAMPLE_PAYLOAD), "8306")
    latest = latest_document(documents)
    assert latest is not None
    assert latest.doc_id == "S100AAA1"  # 2024-06-21 > 2024-02-14


def test_latest_document_returns_none_for_empty() -> None:
    assert latest_document([]) is None


def test_select_recent_documents_orders_desc_and_limits() -> None:
    documents = filter_by_ticker(parse_documents(_SAMPLE_PAYLOAD), "8306")
    top1 = select_recent_documents(documents, 1)
    assert [doc.doc_id for doc in top1] == ["S100AAA1"]

    top_all = select_recent_documents(documents, 5)
    assert [doc.doc_id for doc in top_all] == ["S100AAA1", "S100AAA2"]

    # limit <= 0 returns everything, still most-recent first.
    assert [doc.doc_id for doc in select_recent_documents(documents, 0)] == [
        "S100AAA1",
        "S100AAA2",
    ]


def test_ticker_is_none_for_non_standard_sec_code() -> None:
    doc = EdinetDocument(
        doc_id="X",
        edinet_code="E1",
        sec_code=None,
        filer_name="f",
        doc_type_code="120",
        doc_description="d",
        period_start=None,
        period_end=None,
        submit_datetime=None,
        has_xbrl=False,
        has_csv=False,
        has_pdf=False,
    )
    assert doc.ticker is None
