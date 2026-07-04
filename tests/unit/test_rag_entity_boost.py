"""Tests for entity/ticker-aware retrieval boosting."""

from __future__ import annotations

from investment_assistant.rag.search import SearchResult, boost_by_entities


def _result(chunk_id: str, source: str, score: float, ticker: str | None = None) -> SearchResult:
    metadata = {"ticker": ticker} if ticker else {}
    return SearchResult(
        chunk_id=chunk_id,
        source=source,
        chunk_index=0,
        score=score,
        text=f"{chunk_id} の詳細",
        metadata=metadata,
    )


def _pool() -> list[SearchResult]:
    return [
        _result("generic", "generic.md", 0.90, ticker=None),
        _result("kddi", "9433.md", 0.40, ticker="9433"),
        _result("other", "7203.md", 0.30, ticker="7203"),
    ]


def test_boost_by_entities_bare_ticker_code_boosts_matching_result() -> None:
    pool = _pool()
    boosted = boost_by_entities(pool, "9433の配当利回りを教えて")

    kddi_result = next(result for result in boosted if result.chunk_id == "kddi")
    original = next(result for result in pool if result.chunk_id == "kddi")
    assert kddi_result.score > original.score


def test_boost_by_entities_brand_name_boosts_matching_result() -> None:
    pool = _pool()
    boosted = boost_by_entities(pool, "KDDIの配当利回りと根拠を、投資助言にならない形で確認して")

    kddi_result = next(result for result in boosted if result.chunk_id == "kddi")
    original = next(result for result in pool if result.chunk_id == "kddi")
    assert kddi_result.score > original.score


def test_boost_by_entities_fullwidth_brand_name_boosts_matching_result() -> None:
    pool = _pool()
    boosted = boost_by_entities(pool, "ＫＤＤＩの配当利回りと根拠を確認して")

    kddi_result = next(result for result in boosted if result.chunk_id == "kddi")
    original = next(result for result in pool if result.chunk_id == "kddi")
    assert kddi_result.score > original.score


def test_boost_by_entities_no_signal_is_a_noop() -> None:
    pool = _pool()

    boosted = boost_by_entities(pool, "投資判断はユーザーが行います")

    assert boosted == pool
    assert [result.score for result in boosted] == [result.score for result in pool]


def test_boost_by_entities_reorders_when_boost_overtakes_higher_score() -> None:
    # A short ticker-scoped doc starts below a longer generic doc; a strong
    # enough entity match should be able to move it ahead.
    pool = [
        _result("generic", "generic.md", 0.50, ticker=None),
        _result("kddi", "9433.md", 0.45, ticker="9433"),
    ]

    boosted = boost_by_entities(pool, "9433 KDDI", weight=0.6)

    assert boosted[0].chunk_id == "kddi"
