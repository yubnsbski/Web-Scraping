from __future__ import annotations

from datetime import UTC, datetime, timedelta

from investment_assistant.ingestion.http_cache import HttpCache
from investment_assistant.llm.cache import LlmCache
from investment_assistant.observability import redact


def test_redact_truncates_and_annotates_length() -> None:
    assert redact(None) == "<empty>"
    assert redact("short") == "'short'(len=5)"
    long = "x" * 200
    rendered = redact(long, max_chars=10)
    assert "len=200" in rendered
    assert rendered.startswith("'xxxxxxxxxx'")


def test_redact_collapses_whitespace_and_hides_full_text() -> None:
    secret = "API_KEY=abcdefghijklmnopqrstuvwxyz0123456789"
    rendered = redact(secret, max_chars=8)
    assert "abcdefghijklmnopqrstuvwxyz" not in rendered  # full secret not present
    assert "len=" in rendered


def test_llm_cache_purge_expired(tmp_path) -> None:
    cache = LlmCache(tmp_path / "llm.sqlite", ttl_days=1)
    old = datetime.now(UTC) - timedelta(days=3)
    cache.set("k_old", "old", now=old)
    cache.set("k_new", "new")
    removed = cache.purge_expired()
    assert removed == 1
    assert cache.get("k_old") is None
    assert cache.get("k_new") == "new"


def test_llm_cache_enforce_max_rows_keeps_newest(tmp_path) -> None:
    cache = LlmCache(tmp_path / "llm.sqlite", ttl_days=365, max_rows=2)
    base = datetime.now(UTC)
    for index in range(5):
        cache.set(f"k{index}", f"v{index}", now=base + timedelta(minutes=index))
    # max_rows enforced on each set -> only the 2 newest remain.
    assert cache.get("k4") == "v4"
    assert cache.get("k3") == "v3"
    assert cache.get("k0") is None


def test_http_cache_purge_and_trim(tmp_path) -> None:
    cache = HttpCache(tmp_path / "http.sqlite", ttl_seconds=60)
    old = datetime.now(UTC) - timedelta(seconds=120)
    cache.set(url="https://a/", status_code=200, headers_json="{}", body=b"a", now=old)
    cache.set(url="https://b/", status_code=200, headers_json="{}", body=b"b")
    assert cache.purge_expired() == 1
    assert cache.get("https://a/") is None
    assert cache.enforce_max_rows(0) == 1  # trims the remaining row
