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


class QueryRouter:
    """Deterministic v0 router: ``detailed`` -> orchestrate, else Gemini chain."""

    def decide(self, request: BrainstemRequest) -> RouteDecision:
        if request.answer_mode == "detailed":
            return RouteDecision(
                route="orchestrate",
                allow_context_rewrite=False,
                reason="detailed answer_mode requests multi-model orchestration",
            )
        return RouteDecision(
            route="gemini_chain",
            allow_context_rewrite=False,
            reason="default answer_mode routes to the guarded single-shot RAG answer",
        )
