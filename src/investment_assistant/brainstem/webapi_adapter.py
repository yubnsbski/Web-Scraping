"""Stage 1 (ingest) + transport boundary: JSON body <-> ``BrainstemRequest``.

``webapi/chat.py`` is now a thin adapter that calls ``chat_turn`` here. This
module owns the only ``ApiError`` dependency in the brainstem package (the
rest of the package is transport-agnostic) and the input-normalization
helpers that used to live directly in ``webapi/chat.py``.
"""

from __future__ import annotations

import math
from typing import Any

from investment_assistant.brainstem.contracts import BrainstemRequest
from investment_assistant.brainstem.pipeline import BrainstemService
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH
from investment_assistant.webapi.errors import ApiError

JsonDict = dict[str, Any]

_DEFAULT_LIMIT = 6
_MAX_LIMIT = 16
_MAX_MESSAGES = 200
_DEFAULT_ALPHA = 0.5
_VALID_ANSWER_MODES = ("answer", "detailed")


def chat_turn(body: JsonDict) -> JsonDict:
    """Handle one stateless chat turn: ingest, run the pipeline, return JSON."""

    request = _to_request(body)
    try:
        return BrainstemService().run_turn(request)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc


def _to_request(body: JsonDict) -> BrainstemRequest:
    messages = _require_messages(body)
    answer_mode = str(body.get("mode") or "answer")
    if answer_mode not in _VALID_ANSWER_MODES:
        raise ApiError(f"invalid mode: {answer_mode!r}, expected one of {_VALID_ANSWER_MODES}")

    return BrainstemRequest(
        messages=tuple(dict(message) for message in messages),
        answer_mode=answer_mode,  # type: ignore[arg-type]  # validated above
        source_mode="rag",
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_clamp_limit(body.get("limit")),
        call_real_api=_as_bool(body.get("call_real_api"), False),
        hybrid=_as_bool(body.get("hybrid"), True),
        alpha=_clamp_alpha(body.get("alpha")),
    )


def _require_messages(body: JsonDict) -> list[dict[str, Any]]:
    raw = body.get("messages")
    if not isinstance(raw, list) or not raw:
        raise ApiError("messages is required and must be a non-empty list")
    if len(raw) > _MAX_MESSAGES:
        raise ApiError(f"messages is too long: max {_MAX_MESSAGES} messages")
    messages: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError("each message must be an object with role/content")
        messages.append(item)
    return messages


def _clamp_limit(value: object) -> int:
    limit = _as_int(value, _DEFAULT_LIMIT)
    if limit < 1:
        limit = 1
    return min(limit, _MAX_LIMIT)


def _clamp_alpha(value: object) -> float:
    """Parse alpha, defaulting non-numeric/non-finite input, clamped to [0, 1]."""

    alpha = _as_float(value, _DEFAULT_ALPHA)
    if not math.isfinite(alpha):
        return _DEFAULT_ALPHA
    return min(max(alpha, 0.0), 1.0)


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
