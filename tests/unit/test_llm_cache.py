from __future__ import annotations

from datetime import UTC, datetime, timedelta

from investment_assistant.llm.cache import LlmCache


def test_cache_returns_stored_response(tmp_path):
    cache = LlmCache(tmp_path / "cache.sqlite", ttl_days=30)
    key = cache.make_key("rag_answer", "gemini", "prompt")

    cache.set(key, "response", now=datetime(2026, 6, 1, tzinfo=UTC))

    assert cache.get(key, now=datetime(2026, 6, 2, tzinfo=UTC)) == "response"


def test_cache_expires_old_response(tmp_path):
    cache = LlmCache(tmp_path / "cache.sqlite", ttl_days=1)
    key = cache.make_key("rag_answer", "gemini", "prompt")

    cache.set(key, "response", now=datetime(2026, 6, 1, tzinfo=UTC))

    assert cache.get(key, now=datetime(2026, 6, 1, tzinfo=UTC) + timedelta(days=2)) is None


def test_disabled_cache_never_reads_or_writes(tmp_path):
    cache = LlmCache(tmp_path / "cache.sqlite", enabled=False)
    key = cache.make_key("rag_answer", "gemini", "prompt")

    cache.set(key, "response")

    assert cache.get(key) is None
