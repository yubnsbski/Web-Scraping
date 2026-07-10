"""Stage 4 (route): local vs Gemini routing decision.

v0 (this sprint, per blueprint section 3): deterministic heuristic,
identical to today's ``chat.py`` behavior -- ``detailed`` answer_mode always
orchestrates, everything else takes the guarded single-shot RAG path. No
local route exists yet (that is O1); until then every ``RouteDecision``
must have ``allow_context_rewrite=False`` (blueprint's absolute rule 2).

v1 (O2) will replace the body of ``decide`` with a lookup against an
offline-measured ``RoutingPolicy`` artifact; the ``RouteDecision`` contract
is designed to stay stable across that change.
"""

from __future__ import annotations

from investment_assistant.brainstem.contracts import BrainstemRequest, RouteDecision
from investment_assistant.brainstem.smalltalk import detect_small_talk


class QueryRouter:
    """Deterministic v0 router: ``detailed`` -> orchestrate, else Gemini chain.

    Small talk (greetings/thanks/acks -- see ``smalltalk.py``) is checked
    first, regardless of ``answer_mode``, since it never needs search or an
    LLM call either way.
    """

    def decide(self, request: BrainstemRequest) -> RouteDecision:
        latest = (request.messages[-1].get("content") or "") if request.messages else ""
        if detect_small_talk(latest) is not None:
            return RouteDecision(
                route="small_talk",
                allow_context_rewrite=False,
                reason="挨拶・相づちと判定したため、検索とLLMを使わずローカルで即答します",
            )
        if request.source_mode == "web":
            return RouteDecision(
                route="web_grounded",
                allow_context_rewrite=False,
                reason="Web検索モードが指定されたため、Google検索グラウンディングで回答します",
            )
        if request.answer_mode == "detailed":
            return RouteDecision(
                route="orchestrate",
                allow_context_rewrite=False,
                reason="詳細モードのため複数モデルのオーケストレーションを実行します",
            )
        return RouteDecision(
            route="gemini_chain",
            allow_context_rewrite=False,
            reason="通常モードのため検索根拠つきの単発回答を生成します",
        )
