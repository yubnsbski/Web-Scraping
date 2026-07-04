from __future__ import annotations

from investment_assistant.cli import run_rag_answer_context, run_rag_index_dir
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


def test_answer_context_returns_forecast_highlights(tmp_path) -> None:
    doc = tmp_path / "7203.md"
    doc.write_text(
        "# トヨタ（7203） 市場データ\n"
        "特徴: 高配当（利回り≥3.5%）\n"
        "予測（統計推定・非助言）: +1営業日 2,100 円 / +5営業日 2,120 円\n",
        encoding="utf-8",
    )
    db = tmp_path / "rag.sqlite"
    document = load_document(doc)
    RagStore(db).upsert_document(
        document,
        chunk_text(source=document.source, text=document.text, content_hash=document.content_hash),
    )

    result = run_rag_answer_context(query="トヨタ 予測 配当", db_path=db, limit=5)

    highlights = result["highlights"]
    assert isinstance(highlights, list) and highlights
    assert highlights[0]["ticker"] == "7203"
    assert "2,100 円" in str(highlights[0]["forecast"])


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

    result = run_rag_index_dir(
        path=docs_dir,
        db_path=db_path,
        max_chars=80,
        overlap_chars=0,
        content_only=False,
    )
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


def test_run_rag_index_dir_filters_files_without_front_matter_by_default(tmp_path) -> None:
    docs_dir = tmp_path / "local_docs"
    docs_dir.mkdir()
    content_doc = docs_dir / "9433.md"
    content_doc.write_text(
        '---\ndoc_type: market_evidence\nticker: "9433"\n---\n\n# KDDI\n本文...',
        encoding="utf-8",
    )
    operational_doc = docs_dir / "data_action_queue.md"
    operational_doc.write_text(
        "# データアクションキュー\n未処理タスク一覧...",
        encoding="utf-8",
    )
    db_path = tmp_path / "rag.sqlite"

    result = run_rag_index_dir(path=docs_dir, db_path=db_path)
    store = RagStore(db_path)
    chunks = store.list_chunks()

    assert result["indexed_sources"] == [str(content_doc)]
    assert str(operational_doc) in result["skipped_files"]
    assert {chunk.source for chunk in chunks} == {str(content_doc)}


def test_run_rag_index_dir_prunes_documents_removed_from_disk(tmp_path) -> None:
    docs_dir = tmp_path / "local_docs"
    docs_dir.mkdir()
    keep_doc = docs_dir / "9433.md"
    keep_doc.write_text(
        '---\ndoc_type: market_evidence\nticker: "9433"\n---\n\n# KDDI\n本文...',
        encoding="utf-8",
    )
    removed_doc = docs_dir / "9432.md"
    removed_doc.write_text(
        '---\ndoc_type: market_evidence\nticker: "9432"\n---\n\n# NTT\n本文...',
        encoding="utf-8",
    )
    db_path = tmp_path / "rag.sqlite"

    first_result = run_rag_index_dir(path=docs_dir, db_path=db_path)
    assert first_result["documents_pruned"] == 0
    store = RagStore(db_path)
    assert {chunk.source for chunk in store.list_chunks()} == {str(keep_doc), str(removed_doc)}

    removed_doc.unlink()
    second_result = run_rag_index_dir(path=docs_dir, db_path=db_path)

    assert second_result["documents_pruned"] == 1
    assert {chunk.source for chunk in store.list_chunks()} == {str(keep_doc)}


def test_run_rag_index_dir_does_not_prune_outside_indexed_prefix(tmp_path) -> None:
    root_dir = tmp_path / "local_docs"
    kept_subdir = root_dir / "kept"
    other_subdir = root_dir / "other"
    kept_subdir.mkdir(parents=True)
    other_subdir.mkdir(parents=True)
    kept_doc = kept_subdir / "9433.md"
    kept_doc.write_text(
        '---\ndoc_type: market_evidence\nticker: "9433"\n---\n\n# KDDI\n本文...',
        encoding="utf-8",
    )
    other_doc = other_subdir / "9432.md"
    other_doc.write_text(
        '---\ndoc_type: market_evidence\nticker: "9432"\n---\n\n# NTT\n本文...',
        encoding="utf-8",
    )
    db_path = tmp_path / "rag.sqlite"

    run_rag_index_dir(path=root_dir, db_path=db_path)
    store = RagStore(db_path)
    assert {chunk.source for chunk in store.list_chunks()} == {str(kept_doc), str(other_doc)}

    # Re-index only the "kept" subdirectory; documents under "other" are outside
    # this run's prefix and must survive the prune.
    result = run_rag_index_dir(path=kept_subdir, db_path=db_path)

    assert result["documents_pruned"] == 0
    assert {chunk.source for chunk in store.list_chunks()} == {str(kept_doc), str(other_doc)}


def test_run_rag_index_dir_does_not_prune_sibling_dir_with_colliding_name_prefix(
    tmp_path,
) -> None:
    # Regression test: a naive `source.startswith(under_prefix)` check treats
    # ".../rag_priority1" as being "under" ".../rag" because the *string*
    # "rag_priority1" starts with the string "rag" -- even though the
    # directory "rag_priority1" is a sibling of "rag", not a descendant. The
    # indexed prefix must require a path-separator boundary (or exact
    # equality) so sibling directories whose names happen to share a prefix
    # are never pruned.
    market_dir = tmp_path / "market"
    rag_dir = market_dir / "rag"
    rag_priority1_dir = market_dir / "rag_priority1"
    rag_priority2_dir = market_dir / "rag_priority2"
    rag_dir.mkdir(parents=True)
    rag_priority1_dir.mkdir(parents=True)
    rag_priority2_dir.mkdir(parents=True)

    rag_doc = rag_dir / "9433.md"
    rag_doc.write_text(
        '---\ndoc_type: market_evidence\nticker: "9433"\n---\n\n# KDDI\n本文...',
        encoding="utf-8",
    )
    priority1_doc = rag_priority1_dir / "9432.md"
    priority1_doc.write_text(
        '---\ndoc_type: market_evidence\nticker: "9432"\n---\n\n# NTT\n本文...',
        encoding="utf-8",
    )
    priority2_doc = rag_priority2_dir / "9613.md"
    priority2_doc.write_text(
        '---\ndoc_type: market_evidence\nticker: "9613"\n---\n\n# NTTデータ\n本文...',
        encoding="utf-8",
    )
    db_path = tmp_path / "rag.sqlite"

    run_rag_index_dir(path=market_dir, db_path=db_path)
    store = RagStore(db_path)
    assert {chunk.source for chunk in store.list_chunks()} == {
        str(rag_doc),
        str(priority1_doc),
        str(priority2_doc),
    }

    # Re-index only "rag"; the colliding-name siblings "rag_priority1" and
    # "rag_priority2" are outside this run's prefix and must survive.
    result = run_rag_index_dir(path=rag_dir, db_path=db_path)

    assert result["documents_pruned"] == 0
    assert {chunk.source for chunk in store.list_chunks()} == {
        str(rag_doc),
        str(priority1_doc),
        str(priority2_doc),
    }


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
