"""Tests for diversity/dedup selection over a retrieved candidate pool."""

from __future__ import annotations

from investment_assistant.rag.search import SearchResult, diversify_results


def _result(chunk_id: str, source: str, index: int, score: float, text: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id, source=source, chunk_index=index, score=score, text=text
    )


def _pool() -> list[SearchResult]:
    return [
        _result("a0", "A.txt", 0, 0.90, "配当 方針 について A0 の 詳細 説明"),
        _result("a1", "A.txt", 1, 0.85, "営業 キャッシュフロー A1 の 詳細"),
        _result("a2", "A.txt", 2, 0.80, "自己資本 比率 A2 の 詳細"),
        _result("a3", "A.txt", 3, 0.75, "配当 性向 A3 の 詳細"),
        _result("b0", "B.txt", 0, 0.70, "減配 履歴 B0 の 詳細"),
        _result("a4", "A.txt", 4, 0.65, "中期 経営 計画 A4 の 詳細"),
        _result("b1", "B.txt", 1, 0.60, "株主 還元 B1 の 詳細"),
    ]


def test_diversify_caps_per_source() -> None:
    out = diversify_results(_pool(), limit=5, max_per_source=3)
    sources = [result.source for result in out]
    assert len(out) == 5
    assert sources.count("A.txt") == 3  # capped at 3
    assert sources.count("B.txt") == 2
    ids = {result.chunk_id for result in out}
    assert "a3" not in ids and "a4" not in ids  # over-cap A chunks excluded


def test_diversify_backfills_over_cap_to_reach_limit() -> None:
    out = diversify_results(_pool(), limit=6, max_per_source=3)
    ids = [result.chunk_id for result in out]
    assert len(out) == 6
    # Capped pass picks a0,a1,a2,b0,b1; backfill adds the next A chunk (a3).
    assert "a3" in ids
    assert ids.count("a4") == 0


def test_diversify_drops_near_duplicates_within_source() -> None:
    dup = "配当 方針 は 安定 配当 を 継続 する 方針 です"
    pool = [
        _result("a0", "A.txt", 0, 0.90, dup),
        _result("a1", "A.txt", 1, 0.88, dup + " 。"),  # near-identical
        _result("b0", "B.txt", 0, 0.50, "全く 別 の 内容 減配 履歴 です"),
    ]
    ids = {result.chunk_id for result in diversify_results(pool, limit=5, max_per_source=5)}
    assert "a0" in ids
    assert "a1" not in ids  # near-duplicate dropped
    assert "b0" in ids  # different source kept


def test_diversify_empty_and_zero_limit() -> None:
    assert diversify_results([], limit=5) == []
    assert diversify_results(_pool(), limit=0) == []
