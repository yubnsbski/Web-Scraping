"""Text chunking utilities for local RAG indexing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Document:
    """Source document metadata and text."""

    source: str
    text: str
    content_hash: str


@dataclass(frozen=True)
class TextChunk:
    """A deterministic text chunk with source metadata."""

    chunk_id: str
    source: str
    chunk_index: int
    text: str
    content_hash: str


def load_document(path: str | Path) -> Document:
    """Load a local UTF-8 text/Markdown document."""

    document_path = Path(path)
    text = document_path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Document(source=str(document_path), text=text, content_hash=content_hash)


def chunk_text(
    *,
    source: str,
    text: str,
    content_hash: str | None = None,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> list[TextChunk]:
    """Split text into deterministic overlapping chunks."""

    if max_chars <= 0:
        msg = "max_chars must be positive"
        raise ValueError(msg)
    if overlap_chars < 0:
        msg = "overlap_chars must be non-negative"
        raise ValueError(msg)
    if overlap_chars >= max_chars:
        msg = "overlap_chars must be smaller than max_chars"
        raise ValueError(msg)

    normalized = _normalize_text(text)
    if not normalized:
        return []
    digest = content_hash or hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    chunks: list[TextChunk] = []
    start = 0
    chunk_index = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            boundary = normalized.rfind("\n", start, end)
            if boundary <= start:
                boundary = normalized.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunk_text_value = normalized[start:end].strip()
        if chunk_text_value:
            chunk_id = _chunk_id(source, digest, chunk_index, chunk_text_value)
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    source=source,
                    chunk_index=chunk_index,
                    text=chunk_text_value,
                    content_hash=digest,
                )
            )
            chunk_index += 1
        if end >= len(normalized):
            break
        start = max(0, end - overlap_chars)
    return chunks


def _normalize_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip()


def _chunk_id(source: str, content_hash: str, chunk_index: int, text: str) -> str:
    raw = f"{source}\0{content_hash}\0{chunk_index}\0{text}".encode()
    return hashlib.sha256(raw).hexdigest()
