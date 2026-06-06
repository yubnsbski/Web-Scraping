"""Text chunking utilities for local RAG indexing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Document:
    """Source document metadata and text."""

    source: str
    text: str
    content_hash: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TextChunk:
    """A deterministic text chunk with source metadata."""

    chunk_id: str
    source: str
    chunk_index: int
    text: str
    content_hash: str


def load_document(path: str | Path) -> Document:
    """Load a local UTF-8 text/Markdown document and optional front matter."""

    document_path = Path(path)
    raw_text = document_path.read_text(encoding="utf-8")
    text, metadata = split_front_matter(raw_text)
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return Document(
        source=str(document_path),
        text=text,
        content_hash=content_hash,
        metadata=metadata,
    )


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


def split_front_matter(text: str) -> tuple[str, dict[str, str]]:
    """Return body text and simple YAML-like front matter metadata."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        return text, {}

    lines = normalized.split("\n")
    end_index = _front_matter_end_index(lines)
    if end_index is None:
        return text, {}

    metadata = _parse_front_matter_lines(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    if body.startswith("\n"):
        body = body[1:]
    return body, metadata


def _front_matter_end_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return index
    return None


def _parse_front_matter_lines(lines: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in lines:
        key, separator, raw_value = line.partition(":")
        if not separator:
            continue
        normalized_key = key.strip()
        if not normalized_key:
            continue
        metadata[normalized_key] = _unquote_front_matter_value(raw_value.strip())
    return metadata


def _unquote_front_matter_value(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('\\"', '"')
    return value
