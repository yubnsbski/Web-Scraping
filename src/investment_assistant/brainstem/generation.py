"""Stage 5 (generate): run the routed generation call.

Wraps the entry points ``chat.py`` called directly before the B0 refactor --
``cli.run_rag_answer`` (gemini_chain route), ``cli.run_orchestrate_answer``
(orchestrate route) -- plus ``cli.run_web_answer`` (web_grounded route, added
for the Web-search sprint). Behavior for the first two is untouched: same
keyword arguments, same fused retrieval+generation call (see ``retrieval.py``
module docstring for why retrieval is not split out of these calls yet).

``source_mode == "auto"`` is handled here rather than in ``router.py``:
the rag path (gemini_chain route) always runs first, and only when it comes
back with zero results does this stage make one ``run_web_answer`` call and
return that raw payload instead (with ``raw["auto_fallback"] = True``), so
the extra Web call only happens when local evidence is truly absent.

Injection seams (``rag_answer_fn`` / ``orchestrate_answer_fn`` /
``web_answer_fn``) exist for tests to supply fakes. When not given, the
``cli`` module attribute is looked up at call time (not bound at
construction time) so ``monkeypatch.setattr(cli, "run_orchestrate_answer",
...)`` -- used by existing chat tests -- keeps working unchanged.
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
        web_answer_fn: _AnswerFn | None = None,
    ) -> None:
        self._rag_answer_fn = rag_answer_fn
        self._orchestrate_answer_fn = orchestrate_answer_fn
        self._web_answer_fn = web_answer_fn

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
        if route.route == "web_grounded":
            web_fn = self._web_answer_fn or cli.run_web_answer
            raw = web_fn(
                query=resolved.prompt_question,
                call_real_api=request.call_real_api,
            )
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
            if request.source_mode == "auto" and not raw.get("results"):
                web_fn = self._web_answer_fn or cli.run_web_answer
                web_raw = dict(
                    web_fn(
                        query=resolved.prompt_question,
                        call_real_api=request.call_real_api,
                    )
                )
                web_raw["auto_fallback"] = True
                return GenerationAttempt(route=route.route, raw=web_raw)
        return GenerationAttempt(route=route.route, raw=raw)
