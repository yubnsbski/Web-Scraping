"""Stage 3 (retrieve): RAG evidence retrieval, in the common ``EvidenceItem``
shape shared with a future web-search mode handler (O3).

``RagEvidenceRetriever`` mirrors, without duplicating any scoring logic, the
retrieval half of ``rag.answer.generate_rag_answer`` -- the same embedder
resolution + ``hybrid_search``/``search_chunks`` call chat.py's default
"answer" mode ultimately runs through ``cli.run_rag_answer``.

Deviation from blueprint section 2 (documented per Sprint B0 instructions):
today's production call graph (``generation.py``) still delegates whole-hog
to ``cli.run_rag_answer`` / ``cli.run_orchestrate_answer``, which perform
retrieval *and* generation atomically (the orchestrate path additionally
applies feedback/entity boosting and diversification that this retriever
does not replicate). Re-implementing that here and wiring it as the sole
retrieval path now would risk exactly the byte-identical-output regression
this sprint must avoid. This class is therefore a real, independently
tested seam (see its unit tests) that O1/O2 will wire into the live
pipeline once local generation needs evidence decoupled from the
Gemini-specific ``cli`` helpers -- it is not yet called by ``pipeline.py``.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.brainstem.contracts import EvidenceItem
from investment_assistant.rag.embeddings import resolve_embedder
from investment_assistant.rag.search import (
    SearchResult,
    hybrid_search,
    search_chunks,
    search_result_to_dict,
)
from investment_assistant.rag.store import RagStore, read_stored_embedder_name


class RagEvidenceRetriever:
    """Wraps the existing hybrid/keyword RAG search path as evidence items."""

    def retrieve(
        self,
        *,
        query: str,
        db_path: str | Path,
        limit: int = 5,
        hybrid: bool = False,
        alpha: float = 0.5,
    ) -> list[EvidenceItem]:
        embedder = resolve_embedder(read_stored_embedder_name(db_path))
        store = RagStore(db_path, embedder=embedder)
        results: list[SearchResult] = (
            hybrid_search(store, query=query, limit=limit, alpha=alpha, embedder=embedder)
            if hybrid
            else search_chunks(store, query=query, limit=limit)
        )
        return [_to_evidence_item(result) for result in results]


def _to_evidence_item(result: SearchResult) -> EvidenceItem:
    raw = search_result_to_dict(result)
    return EvidenceItem(
        source=result.source,
        text=result.text,
        citation=raw.get("citation"),
        score=result.score,
        raw=raw,
    )
