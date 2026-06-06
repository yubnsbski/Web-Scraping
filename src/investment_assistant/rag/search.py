"""Local keyword search over stored RAG chunks."""

from __future__ import annotations

from dataclasses import dataclass, field

from investment_assistant.rag.store import RagStore, StoredChunk
from investment_assistant.rag.tokenize import tokenize

_CONTEXT_METADATA_KEYS = ("source_url", "fetched_at", "status_code", "content_type")
DEFAULT_MAX_CONTEXT_CHARS = 6000


@dataclass(frozen=True)
class SearchResult:
    """Scored chunk search result."""

    chunk_id: str
    source: str
    chunk_index: int
    score: float
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


def search_chunks(store: RagStore, *, query: str, limit: int = 5) -> list[SearchResult]:
    """Search chunks using FTS5 BM25 ranking, falling back to keyword scoring.

    Exact-duplicate chunk texts (which overlapping chunking can produce) are
    collapsed so near-identical passages do not crowd out other sources.
    """

    terms = tokenize(query)
    if not terms or limit <= 0:
        return []

    bm25_hits = store.search_bm25(terms, limit=limit * 4)
    if bm25_hits:
        results = [
            SearchResult(
                chunk_id=chunk.chunk_id,
                source=chunk.source,
                chunk_index=chunk.chunk_index,
                score=score,
                text=chunk.text,
                metadata=chunk.metadata,
            )
            for chunk, score in bm25_hits
        ]
    else:
        results = _keyword_search(store, terms)

    return _dedupe_by_text(results)[:limit]


def _keyword_search(store: RagStore, terms: list[str]) -> list[SearchResult]:
    """Fallback keyword scoring used when FTS5 is unavailable."""

    results: list[SearchResult] = []
    for chunk in store.list_chunks():
        score = _score_chunk(chunk, terms)
        if score > 0:
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    source=chunk.source,
                    chunk_index=chunk.chunk_index,
                    score=float(score),
                    text=chunk.text,
                    metadata=chunk.metadata,
                )
            )
    return sorted(results, key=lambda result: (-result.score, result.source, result.chunk_index))


def _dedupe_by_text(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        key = " ".join(result.text.split())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def build_answer_context(
    results: list[SearchResult],
    *,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    """Build a citation-friendly context block within a character budget.

    The budget caps how much retrieved text is sent to the LLM so prompts stay
    within token limits and cost, keeping the highest-ranked passages first.
    """

    if not results:
        return "関連するローカル文書チャンクは見つかりませんでした。"
    blocks: list[str] = []
    used_chars = 0
    for index, result in enumerate(results, 1):
        header = _format_context_header(index, result)
        remaining = max_context_chars - used_chars - len(header) - 1
        if remaining <= 0:
            break
        body = result.text if len(result.text) <= remaining else result.text[:remaining].rstrip()
        block = f"{header}\n{body}"
        blocks.append(block)
        used_chars += len(block) + 2
    return "\n\n".join(blocks)


def _format_context_header(index: int, result: SearchResult) -> str:
    base = f"[{index}] source={result.source} chunk={result.chunk_index} score={result.score}"
    metadata = " ".join(
        f"{key}={result.metadata[key]}"
        for key in _CONTEXT_METADATA_KEYS
        if result.metadata.get(key)
    )
    return f"{base} {metadata}" if metadata else base


def _score_chunk(chunk: StoredChunk, terms: list[str]) -> int:
    text = chunk.text.lower()
    return sum(text.count(term) for term in terms)
