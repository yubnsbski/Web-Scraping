"""Tests for the feedback store and feedback-driven re-ranking."""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.feedback import FeedbackStore, feedback_source_scores
from investment_assistant.rag.search import SearchResult, boost_by_feedback


def _r(source: str, score: float, chunk_index: int = 0) -> SearchResult:
    return SearchResult(
        chunk_id=f"{source}-{chunk_index}",
        source=source,
        chunk_index=chunk_index,
        score=score,
        text=f"text {source}",
    )


def test_record_and_source_scores(tmp_path: Path) -> None:
    store = FeedbackStore(tmp_path / "fb.sqlite")
    store.record(rating="up", sources=["a.txt", "b.txt"], question="q")
    store.record(rating="up", sources=["a.txt"])
    store.record(rating="down", sources=["b.txt"])

    scores = store.source_scores()
    assert scores["a.txt"] == 2  # two upvotes
    assert scores["b.txt"] == 0  # one up, one down


def test_summary_counts_events_not_rows(tmp_path: Path) -> None:
    store = FeedbackStore(tmp_path / "fb.sqlite")
    store.record(rating="up", sources=["a.txt", "b.txt", "c.txt"])  # 1 event, 3 rows
    store.record(rating="down", sources=["a.txt"])
    summary = store.summary()
    assert summary["total"] == 2
    assert summary["up"] == 1
    assert summary["down"] == 1
    assert summary["rated_sources"] == 3  # type: ignore[operator]


def test_record_rejects_bad_rating(tmp_path: Path) -> None:
    store = FeedbackStore(tmp_path / "fb.sqlite")
    with pytest.raises(ValueError, match="rating"):
        store.record(rating="meh", sources=["a.txt"])


def test_feedback_source_scores_missing_db(tmp_path: Path) -> None:
    assert feedback_source_scores(tmp_path / "nope.sqlite") == {}


def test_boost_by_feedback_reranks_liked_above_disliked() -> None:
    # Equal base scores; feedback should float the liked source above the disliked.
    results = [_r("bad.txt", 0.50), _r("good.txt", 0.50), _r("neutral.txt", 0.50)]
    boosted = boost_by_feedback(results, {"good.txt": 5, "bad.txt": -5})
    order = [r.source for r in boosted]
    assert order[0] == "good.txt"
    assert order[-1] == "bad.txt"


def test_boost_is_bounded_and_no_op_without_feedback() -> None:
    results = [_r("a.txt", 1.0)]
    assert boost_by_feedback(results, {}) == results
    # A single upvote nudges by less than the weight ceiling (15%).
    boosted = boost_by_feedback(results, {"a.txt": 1}, weight=0.15)
    assert 1.0 < boosted[0].score < 1.15
