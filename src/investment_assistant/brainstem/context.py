"""Stage 2 (context): resolve chat history into retrieval/prompt strings.

Wraps the existing pure-function heuristics in
:mod:`investment_assistant.rag.history` -- no logic is duplicated here, only
adapted to the :class:`~investment_assistant.brainstem.contracts.BrainstemRequest`
/ :class:`~investment_assistant.brainstem.contracts.ResolvedContext` contracts.
"""

from __future__ import annotations

from investment_assistant.brainstem.contracts import BrainstemRequest, ResolvedContext
from investment_assistant.rag.history import build_retrieval_query, standalone_question


class ContextResolver:
    """Resolves a request's message history into a :class:`ResolvedContext`.

    Raises ``ValueError`` (propagated verbatim from ``rag.history``) when the
    latest turn is missing, blank, or not from the user -- the webapi adapter
    translates that into an ``ApiError``.
    """

    def resolve(self, request: BrainstemRequest) -> ResolvedContext:
        messages = [dict(message) for message in request.messages]
        retrieval_query = build_retrieval_query(messages)
        prompt_question = standalone_question(messages)
        return ResolvedContext(
            original_query=_latest_user_content(messages),
            retrieval_query=retrieval_query,
            prompt_question=prompt_question,
        )


def _latest_user_content(messages: list[dict[str, str]]) -> str:
    latest = messages[-1]
    content = latest.get("content")
    return content if isinstance(content, str) else ""
