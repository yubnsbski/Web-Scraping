from __future__ import annotations

import math

import pytest

from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.embeddings import HashingEmbedder, cosine
from investment_assistant.rag.search import hybrid_search, search_chunks
from investment_assistant.rag.store import RagStore


def test_hashing_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashingEmbedder(dim=64)
    a = embedder.embed(["投資判断はユーザー本人が行います"])[0]
    b = embedder.embed(["投資判断はユーザー本人が行います"])[0]
    assert a == b  # deterministic
    assert math.isclose(math.sqrt(sum(v * v for v in a)), 1.0, rel_tol=1e-6)


def test_cosine_similarity_self_is_one_and_related_higher() -> None:
    embedder = HashingEmbedder(dim=128)
    finance = embedder.embed(["株式 投資 分散 ポートフォリオ 資産運用"])[0]
    finance2 = embedder.embed(["投資 株式 資産運用 分散投資"])[0]
    unrelated = embedder.embed(["今日の天気は晴れで気温が高い"])[0]
    assert cosine(finance, finance) == pytest.approx(1.0, abs=1e-6)
    assert cosine(finance, finance2) > cosine(finance, unrelated)


def _index(store: RagStore, tmp_path, name: str, text: str) -> None:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    document = load_document(path)
    store.upsert_document(
        document,
        chunk_text(source=document.source, text=document.text, content_hash=document.content_hash),
    )


def test_store_persists_embeddings(tmp_path) -> None:
    store = RagStore(tmp_path / "rag.sqlite")
    _index(store, tmp_path, "a.md", "投資判断はユーザー本人が行います。")
    embedded = store.iter_embeddings()
    assert len(embedded) == 1
    chunk, vector = embedded[0]
    assert "投資判断" in chunk.text
    assert len(vector) == HashingEmbedder().dim


def test_hybrid_search_returns_ranked_results(tmp_path) -> None:
    store = RagStore(tmp_path / "rag.sqlite")
    _index(store, tmp_path, "a.md", "投資判断はユーザー本人が行います。分散投資が重要です。")
    _index(store, tmp_path, "b.md", "自動売買は一切行いません。")

    results = hybrid_search(store, query="投資判断", limit=5, alpha=0.5)
    assert results
    assert "投資判断" in results[0].text
    assert results[0].score > 0


def test_hybrid_alpha_zero_matches_lexical_ordering(tmp_path) -> None:
    store = RagStore(tmp_path / "rag.sqlite")
    _index(store, tmp_path, "a.md", "投資判断は重要な投資判断です。")
    _index(store, tmp_path, "b.md", "自動売買は行いません。")

    lexical = search_chunks(store, query="投資判断", limit=5)
    hybrid_lexical = hybrid_search(store, query="投資判断", limit=5, alpha=0.0)
    assert [r.chunk_id for r in hybrid_lexical][:1] == [r.chunk_id for r in lexical][:1]
