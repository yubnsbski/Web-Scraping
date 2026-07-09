"""Frozen data contracts shared by every brainstem pipeline stage.

These mirror ``docs/brainstem.md`` section 2's stage diagram. Fields model
only what :mod:`investment_assistant.webapi.chat` actually uses today
(Sprint B0 is a pure refactor); ``source_mode`` and the ``local_ollama``
route are reserved literals for O1/O3, not yet reachable in v0.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

# answer: single-shot guarded RAG answer. detailed: multi-model orchestration.
AnswerMode = Literal["answer", "detailed"]

# rag: local accumulated-data search (the only mode implemented in v0).
# web/auto are reserved literals for O3 (per blueprint section 2/6).
SourceMode = Literal["rag", "web", "auto"]

# gemini_chain: guarded single-shot RAG answer (cli.run_rag_answer).
# orchestrate: multi-model orchestration (cli.run_orchestrate_answer).
# small_talk: local, no-search, no-LLM reply to greetings/thanks/acks.
# local_ollama is reserved for O1; unreachable until QueryRouter grows it.
RouteName = Literal["gemini_chain", "orchestrate", "small_talk", "local_ollama"]


@dataclass(frozen=True)
class BrainstemRequest:
    """A single normalized chat turn request (the "ingest" stage's output)."""

    messages: tuple[Mapping[str, str], ...]
    answer_mode: AnswerMode
    source_mode: SourceMode
    db_path: str
    limit: int
    call_real_api: bool
    hybrid: bool
    alpha: float


@dataclass(frozen=True)
class ResolvedContext:
    """History resolved into the two strings the rest of the pipeline uses.

    CACHE INVARIANT (blueprint section 2, absolute rule 1): conversation
    history may only ever influence ``retrieval_query``. ``prompt_question``
    is a deterministic function of the latest turn plus carried entity
    tokens only (see ``rag.history.standalone_question``), and only
    ``prompt_question`` may ever reach a Gemini prompt -- this is what keeps
    the Gemini free-tier cache/budget guard effective across follow-up turns.
    """

    original_query: str
    retrieval_query: str
    prompt_question: str


@dataclass(frozen=True)
class EvidenceItem:
    """One retrieved RAG chunk, in the common shape mode handlers produce.

    ``raw`` retains the full untyped dict (as produced by
    ``rag.search.search_result_to_dict``) so downstream assembly can stay
    byte-identical to today's response shape without this contract needing
    to model every existing/future key.
    """

    source: str
    text: str
    citation: Mapping[str, Any] | None
    score: float | None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteDecision:
    """QueryRouter's verdict for one turn."""

    route: RouteName
    allow_context_rewrite: bool
    reason: str

    def __post_init__(self) -> None:
        # Absolute rule 2: only local routes may ever rewrite context/query.
        if self.route != "local_ollama" and self.allow_context_rewrite:
            raise ValueError(
                "allow_context_rewrite may only be true for the local_ollama route"
            )


@dataclass(frozen=True)
class GenerationAttempt:
    """Output of the generate stage: the route taken and its raw payload.

    ``raw`` is passed through unchanged from ``cli.run_rag_answer`` /
    ``cli.run_orchestrate_answer`` -- see ``generation.py`` -- so
    ``ComplianceGuard`` can normalize it exactly as ``chat.py`` did before
    this refactor.
    """

    route: RouteName
    raw: Mapping[str, Any]
