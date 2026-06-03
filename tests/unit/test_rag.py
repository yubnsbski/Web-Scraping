from __future__ import annotations

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
    assert results[0].score >= 1
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
