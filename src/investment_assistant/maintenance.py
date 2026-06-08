"""Storage maintenance: bound disk growth from accumulated ingestion artifacts.

Weekly runs over ~220 tickers accumulate per-filing text + sidecars under
``local_docs`` and cached response bodies in the HTTP cache. This module prunes
the bulky, regenerable parts while leaving the small durable history
(``financials.csv``) intact:

- ``prune_local_docs``: per ticker directory, keep only the most recent N
  filings (a filing = its ``<doc_id>.*`` files), delete older ones.
- ``prune_http_cache``: drop expired / surplus cached responses and VACUUM the
  SQLite file so the freed space is actually returned to disk.

No network I/O. Only files under the given roots are touched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.ingestion.http_cache import HttpCache
from investment_assistant.observability import get_logger

_logger = get_logger("maintenance")

DEFAULT_KEEP_PER_DIR = 8
DEFAULT_HTTP_MAX_ROWS = 500
# Files kept regardless of retention (durable aggregates live at the root).
_PROTECTED_NAMES = frozenset({"financials.csv"})


def prune_local_docs(
    root: str | Path, *, keep_per_dir: int = DEFAULT_KEEP_PER_DIR
) -> dict[str, object]:
    """Keep only the most recent ``keep_per_dir`` filings per subdirectory.

    A "filing" groups all files sharing a ``<doc_id>`` prefix (e.g.
    ``S100ABC.txt`` and ``S100ABC.points.json``). Files directly under ``root``
    (such as ``financials.csv``) are never touched — only files inside the
    immediate subdirectories are pruned.
    """

    base = reject_path_traversal(root)
    result: dict[str, object] = {
        "root": str(base),
        "dirs_scanned": 0,
        "filings_removed": 0,
        "files_removed": 0,
    }
    if not base.is_dir():
        return result

    keep = max(0, keep_per_dir)
    dirs_scanned = 0
    filings_removed = 0
    files_removed = 0
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        dirs_scanned += 1
        groups = _group_by_doc_id(sub)
        if len(groups) <= keep:
            continue
        ordered = sorted(
            groups.items(),
            key=lambda item: max(path.stat().st_mtime for path in item[1]),
            reverse=True,
        )
        for _doc_id, paths in ordered[keep:]:
            for path in paths:
                path.unlink()
                files_removed += 1
            filings_removed += 1

    result["dirs_scanned"] = dirs_scanned
    result["filings_removed"] = filings_removed
    result["files_removed"] = files_removed
    return result


def prune_http_cache(
    cache_path: str | Path,
    *,
    max_rows: int | None = DEFAULT_HTTP_MAX_ROWS,
    purge_expired: bool = True,
    vacuum: bool = True,
) -> dict[str, object]:
    """Purge expired / surplus cached responses and reclaim disk via VACUUM."""

    path = Path(cache_path)
    result: dict[str, object] = {
        "cache_path": str(path),
        "exists": path.exists(),
        "expired_removed": 0,
        "trimmed_removed": 0,
        "remaining": 0,
    }
    if not path.exists():
        return result

    cache = HttpCache(path)
    if purge_expired:
        result["expired_removed"] = cache.purge_expired()
    if max_rows is not None:
        result["trimmed_removed"] = cache.enforce_max_rows(max_rows)
    result["remaining"] = cache.count()
    if vacuum:
        _vacuum(path)
    return result


def run_storage_prune(
    *,
    docs_roots: list[str | Path] | None = None,
    cache_path: str | Path | None = None,
    keep_per_dir: int = DEFAULT_KEEP_PER_DIR,
    http_max_rows: int | None = DEFAULT_HTTP_MAX_ROWS,
) -> dict[str, object]:
    """Run document retention and HTTP-cache pruning in one pass."""

    roots = docs_roots if docs_roots is not None else ["local_docs/edinet", "local_docs/crawl"]
    docs = [prune_local_docs(root, keep_per_dir=keep_per_dir) for root in roots]
    cache = (
        prune_http_cache(cache_path, max_rows=http_max_rows)
        if cache_path is not None
        else None
    )
    total_files = sum(int(str(entry["files_removed"])) for entry in docs)
    _logger.info("storage prune removed files=%d", total_files)
    return {
        "keep_per_dir": keep_per_dir,
        "docs": docs,
        "http_cache": cache,
        "files_removed_total": total_files,
    }


def _group_by_doc_id(directory: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.name in _PROTECTED_NAMES:
            continue
        doc_id = path.name.split(".", 1)[0]
        groups.setdefault(doc_id, []).append(path)
    return groups


def _vacuum(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("VACUUM")
    finally:
        connection.close()
