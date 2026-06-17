from __future__ import annotations

from investment_assistant.cli import run_rag_index_dir
from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.search import build_answer_context, search_chunks
from investment_assistant.rag.store import RagStore


def test_chunk_text_splits_with_stable_metadata() -> None:
    chunks = chunk_text(
        source="memo.md",
        text="投資判断はユーザーが行います。\n自動売買は行いません。\n" * 5,
        content_hash="abc123",
        max_chars=40,
        overlap_chars=5,
    )

    assert len(chunks) > 1
    assert chunks[0].source == "memo.md"
    assert chunks[0].chunk_index == 0
    assert chunks[0].content_hash == "abc123"
    assert chunks[0].chunk_id == chunk_text(
        source="memo.md",
        text="投資判断はユーザーが行います。\n自動売買は行いません。\n" * 5,
        content_hash="abc123",
        max_chars=40,
        overlap_chars=5,
    )[0].chunk_id


def test_chunk_text_rejects_invalid_overlap() -> None:
    try:
        chunk_text(source="memo.md", text="hello", max_chars=10, overlap_chars=10)
    except ValueError as exc:
        assert "overlap_chars" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_rag_store_replaces_existing_document_chunks(tmp_path) -> None:
    path = tmp_path / "memo.md"
    path.write_text("投資判断はユーザーが行います。", encoding="utf-8")
    document = load_document(path)
    store = RagStore(tmp_path / "rag.sqlite")

    first_chunks = chunk_text(source=document.source, text=document.text, content_hash="first")
    second_chunks = chunk_text(
        source=document.source,
        text="自動売買は行いません。",
        content_hash="second",
    )

    assert store.upsert_document(document, first_chunks) == 1
    assert store.upsert_document(document, second_chunks) == 1

    stored = store.list_chunks()
    assert len(stored) == 1
    assert stored[0].content_hash == "second"
    assert "自動売買" in stored[0].text


def test_search_chunks_scores_and_limits_results(tmp_path) -> None:
    path = tmp_path / "memo.md"
    path.write_text(
        "投資判断はユーザーが行います。投資判断には根拠が必要です。\n"
        "自動売買は行いません。",
        encoding="utf-8",
    )
    document = load_document(path)
    chunks = chunk_text(
        source=document.source,
        text=document.text,
        content_hash=document.content_hash,
        max_chars=80,
        overlap_chars=0,
    )
    store = RagStore(tmp_path / "rag.sqlite")
    store.upsert_document(document, chunks)

    results = search_chunks(store, query="投資判断", limit=1)

    assert len(results) == 1
    assert results[0].score > 0
    assert "投資判断" in results[0].text


def test_build_answer_context_formats_citations(tmp_path) -> None:
    path = tmp_path / "memo.md"
    path.write_text("自動売買は行いません。", encoding="utf-8")
    document = load_document(path)
    store = RagStore(tmp_path / "rag.sqlite")
    store.upsert_document(
        document,
        chunk_text(source=document.source, text=document.text, content_hash=document.content_hash),
    )

    context = build_answer_context(search_chunks(store, query="自動売買", limit=5))

    assert "[1] source=" in context
    assert "自動売買は行いません" in context


