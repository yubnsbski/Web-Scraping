"""Text chunking utilities for local RAG indexing."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from investment_assistant.ingestion.encoding import decode_body
from investment_assistant.ingestion.html_extract import extract_text_from_html

TEXT_DOCUMENT_EXTENSIONS = frozenset({".md", ".markdown", ".txt"})
HTML_DOCUMENT_EXTENSIONS = frozenset({".html", ".htm"})
CSV_DOCUMENT_EXTENSIONS = frozenset({".csv"})
PDF_DOCUMENT_EXTENSIONS = frozenset({".pdf"})
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {
        *TEXT_DOCUMENT_EXTENSIONS,
        *HTML_DOCUMENT_EXTENSIONS,
        *CSV_DOCUMENT_EXTENSIONS,
        *PDF_DOCUMENT_EXTENSIONS,
    }
)

_PDF_STREAM_RE = re.compile(rb"<<(?P<dict>.*?)>>\s*stream\r?\n(?P<data>.*?)\r?\nendstream", re.S)
_PDF_LITERAL_RE = re.compile(rb"\((?:\\.|[^\\()])*\)")
_PDF_HEX_RE = re.compile(rb"<([0-9A-Fa-f\s]{4,})>")


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
    """Load a local RAG document and optional front matter.

    Markdown/text keep their front matter behavior. HTML, CSV, and simple text
    PDFs are converted to searchable plain text using only local deterministic
    parsers, so registration does not depend on an LLM or network access.
    """

    document_path = Path(path)
    raw_bytes = document_path.read_bytes()
    suffix = document_path.suffix.lower()
    if suffix in HTML_DOCUMENT_EXTENSIONS:
        text = extract_text_from_html(decode_body(raw_bytes, "text/html"))
        metadata = {"file_type": "html"}
    elif suffix in CSV_DOCUMENT_EXTENSIONS:
        text = _csv_to_searchable_text(decode_body(raw_bytes, "text/csv"))
        metadata = {"file_type": "csv"}
    elif suffix in PDF_DOCUMENT_EXTENSIONS:
        text = _extract_text_from_pdf(raw_bytes)
        metadata = {"file_type": "pdf"}
    else:
        raw_text = _decode_text_body(raw_bytes)
        text, metadata = split_front_matter(raw_text)
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
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


def _csv_to_searchable_text(text: str) -> str:
    reader = csv.reader(io.StringIO(text))
    rows = [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return ""
    header = rows[0]
    if not header:
        return text.strip()
    lines = [f"CSV columns: {', '.join(header)}"]
    for row_number, row in enumerate(rows[1:], 1):
        pairs = []
        for index, value in enumerate(row):
            key = header[index] if index < len(header) and header[index] else f"column_{index + 1}"
            if value:
                pairs.append(f"{key}={value}")
        if pairs:
            lines.append(f"row {row_number}: " + "; ".join(pairs))
    if len(lines) == 1:
        lines.extend(",".join(row) for row in rows[1:])
    return "\n".join(lines)


def _decode_text_body(body: bytes) -> str:
    for encoding in ("utf-8", "cp932", "euc_jp"):
        try:
            decoded = body.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in decoded:
            continue
        return decoded
    raise UnicodeDecodeError("utf-8", body, 0, min(1, len(body)), "unsupported text encoding")


def _extract_text_from_pdf(body: bytes) -> str:
    candidates: list[bytes] = []
    for match in _PDF_STREAM_RE.finditer(body):
        stream = match.group("data").strip(b"\r\n")
        if b"/FlateDecode" in match.group("dict"):
            try:
                stream = zlib.decompress(stream)
            except zlib.error:
                continue
        candidates.append(stream)
    if not candidates:
        candidates.append(body)

    parts: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for raw_literal in _PDF_LITERAL_RE.findall(candidate):
            text = _decode_pdf_literal(raw_literal[1:-1])
            if _is_useful_pdf_text(text) and text not in seen:
                parts.append(text)
                seen.add(text)
        for raw_hex in _PDF_HEX_RE.findall(candidate):
            text = _decode_pdf_hex(raw_hex)
            if _is_useful_pdf_text(text) and text not in seen:
                parts.append(text)
                seen.add(text)
    return "\n".join(parts)


def _decode_pdf_literal(raw: bytes) -> str:
    output = bytearray()
    index = 0
    while index < len(raw):
        char = raw[index]
        if char != 0x5C:
            output.append(char)
            index += 1
            continue
        index += 1
        if index >= len(raw):
            break
        escaped = raw[index]
        if escaped in b"nrtbf":
            output.append(
                {
                    ord("n"): 10,
                    ord("r"): 13,
                    ord("t"): 9,
                    ord("b"): 8,
                    ord("f"): 12,
                }[escaped]
            )
            index += 1
            continue
        if escaped in b"()\\":
            output.append(escaped)
            index += 1
            continue
        if 48 <= escaped <= 55:
            octal = bytes([escaped])
            index += 1
            while index < len(raw) and len(octal) < 3 and 48 <= raw[index] <= 55:
                octal += bytes([raw[index]])
                index += 1
            output.append(int(octal, 8))
            continue
        output.append(escaped)
        index += 1
    return _decode_pdf_text_bytes(bytes(output))


def _decode_pdf_hex(raw: bytes) -> str:
    compact = b"".join(raw.split())
    if len(compact) % 2:
        compact += b"0"
    try:
        return _decode_pdf_text_bytes(bytes.fromhex(compact.decode("ascii")))
    except ValueError:
        return ""


def _decode_pdf_text_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace").strip()
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace").strip()
    if len(raw) >= 4 and raw[0::2].count(0) > len(raw) // 4:
        return raw.decode("utf-16-be", errors="replace").strip()
    for encoding in ("utf-8", "cp932", "latin-1"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def _is_useful_pdf_text(text: str) -> bool:
    normalized = " ".join(text.split())
    if len(normalized) < 2:
        return False
    return any(char.isalnum() for char in normalized)


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
