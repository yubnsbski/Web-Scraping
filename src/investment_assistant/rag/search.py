"""Local keyword search over stored RAG chunks."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from investment_assistant.rag.embeddings import Embedder, HashingEmbedder, cosine
from investment_assistant.rag.store import RagStore, StoredChunk
from investment_assistant.rag.tokenize import tokenize

_CONTEXT_METADATA_KEYS = ("source_url", "fetched_at", "status_code", "content_type")
DEFAULT_MAX_CONTEXT_CHARS = 10000
DEFAULT_HYBRID_ALPHA = 0.5
# Near-duplicate threshold (token Jaccard) for diversity selection.
_DUPLICATE_JACCARD = 0.85


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


def hybrid_search(
    store: RagStore,
    *,
    query: str,
    limit: int = 5,
    embedder: Embedder | None = None,
    alpha: float = DEFAULT_HYBRID_ALPHA,
) -> list[SearchResult]:
    """Combine lexical BM25 and semantic embedding scores.

    Lexical and semantic scores are each min-max normalized to [0, 1] across the
    candidate set, then blended as ``alpha * semantic + (1 - alpha) * lexical``.
    ``alpha=0`` is pure lexical (BM25), ``alpha=1`` is pure semantic.
    """

    if not 0.0 <= alpha <= 1.0:
        msg = "alpha must be between 0 and 1"
        raise ValueError(msg)
    terms = tokenize(query)
    if not terms or limit <= 0:
        return []
    chosen_embedder = embedder if embedder is not None else HashingEmbedder()

    lexical = {chunk.chunk_id: score for chunk, score in store.search_bm25(terms, limit=limit * 5)}
    query_vector = chosen_embedder.embed([query])[0]
    embedded = store.iter_embeddings()
    semantic = {chunk.chunk_id: cosine(query_vector, vector) for chunk, vector in embedded}
    chunks_by_id = {chunk.chunk_id: chunk for chunk, _ in embedded}

    lexical_norm = _min_max_normalize(lexical)
    semantic_norm = _min_max_normalize(semantic)
    candidate_ids = set(lexical) | set(semantic)

    results: list[SearchResult] = []
    for chunk_id in candidate_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        combined = alpha * semantic_norm.get(chunk_id, 0.0) + (1 - alpha) * lexical_norm.get(
            chunk_id, 0.0
        )
        if combined <= 0:
            continue
        results.append(
            SearchResult(
                chunk_id=chunk.chunk_id,
                source=chunk.source,
                chunk_index=chunk.chunk_index,
                score=round(combined, 6),
                text=chunk.text,
                metadata=chunk.metadata,
            )
        )
    ranked = sorted(results, key=lambda result: (-result.score, result.source, result.chunk_index))
    return _dedupe_by_text(ranked)[:limit]


def _min_max_normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = scores.values()
    lowest = min(values)
    highest = max(values)
    if highest == lowest:
        return {key: 1.0 for key in scores}
    span = highest - lowest
    return {key: (value - lowest) / span for key, value in scores.items()}


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


def boost_by_feedback(
    results: list[SearchResult],
    source_scores: dict[str, int],
    *,
    weight: float = 0.15,
) -> list[SearchResult]:
    """Gently re-rank results by accumulated user feedback per source.

    A source's net feedback (👍 = +1, 👎 = -1) nudges its score by at most
    ``±weight`` (bounded via tanh), so liked sources float up and disliked ones
    sink — without letting one rating dominate lexical/semantic relevance.
    Returns a new score-sorted list; with no feedback the order is unchanged.
    """

    if not source_scores or weight <= 0:
        return results
    adjusted: list[SearchResult] = []
    for result in results:
        net = source_scores.get(result.source, 0)
        factor = 1 + weight * math.tanh(net / 3)
        adjusted.append(replace(result, score=result.score * factor))
    adjusted.sort(key=lambda result: (-result.score, result.source, result.chunk_index))
    return adjusted


def diversify_results(
    results: list[SearchResult],
    *,
    limit: int,
    max_per_source: int = 3,
) -> list[SearchResult]:
    """Select a diverse, de-duplicated top-``limit`` from a larger ranked pool.

    Drops near-duplicate passages and caps how many chunks any single source can
    contribute, so the context spans more documents instead of many redundant
    passages from one filing. Over-cap chunks are only used to backfill when the
    capped pass cannot reach ``limit``. Input is assumed score-ordered.
    """

    if limit <= 0:
        return []

    selected: list[SearchResult] = []
    deferred: list[SearchResult] = []
    per_source: dict[str, int] = {}
    fingerprints: list[tuple[str, frozenset[str]]] = []

    def _is_duplicate(result: SearchResult) -> bool:
        tokens = frozenset(tokenize(result.text))
        if not tokens:
            return False
        for source, prior in fingerprints:
            if source != result.source or not prior:
                continue
            overlap = len(tokens & prior) / len(tokens | prior)
            if overlap >= _DUPLICATE_JACCARD:
                return True
        return False

    def _accept(result: SearchResult) -> None:
        selected.append(result)
        per_source[result.source] = per_source.get(result.source, 0) + 1
        fingerprints.append((result.source, frozenset(tokenize(result.text))))

    for result in results:
        if len(selected) >= limit:
            break
        if _is_duplicate(result):
            continue
        if per_source.get(result.source, 0) >= max_per_source:
            deferred.append(result)
            continue
        _accept(result)

    for result in deferred:
        if len(selected) >= limit:
            break
        if not _is_duplicate(result):
            _accept(result)

    return selected


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
