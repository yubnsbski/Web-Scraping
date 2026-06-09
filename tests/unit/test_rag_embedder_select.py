"""Tests for embedder selection and index/search space matching."""

from __future__ import annotations

from pathlib import Path

from investment_assistant.rag.chunker import Document, chunk_text
from investment_assistant.rag.embeddings import (
    Embedder,
    GeminiEmbedder,
    HashingEmbedder,
    resolve_embedder,
)
from investment_assistant.rag.store import RagStore, read_stored_embedder_name


def test_resolve_embedder_selects_by_name() -> None:
    assert isinstance(resolve_embedder("gemini"), GeminiEmbedder)
    assert isinstance(resolve_embedder("  GEMINI "), GeminiEmbedder)
    assert isinstance(resolve_embedder("hashing"), HashingEmbedder)
    assert isinstance(resolve_embedder(None), HashingEmbedder)
    assert isinstance(resolve_embedder(""), HashingEmbedder)


def _index_one(db_path: Path, embedder: Embedder) -> None:
    document = Document(
        source="memo.md", text="配当 方針 と 営業 キャッシュフロー の 記述", content_hash="h1"
    )
    chunks = chunk_text(
        source=document.source, text=document.text, content_hash=document.content_hash
    )
    RagStore(db_path, embedder=embedder).upsert_document(document, chunks)


def test_store_records_embedder_name_on_index(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_one(db, HashingEmbedder())
    assert read_stored_embedder_name(db) == "hashing"
    assert RagStore(db).stored_embedder_name() == "hashing"


def test_read_stored_embedder_name_missing_db(tmp_path: Path) -> None:
    assert read_stored_embedder_name(tmp_path / "nope.sqlite") is None


def test_read_stored_embedder_name_without_indexing(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    RagStore(db)  # schema only, no documents indexed yet
    assert read_stored_embedder_name(db) is None
