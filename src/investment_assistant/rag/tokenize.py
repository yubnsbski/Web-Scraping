"""Shared tokenization for local RAG indexing and search.

Japanese text has no spaces, so a naive word tokenizer treats a whole sentence
as one token and misses partial matches. We emit ASCII/numeric word tokens plus
CJK unigrams and bigrams. The same function is used at index time (joined with
spaces and stored in an FTS5 ``unicode61`` column) and at query time, so a query
like ``投資判断`` matches a document containing ``投資判断`` via the ``投資`` /
``判断`` bigrams while still allowing two-character lookups.
"""

from __future__ import annotations

import re
import unicodedata

_ASCII_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(
    r"[぀-ゟ゠-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]+"
)


def tokenize(text: str) -> list[str]:
    """Return search tokens: lowercased ASCII words plus CJK uni/bigrams.

    Full-width Latin/digit characters (e.g. ``ＫＤＤＩ``) are NFKC-normalized
    to their ASCII equivalents (``KDDI``) before extraction, so full-width and
    half-width spellings of the same brand/ticker tokenize identically.
    """

    normalized = unicodedata.normalize("NFKC", text)
    lowered = normalized.lower()
    tokens: list[str] = _ASCII_WORD_RE.findall(lowered)
    for run in _CJK_RUN_RE.findall(lowered):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def tokens_to_index_text(text: str) -> str:
    """Return a space-joined token string for storage in an FTS5 column."""

    return " ".join(tokenize(text))
