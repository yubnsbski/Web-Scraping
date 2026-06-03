"""Local keyword search over stored RAG chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from investment_assistant.rag.store import RagStore, StoredChunk

_TOKEN_RE = re.compile(r"[\w一-龯ぁ-んァ-ン]+", re.UNICODE)


@dataclass(frozen=True)
class SearchResult:
    """Scored chunk search result."""

    chunk_id: str
    source: str
    chunk_index: int
    score: int
    text: str


def search_chunks(store: RagStore, *, query: str, limit: int = 5) -> list[SearchResult]:
    """Search chunks with simple local keyword scoring."""

    terms = _tokenize(query)
    if not terms or limit <= 0:
        return []
    results: list[SearchResult] = []
    for chunk in store.list_chunks():
        score = _score_chunk(chunk, terms)
        if score > 0:
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    source=chunk.source,
                    chunk_index=chunk.chunk_index,
                    score=score,
                    text=chunk.text,
                )
            )
    return sorted(results, key=lambda result: (-result.score, result.source, result.chunk_index))[
        :limit
    ]


def build_answer_context(results: list[SearchResult]) -> str:
    """Build a citation-friendly context block without calling an LLM."""

    if not results:
        return "関連するローカル文書チャンクは見つかりませんでした。"
    blocks = []
    for index, result in enumerate(results, 1):
        blocks.append(
            "\n".join(
                (
                    (
                        f"[{index}] source={result.source} "
                        f"chunk={result.chunk_index} score={result.score}"
                    ),
                    result.text,
                )
            )
        )
    return "\n\n".join(blocks)


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text) if match.group(0).strip()]


def _score_chunk(chunk: StoredChunk, terms: list[str]) -> int:
    text = chunk.text.lower()
    return sum(text.count(term) for term in terms)
