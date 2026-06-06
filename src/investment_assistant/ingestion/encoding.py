"""Charset detection for fetched HTML/text bodies.

Many Japanese sites still serve Shift_JIS or EUC-JP. Decoding everything as
UTF-8 produces mojibake (replacement characters) that silently corrupts the
text that later feeds RAG search and answers, so we detect the encoding from
the Content-Type header, then from an HTML ``<meta>`` charset, and finally fall
back through common Japanese encodings before a lossy UTF-8 decode.
"""

from __future__ import annotations

import re

_CONTENT_TYPE_CHARSET_RE = re.compile(r"charset\s*=\s*\"?([\w\-]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([\w\-]+)", re.IGNORECASE)
_FALLBACK_ENCODINGS = ("utf-8", "cp932", "euc_jp")


def detect_charset(body: bytes, content_type: str | None) -> str | None:
    """Return a normalized charset name from the header or HTML meta tag."""

    if content_type:
        match = _CONTENT_TYPE_CHARSET_RE.search(content_type)
        if match:
            return _normalize_charset(match.group(1))
    meta_match = _META_CHARSET_RE.search(body[:4096])
    if meta_match:
        return _normalize_charset(meta_match.group(1).decode("ascii", errors="ignore"))
    return None


def decode_body(body: bytes, content_type: str | None) -> str:
    """Decode ``body`` using the best-known charset, never raising on bad bytes."""

    charset = detect_charset(body, content_type)
    if charset:
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            pass
    for encoding in _FALLBACK_ENCODINGS:
        try:
            return body.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def _normalize_charset(name: str) -> str:
    normalized = name.strip().lower().replace("-", "_")
    if normalized in {"shift_jis", "sjis", "x_sjis", "shift_jisx0213", "ms932", "windows_31j"}:
        return "cp932"
    if normalized in {"euc_jp", "eucjp", "x_euc_jp"}:
        return "euc_jp"
    if normalized in {"utf8", "utf_8"}:
        return "utf-8"
    return normalized
