"""POST /api/chat/turn -- stateless multi-turn chat with history-aware RAG.

Thin webapi adapter (Sprint B0 refactor): all logic now lives in
:mod:`investment_assistant.brainstem`, the fixed pipeline every chat turn
passes through (see ``docs/brainstem.md`` section 2). This module exists
only so ``webapi/service.py``'s route registration
(``chat_api.chat_turn``) keeps working unchanged.
"""

from __future__ import annotations

from typing import Any

from investment_assistant.brainstem.webapi_adapter import chat_turn as _chat_turn

JsonDict = dict[str, Any]


def chat_turn(body: JsonDict) -> JsonDict:
    """Handle one stateless chat turn: resolve history, answer, normalize."""

    return _chat_turn(body)
