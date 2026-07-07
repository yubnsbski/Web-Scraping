"""``BrainstemService.run_turn`` -- the fixed pipeline funnel.

Chains the stages described in ``docs/brainstem.md`` section 2:
context -> route -> generate -> comply/assemble. (The "retrieve" stage,
``retrieval.RagEvidenceRetriever``, is not yet invoked here -- see that
module's docstring for why; ``generation.Generator`` still performs
retrieval internally via the existing ``cli`` helpers for this sprint.)
"""

from __future__ import annotations

from typing import Any

from investment_assistant.brainstem.compliance import ComplianceGuard
from investment_assistant.brainstem.context import ContextResolver
from investment_assistant.brainstem.contracts import BrainstemRequest
from investment_assistant.brainstem.generation import Generator
from investment_assistant.brainstem.router import QueryRouter

JsonDict = dict[str, Any]


class BrainstemService:
    """Runs one chat turn through the full brainstem pipeline."""

    def __init__(
        self,
        *,
        context_resolver: ContextResolver | None = None,
        router: QueryRouter | None = None,
        generator: Generator | None = None,
        compliance: ComplianceGuard | None = None,
    ) -> None:
        self._context_resolver = context_resolver or ContextResolver()
        self._router = router or QueryRouter()
        self._generator = generator or Generator()
        self._compliance = compliance or ComplianceGuard()

    def run_turn(self, request: BrainstemRequest) -> JsonDict:
        """Run one turn end to end, returning a ``chat.turn.v1`` payload.

        Raises ``ValueError`` (from :class:`ContextResolver`) when the
        message history is invalid -- callers at the transport boundary
        (see ``webapi_adapter.py``) translate that into their own error type.
        """

        resolved = self._context_resolver.resolve(request)
        route = self._router.decide(request)
        attempt = self._generator.generate(request=request, resolved=resolved, route=route)
        return self._compliance.assemble(request=request, resolved=resolved, attempt=attempt)
