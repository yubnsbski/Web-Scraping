"""Tests for shared RAG tokenization, including width normalization."""

from __future__ import annotations

from investment_assistant.rag.tokenize import tokenize, tokens_to_index_text


def test_tokenize_normalizes_fullwidth_latin_to_ascii_token() -> None:
    # ＫＤＤＩ is full-width Latin; NFKC normalization must fold it to ASCII
    # "kddi" so a half-width query token ("kddi") can match it.
    assert "kddi" in tokenize("ＫＤＤＩ")


def test_tokenize_normalizes_fullwidth_digits() -> None:
    assert "9433" in tokenize("９４３３")


def test_tokenize_halfwidth_and_fullwidth_produce_same_tokens() -> None:
    assert tokenize("KDDI") == tokenize("ＫＤＤＩ")


def test_tokens_to_index_text_includes_normalized_token() -> None:
    assert "kddi" in tokens_to_index_text("ＫＤＤＩ（９４３３） 市況データ").split()