def test_run_rag_index_dir_indexes_supported_files_recursively(tmp_path) -> None:
    docs_dir = tmp_path / "local_docs"
    nested_dir = docs_dir / "nested"
    cache_dir = docs_dir / ".cache"
    nested_dir.mkdir(parents=True)
    cache_dir.mkdir()
    first = docs_dir / "memo.txt"
    second = nested_dir / "note.md"
    ignored_csv = docs_dir / "funds.csv"
    ignored_db = docs_dir / "rag.sqlite"
    ignored_env = docs_dir / ".env"
    ignored_cache_doc = cache_dir / "cached.md"
    binary_txt = docs_dir / "binary.txt"
    first.write_text("投資判断はユーザーが行います。", encoding="utf-8")
    second.write_text("自動売買は行いません。", encoding="utf-8")
    ignored_csv.write_text("name,value\nA,1\n", encoding="utf-8")
    ignored_db.write_text("sqlite", encoding="utf-8")
    ignored_env.write_text("SECRET=value", encoding="utf-8")
    ignored_cache_doc.write_text("cache should be skipped", encoding="utf-8")
    binary_txt.write_bytes(b"\xff\xfe\x00")
    db_path = tmp_path / "rag.sqlite"

    result = run_rag_index_dir(path=docs_dir, db_path=db_path, max_chars=80, overlap_chars=0)
    store = RagStore(db_path)
    chunks = store.list_chunks()

    assert result["files_indexed"] == 2
    assert result["chunks_indexed"] == 2
    assert str(first) in result["indexed_sources"]
    assert str(second) in result["indexed_sources"]
    skipped = result["skipped_files"]
    assert isinstance(skipped, list)
    assert str(ignored_csv) in skipped
    assert str(ignored_db) in skipped
    assert str(ignored_env) in skipped
    assert str(ignored_cache_doc) in skipped
    assert str(binary_txt) in skipped
    assert {chunk.source for chunk in chunks} == {str(first), str(second)}


def test_run_rag_index_dir_handles_empty_directory(tmp_path) -> None:
    docs_dir = tmp_path / "empty_docs"
    docs_dir.mkdir()

    result = run_rag_index_dir(path=docs_dir, db_path=tmp_path / "rag.sqlite")

    assert result["files_indexed"] == 0
    assert result["chunks_indexed"] == 0
    assert result["indexed_sources"] == []
    assert result["skipped_files"] == []


def test_load_document_extracts_front_matter_metadata(tmp_path) -> None:
    path = tmp_path / "fetched.txt"
    path.write_text(
        "---\n"
        'source_url: "https://example.com/funds"\n'
        "fetched_at: 2026-06-06T00:00:00Z\n"
        "status_code: 200\n"
        'content_type: "text/html; charset=utf-8"\n'
        "extracted_text: true\n"
        "---\n\n"
        "Fund Page\n\nVisible text.",
        encoding="utf-8",
    )

    document = load_document(path)

    assert document.text == "Fund Page\n\nVisible text."
    assert document.metadata == {
        "source_url": "https://example.com/funds",
        "fetched_at": "2026-06-06T00:00:00Z",
        "status_code": "200",
        "content_type": "text/html; charset=utf-8",
        "extracted_text": "true",
    }


def test_search_results_include_front_matter_metadata_in_context(tmp_path) -> None:
    path = tmp_path / "fetched.txt"
    path.write_text(
        "---\n"
        'source_url: "https://example.com/funds"\n'
        "doc_type: investment_report\n"
        'title: "KDDI monthly report"\n'
        "report_id: report-202606\n"
        "integrity_status: ok\n"
        "fetched_at: 2026-06-06T00:00:00Z\n"
        "status_code: 200\n"
        'content_type: "text/html; charset=utf-8"\n'
        "extracted_text: true\n"
        "---\n\n"
        "Fund Page\n\nVisible text for 投資判断.",
        encoding="utf-8",
    )
    document = load_document(path)
    store = RagStore(tmp_path / "rag.sqlite")
    store.upsert_document(
        document,
        chunk_text(
            source=document.source,
            text=document.text,
            content_hash=document.content_hash,
            max_chars=120,
            overlap_chars=0,
        ),
    )

    results = search_chunks(store, query="投資判断", limit=5)
    context = build_answer_context(results)

    assert results[0].metadata["source_url"] == "https://example.com/funds"
    assert results[0].metadata["doc_type"] == "investment_report"
    assert results[0].metadata["report_id"] == "report-202606"
    assert results[0].metadata["fetched_at"] == "2026-06-06T00:00:00Z"
    assert "source_url=https://example.com/funds" in context
    assert "doc_type=investment_report" in context
    assert "report_id=report-202606" in context
    assert "integrity_status=ok" in context
    assert "fetched_at=2026-06-06T00:00:00Z" in context
    assert "status_code=200" in context
    assert "content_type=text/html; charset=utf-8" in context
    assert "source_url:" not in results[0].text
