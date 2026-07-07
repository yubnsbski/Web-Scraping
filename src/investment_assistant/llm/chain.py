"""Chain of guarded LLM services, tried in order with fallthrough.

Lets a role try a secondary provider first and fall through to the primary
service when the secondary is skipped, in cooldown, over budget, or erroring
(e.g. the planned local-LLM-first / Gemini-escalation chain).
"""

from __future__ import annotations

from collections.abc import Sequence

from investment_assistant.llm.service import LlmResponse, LlmServiceProtocol
from investment_assistant.observability import get_logger

_logger = get_logger("llm.chain")


class ChainLlmService:
    """Try each guarded service in order; return the first usable response.

    A response counts as usable when it is not ``skipped`` and its ``source``
    does not start with ``"fallback:"`` (i.e. it did not go through a guard's
    fallback path). The last service in the chain is always returned as-is,
    even if its response is itself skipped/fallback, so callers always get a
    response object.
    """

    def __init__(self, services: Sequence[LlmServiceProtocol]) -> None:
        if not services:
            msg = "ChainLlmService requires at least one service"
            raise ValueError(msg)
        self.services = list(services)

    def generate(self, *, task_type: str, prompt: str, priority: str = "normal") -> LlmResponse:
        """Generate text by trying each chained service in order."""

        last_index = len(self.services) - 1
        response: LlmResponse | None = None
        for index, service in enumerate(self.services):
            response = service.generate(task_type=task_type, prompt=prompt, priority=priority)
            if index == last_index or _is_usable(response):
                return response
            _logger.info(
                "llm chain fallthrough task=%s from_source=%s next=%d/%d",
                task_type,
                response.source,
                index + 2,
                len(self.services),
            )
        # Unreachable: the loop above always returns on its last iteration
        # because `services` is non-empty (enforced in __init__).
        assert response is not None
        return response


def _is_usable(response: LlmResponse) -> bool:
    return not response.skipped and not response.source.startswith("fallback:")
