from __future__ import annotations

import pytest

from investment_assistant.ingestion.encoding import decode_body, detect_charset
from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.ingestion.transport import (
    ResponseTooLargeError,
    UnsafeUrlError,
    UrlLibHttpTransport,
    validate_public_http_url,
)
from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.search import (
    SearchResult,
    build_answer_context,
    search_chunks,
)
from investment_assistant.rag.store import RagStore
from investment_assistant.rag.tokenize import tokenize


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "http://127.0.0.1/admin",
        "http://10.0.0.5/internal",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/",
        "https://[::1]/",
    ],
)
def test_validate_public_http_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_http_url(url)


def test_validate_public_http_url_allows_public_ip() -> None:
    # Numeric IPs do not require DNS, so this stays offline.
    validate_public_http_url("http://8.8.8.8/")


def test_transport_read_limited_enforces_size_cap() -> None:
    transport = UrlLibHttpTransport(max_bytes=4)

    class _FakeResponse:
        def read(self, size: int) -> bytes:
            return b"x" * size

    with pytest.raises(ResponseTooLargeError):
        transport._read_limited(_FakeResponse())


def test_detect_charset_prefers_header_then_meta() -> None:
    assert detect_charset(b"<html></html>", "text/html; charset=Shift_JIS") == "cp932"
    assert detect_charset(b'<meta charset="euc-jp">', "text/html") == "euc_jp"
    assert detect_charset(b"<html></html>", "text/html") is None


def test_decode_body_handles_shift_jis() -> None:
    body = "投資判断".encode("cp932")
    assert decode_body(body, "text/html; charset=shift_jis") == "投資判断"
    # Without a declared charset, the UTF-8 fallback still decodes UTF-8 bytes.
    assert decode_body("自動売買".encode(), None) == "自動売買"


def test_reject_path_traversal_blocks_parent_escape(tmp_path) -> None:
    with pytest.raises(ValueError, match="traversal"):
        reject_path_traversal("../escape.txt")
    # Absolute paths are the caller's explicit choice and are allowed.
    assert reject_path_traversal(tmp_path / "out.txt")


def test_tokenize_emits_cjk_bigrams_and_ascii_words() -> None:
    tokens = tokenize("投資 ETF2024")
    assert "投" in tokens
    assert "投資" in tokens
    assert "etf2024" in tokens


def test_fts_search_ranks_relevant_chunk_first(tmp_path) -> None:
    store = RagStore(tmp_path / "rag.sqlite")
    assert store.fts_enabled
    for name, text in (
        ("a.md", "投資判断はユーザー本人が行います。"),
        ("b.md", "自動売買は一切行いません。"),
    ):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        document = load_document(path)
        store.upsert_document(
            document,
            chunk_text(
                source=document.source,
                text=document.text,
                content_hash=document.content_hash,
            ),
        )

    results = search_chunks(store, query="投資判断", limit=5)

    assert results
    assert "投資判断" in results[0].text
    assert results[0].score > 0


def test_search_chunks_dedupes_identical_text(tmp_path) -> None:
    store = RagStore(tmp_path / "rag.sqlite")
    for name in ("a.md", "b.md"):
        path = tmp_path / name
        path.write_text("投資判断は同一の本文です。", encoding="utf-8")
        document = load_document(path)
        store.upsert_document(
            document,
            chunk_text(
                source=document.source,
                text=document.text,
                content_hash=document.content_hash,
            ),
        )

    results = search_chunks(store, query="投資判断", limit=5)

    assert len(results) == 1


def test_build_answer_context_respects_char_budget() -> None:
    results = [
        SearchResult(
            chunk_id=f"c{index}",
            source=f"s{index}.md",
            chunk_index=0,
            score=1.0,
            text="あ" * 500,
        )
        for index in range(5)
    ]

    context = build_answer_context(results, max_context_chars=300)

    assert len(context) <= 320  # budget plus a small header allowance
