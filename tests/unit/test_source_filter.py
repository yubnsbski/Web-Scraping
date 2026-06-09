"""Tests for flexible target-source matching in the AI Chat / RAG search.

EDINET filings are indexed under ``local_docs/edinet/<ticker>/<docid>.txt`` while
the UI's target dropdown historically pointed at ``local_docs/nikkei225/<ticker>/
ir.txt``. An exact-path filter therefore matched nothing and the chat returned
"no local documents". The matcher resolves a ticker/prefix to the indexed paths.
"""

from __future__ import annotations

from investment_assistant.cli import _source_filter_matches


def test_empty_filter_matches_everything() -> None:
    assert _source_filter_matches("local_docs/edinet/8306/S1.txt", "")
    assert _source_filter_matches("anything", "   ")


def test_exact_and_prefix_match() -> None:
    assert _source_filter_matches("local_docs/edinet/9432/S1.txt", "local_docs/edinet/9432/S1.txt")
    assert _source_filter_matches("local_docs/edinet/9432/S1.txt", "local_docs/edinet/9432")
    assert _source_filter_matches("local_docs/edinet/9432/S1.txt", "local_docs/edinet/9432/")


def test_ticker_segment_match_across_corpora() -> None:
    # The UI value points at the nikkei225 path, but data lives under edinet/.
    assert _source_filter_matches(
        "local_docs/edinet/8306/S100Y24.txt", "local_docs/nikkei225/8306/ir.txt"
    )


def test_non_matching_ticker_is_excluded() -> None:
    assert not _source_filter_matches(
        "local_docs/edinet/9999/S1.txt", "local_docs/nikkei225/8306/ir.txt"
    )
    assert not _source_filter_matches("local_docs/edinet/8306/S1.txt", "local_docs/edinet/2914")
