"""Offline tests for the sentence-transformers neural embedder.

No model download or network: a deterministic fake model object is injected
in place of ``sentence_transformers.SentenceTransformer``.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import pytest

from investment_assistant.rag import neural_embeddings
from investment_assistant.rag.chunker import Document, chunk_text
from investment_assistant.rag.embeddings import (
    Embedder,
    EmbedderMismatchError,
    HashingEmbedder,
    embed_queries,
    resolve_embedder,
)
from investment_assistant.rag.neural_embeddings import SentenceTransformersEmbedder
from investment_assistant.rag.search import hybrid_search
from investment_assistant.rag.store import RagStore, read_stored_embedder_name


class FakeSentenceTransformer:
    """Deterministic stand-in for ``sentence_transformers.SentenceTransformer``."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def encode(self, sentences: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append(list(sentences))
        return [self._vector(text) for text in sentences]

    def _vector(self, text: str) -> list[float]:
        seed = sum(text.encode("utf-8"))
        return [float((seed * (index + 3)) % 97 + 1) for index in range(self.dim)]


def _neural(model_id: str = "intfloat/multilingual-e5-small") -> SentenceTransformersEmbedder:
    return SentenceTransformersEmbedder(model_id, model=FakeSentenceTransformer())


def test_module_import_does_not_require_sentence_transformers() -> None:
    # The module is already imported at the top of this file; the package must
    # not have been pulled in as a side effect.
    assert "sentence_transformers" not in sys.modules


def test_embedder_satisfies_protocol_and_normalizes() -> None:
    embedder: Embedder = _neural()
    assert embedder.name == "st:intfloat/multilingual-e5-small"
    vectors = embedder.embed(["配当方針の説明", "自己株買いの発表"])
    assert len(vectors) == 2
    assert embedder.dim == 8
    for vector in vectors:
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)


def test_e5_model_prefixes_passages_and_queries_differently() -> None:
    fake = FakeSentenceTransformer()
    embedder = SentenceTransformersEmbedder("intfloat/multilingual-e5-small", model=fake)
    embedder.embed(["高配当銘柄の解説"])
    embedder.embed_queries(["高配当銘柄の根拠を探す"])
    assert fake.calls[0] == ["passage: 高配当銘柄の解説"]
    assert fake.calls[1] == ["query: 高配当銘柄の根拠を探す"]


def test_non_e5_model_gets_no_prefixes() -> None:
    fake = FakeSentenceTransformer()
    embedder = SentenceTransformersEmbedder(
        "sentence-transformers/all-MiniLM-L6-v2", model=fake
    )
    embedder.embed(["本文テキスト"])
    embedder.embed_queries(["質問テキスト"])
    assert fake.calls == [["本文テキスト"], ["質問テキスト"]]


def test_embed_queries_helper_dispatches_or_falls_back() -> None:
    fake = FakeSentenceTransformer()
    neural = SentenceTransformersEmbedder("intfloat/multilingual-e5-small", model=fake)
    embed_queries(neural, ["根拠"])
    assert fake.calls == [["query: 根拠"]]

    hashing = HashingEmbedder(dim=32)
    assert embed_queries(hashing, ["根拠"]) == hashing.embed(["根拠"])


def test_resolve_embedder_registers_neural_names() -> None:
    alias = resolve_embedder("multilingual-e5-small")
    assert isinstance(alias, SentenceTransformersEmbedder)
    assert alias.model_id == "intfloat/multilingual-e5-small"
    assert alias.name == "st:intfloat/multilingual-e5-small"

    direct = resolve_embedder("intfloat/multilingual-e5-large")
    assert isinstance(direct, SentenceTransformersEmbedder)
    assert direct.model_id == "intfloat/multilingual-e5-large"

    prefixed = resolve_embedder("st:org/custom-model")
    assert isinstance(prefixed, SentenceTransformersEmbedder)
    assert prefixed.model_id == "org/custom-model"

    # Round trip: the name persisted in DB meta resolves back to the same model.
    again = resolve_embedder(alias.name)
    assert isinstance(again, SentenceTransformersEmbedder)
    assert again.model_id == alias.model_id

    # Existing behavior is preserved: hashing stays the default.
    assert isinstance(resolve_embedder("hashing"), HashingEmbedder)
    assert isinstance(resolve_embedder(None), HashingEmbedder)
    assert isinstance(resolve_embedder(""), HashingEmbedder)
    assert isinstance(resolve_embedder("unknown-name"), HashingEmbedder)


def _index_one(db_path: Path, embedder: Embedder) -> None:
    document = Document(
        source="memo.md", text="配当 方針 と 営業 キャッシュフロー の 記述", content_hash="h1"
    )
    chunks = chunk_text(
        source=document.source, text=document.text, content_hash=document.content_hash
    )
    RagStore(db_path, embedder=embedder).upsert_document(document, chunks)


def test_store_persists_neural_embedder_name(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_one(db, _neural())
    assert read_stored_embedder_name(db) == "st:intfloat/multilingual-e5-small"


def test_hybrid_search_rejects_mismatched_query_embedder(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    neural = _neural()
    _index_one(db, neural)
    store = RagStore(db, embedder=neural)

    # Default (hashing) query embedder against a neural-built index must fail
    # loudly instead of comparing vectors from incompatible spaces.
    with pytest.raises(EmbedderMismatchError):
        hybrid_search(store, query="配当", limit=3)

    # The matching embedder is accepted and returns results.
    results = hybrid_search(store, query="配当", limit=3, embedder=neural)
    assert results

    # And the reverse direction: hashing-built index, neural query embedder.
    hashing_db = tmp_path / "hashing.sqlite"
    _index_one(hashing_db, HashingEmbedder())
    hashing_store = RagStore(hashing_db)
    with pytest.raises(EmbedderMismatchError):
        hybrid_search(hashing_store, query="配当", limit=3, embedder=_neural())


def test_hybrid_search_allows_index_without_recorded_embedder(tmp_path: Path) -> None:
    store = RagStore(tmp_path / "empty.sqlite")  # schema only, meta absent
    assert hybrid_search(store, query="配当", limit=3) == []


def test_missing_package_error_mentions_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = SentenceTransformersEmbedder("intfloat/multilingual-e5-small")
    monkeypatch.setattr(neural_embeddings, "_find_spec", lambda name: None)
    with pytest.raises(RuntimeError, match=r"pip install -e '\.\[embeddings\]'"):
        embedder.embed(["配当"])
