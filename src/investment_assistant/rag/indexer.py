"""Directory indexing helpers for local RAG documents.

This is the single source of truth for walking a directory and indexing safe,
text-like files into the local RAG store. The CLI delegates here so file
selection rules live in one place.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH, RagStore

INDEX_EXTENSIONS = frozenset({".md", ".markdown", ".txt"})
EXCLUDED_DIRS = frozenset(
    {".cache", ".git", "__pycache__", ".venv", "venv", "artifacts", "data", "models", "rag_index"}
)
EXCLUDED_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})


def iter_indexable_files(root: Path) -> list[Path]:
    """Return supported, text-like files under ``root`` in stable order."""

    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and is_supported_file(root, path)
    ]


def is_supported_file(root: Path, path: Path) -> bool:
    """Return whether ``path`` is a safe, supported document to index."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
        return False
    if path.name.startswith(".env"):
        return False
    suffix = path.suffix.lower()
    if suffix in EXCLUDED_SUFFIXES:
        return False
    return suffix in INDEX_EXTENSIONS


def index_directory(
    *,
    path: str | Path,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> dict[str, object]:
    """Recursively index supported local files into the RAG store.

    Returns a JSON-friendly summary. Unsupported files and files that cannot be
    decoded as UTF-8 are reported under ``skipped_files``.
    """

    root = Path(path)
    if not root.is_dir():
        msg = f"path must be a directory: {root}"
        raise ValueError(msg)

    store = RagStore(db_path)
    skipped_paths = [
        candidate
        for candidate in sorted(root.rglob("*"))
        if candidate.is_file() and not is_supported_file(root, candidate)
    ]
    indexed_sources: list[str] = []
    total_chunks = 0
    for file_path in iter_indexable_files(root):
        try:
            document = load_document(file_path)
        except (OSError, UnicodeDecodeError):
            skipped_paths.append(file_path)
            continue
        chunks = chunk_text(
            source=document.source,
            text=document.text,
            content_hash=document.content_hash,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        total_chunks += store.upsert_document(document, chunks)
        indexed_sources.append(document.source)

    return {
        "source_dir": str(root),
        "db_path": str(db_path),
        "files_indexed": len(indexed_sources),
        "chunks_indexed": total_chunks,
        "indexed_sources": indexed_sources,
        "skipped_files": [str(file_path) for file_path in skipped_paths],
    }
