"""Directory indexing helpers for local RAG documents."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH, RagStore

DEFAULT_INDEX_GLOB = "*.md"
_ALLOWED_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
_EXCLUDED_NAMES = frozenset({".env"})
_EXCLUDED_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_EXCLUDED_PARTS = frozenset({".cache", ".git", "__pycache__", ".venv", "venv"})


@dataclass(frozen=True)
class IndexedFileResult:
    """Result for one indexed local file."""

    source: str
    content_hash: str
    chunks_indexed: int


@dataclass(frozen=True)
class DirectoryIndexResult:
    """Aggregate result for directory indexing."""

    path: str
    glob: str
    recursive: bool
    db_path: str
    files_indexed: int
    chunks_indexed: int
    skipped_files: list[str]
    indexed_files: list[IndexedFileResult]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""

        return {
            "path": self.path,
            "glob": self.glob,
            "recursive": self.recursive,
            "db_path": self.db_path,
            "files_indexed": self.files_indexed,
            "chunks_indexed": self.chunks_indexed,
            "skipped_files": self.skipped_files,
            "indexed_files": [asdict(item) for item in self.indexed_files],
        }


def iter_indexable_files(
    path: str | Path,
    *,
    glob_pattern: str = DEFAULT_INDEX_GLOB,
    recursive: bool = False,
) -> list[Path]:
    """Return safe, text-like files under ``path`` matching the requested glob."""

    root = Path(path)
    if not root.exists():
        msg = f"Directory does not exist: {root}"
        raise FileNotFoundError(msg)
    if not root.is_dir():
        msg = f"Expected a directory: {root}"
        raise NotADirectoryError(msg)

    candidates: Iterable[Path]
    candidates = root.rglob(glob_pattern) if recursive else root.glob(glob_pattern)
    return sorted(
        (candidate for candidate in candidates if _is_indexable_file(candidate, root)),
        key=lambda item: str(item),
    )


def index_file(
    *,
    path: str | Path,
    store: RagStore,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> IndexedFileResult:
    """Index one local UTF-8 document into the provided RAG store."""

    document = load_document(path)
    chunks = chunk_text(
        source=document.source,
        text=document.text,
        content_hash=document.content_hash,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    chunks_indexed = store.upsert_document(document, chunks)
    return IndexedFileResult(
        source=document.source,
        content_hash=document.content_hash,
        chunks_indexed=chunks_indexed,
    )


def index_directory(
    *,
    path: str | Path,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    glob_pattern: str = DEFAULT_INDEX_GLOB,
    recursive: bool = False,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> DirectoryIndexResult:
    """Index all safe matching files in a directory without calling any LLM."""

    root = Path(path)
    store = RagStore(db_path)
    indexed_files: list[IndexedFileResult] = []
    skipped_files: list[str] = []

    for file_path in iter_indexable_files(root, glob_pattern=glob_pattern, recursive=recursive):
        try:
            indexed_files.append(
                index_file(
                    path=file_path,
                    store=store,
                    max_chars=max_chars,
                    overlap_chars=overlap_chars,
                )
            )
        except UnicodeDecodeError:
            skipped_files.append(str(file_path))

    return DirectoryIndexResult(
        path=str(root),
        glob=glob_pattern,
        recursive=recursive,
        db_path=str(db_path),
        files_indexed=len(indexed_files),
        chunks_indexed=sum(item.chunks_indexed for item in indexed_files),
        skipped_files=skipped_files,
        indexed_files=indexed_files,
    )


def _is_indexable_file(path: Path, root: Path) -> bool:
    if not path.is_file():
        return False
    if path.name in _EXCLUDED_NAMES:
        return False
    if path.suffix.lower() in _EXCLUDED_SUFFIXES:
        return False
    if path.suffix.lower() not in _ALLOWED_SUFFIXES:
        return False
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        relative_parts = path.parts
    return not any(part in _EXCLUDED_PARTS for part in relative_parts)
