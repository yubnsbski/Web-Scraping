"""Tests for storage maintenance / retention (bounding disk growth)."""

from __future__ import annotations

import os
from pathlib import Path

from investment_assistant.ingestion.http_cache import HttpCache
from investment_assistant.maintenance import (
    prune_http_cache,
    prune_local_docs,
    run_storage_prune,
)


def _make_filing(directory: Path, doc_id: str, *, mtime: float) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for suffix in (".txt", ".points.json"):
        path = directory / f"{doc_id}{suffix}"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (mtime, mtime))


def test_prune_local_docs_keeps_recent_filings_per_ticker(tmp_path: Path) -> None:
    root = tmp_path / "edinet"
    ticker = root / "8306"
    for index in range(5):
        _make_filing(ticker, f"DOC{index}", mtime=1000.0 + index)  # DOC4 newest
    # A durable aggregate at the root must never be pruned.
    root.mkdir(parents=True, exist_ok=True)
    (root / "financials.csv").write_text("ticker,fy\n", encoding="utf-8")

    result = prune_local_docs(root, keep_per_dir=2)

    assert result["filings_removed"] == 3
    assert result["files_removed"] == 6  # 3 filings x 2 files each
    remaining = sorted(p.name for p in ticker.iterdir())
    assert remaining == [
        "DOC3.points.json",
        "DOC3.txt",
        "DOC4.points.json",
        "DOC4.txt",
    ]
    assert (root / "financials.csv").is_file()


def test_prune_local_docs_noop_when_within_limit(tmp_path: Path) -> None:
    root = tmp_path / "edinet"
    _make_filing(root / "8306", "DOC0", mtime=1000.0)
    result = prune_local_docs(root, keep_per_dir=8)
    assert result["files_removed"] == 0


def test_prune_local_docs_missing_root(tmp_path: Path) -> None:
    result = prune_local_docs(tmp_path / "nope", keep_per_dir=8)
    assert result["files_removed"] == 0
    assert result["dirs_scanned"] == 0


def test_prune_http_cache_trims_and_reports(tmp_path: Path) -> None:
    cache_path = tmp_path / "http_cache.sqlite"
    cache = HttpCache(cache_path)
    for index in range(5):
        cache.set(url=f"https://example/{index}", status_code=200, headers_json="{}", body=b"x")

    result = prune_http_cache(cache_path, max_rows=2, purge_expired=False)

    assert result["exists"] is True
    assert result["trimmed_removed"] == 3
    assert result["remaining"] == 2


def test_prune_http_cache_missing_file(tmp_path: Path) -> None:
    result = prune_http_cache(tmp_path / "nope.sqlite")
    assert result["exists"] is False


def test_run_storage_prune_combines_docs_and_cache(tmp_path: Path) -> None:
    root = tmp_path / "edinet"
    for index in range(4):
        _make_filing(root / "8306", f"DOC{index}", mtime=1000.0 + index)
    cache_path = tmp_path / "http_cache.sqlite"
    cache = HttpCache(cache_path)
    cache.set(url="https://example/1", status_code=200, headers_json="{}", body=b"x")

    result = run_storage_prune(
        docs_roots=[root],
        cache_path=cache_path,
        keep_per_dir=2,
        http_max_rows=1,
    )

    assert result["files_removed_total"] == 4  # 2 pruned filings x 2 files
    http = result["http_cache"]
    assert isinstance(http, dict)
    assert http["exists"] is True
