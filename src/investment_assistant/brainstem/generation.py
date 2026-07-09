"""Stage 5 (generate): run the routed generation call.

Wraps the two existing entry points ``chat.py`` called directly before this
refactor -- ``cli.run_rag_answer`` (gemini_chain route) and
``cli.run_orchestrate_answer`` (orchestrate route). Behavior is untouched:
same keyword arguments, same fused retrieval+generation call (see
``retrieval.py`` module docstring for why retrieval is not split out of
these calls yet).

Injection seams (``rag_answer_fn`` / ``orchestrate_answer_fn``) exist for
tests to supply fakes. When not given, the ``cli`` module attribute is
looked up at call time (not bound at construction time) so
``monkeypatch.setattr(cli, "run_orchestrate_answer", ...)`` -- used by
existing chat tests -- keeps working unchanged.
"""

from __future__ import annotations

from typing import Any, Protocol

from investment_assistant import cli
from investment_assistant.brainstem.contracts import (
    BrainstemRequest,
    GenerationAttempt,
    ResolvedContext,
    RouteDecision,
)
from investment_assistant.brainstem.smalltalk import detect_small_talk, small_talk_reply

JsonDict = dict[str, Any]


class _AnswerFn(Protocol):
    def __call__(self, **kwargs: Any) -> JsonDict: ...


class Generator:
    """Runs the routed generation call and wraps its raw payload."""

    def __init__(
        self,
        *,
        rag_answer_fn: _AnswerFn | None = None,
        orchestrate_answer_fn: _AnswerFn | None = None,
    ) -> None:
        self._rag_answer_fn = rag_answer_fn
        self._orchestrate_answer_fn = orchestrate_answer_fn

    def generate(
        self,
        *,
        request: BrainstemRequest,
        resolved: ResolvedContext,
        route: RouteDecision,
    ) -> GenerationAttempt:
        if route.route == "small_talk":
            latest = (request.messages[-1].get("content") or "") if request.messages else ""
            category = detect_small_talk(latest) or "ack"
            raw = {
                "answer": small_talk_reply(category),
                "results": [],
                "small_talk": True,
                "llm": {
                    "source": "local_small_talk",
                    "warning": False,
                    "skipped": True,
                    "cache_key": None,
                },
            }
            return GenerationAttempt(route=route.route, raw=raw)
        if route.route == "orchestrate":
            orchestrate_fn = self._orchestrate_answer_fn or cli.run_orchestrate_answer
            raw = orchestrate_fn(
                query=resolved.prompt_question,
                search_query=resolved.retrieval_query,
                db_path=request.db_path,
                limit=request.limit,
                hybrid=request.hybrid,
                alpha=request.alpha,
                call_real_api=request.call_real_api,
            )
        else:
            rag_fn = self._rag_answer_fn or cli.run_rag_answer
            raw = rag_fn(
                query=resolved.prompt_question,
                db_path=request.db_path,
                limit=request.limit,
                call_real_api=request.call_real_api,
                retrieval_query=resolved.retrieval_query,
                hybrid=request.hybrid,
                alpha=request.alpha,
            )
        return GenerationAttempt(route=route.route, raw=raw)
