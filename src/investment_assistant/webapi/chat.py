"""POST /api/chat/turn -- stateless multi-turn chat with history-aware RAG.

The client resends the full message history on every turn (no server-side
session state). This module resolves that history into a retrieval string
and a standalone question (:mod:`investment_assistant.rag.history`), routes
to either the guarded single-shot RAG answer path or the multi-model
orchestration path, and normalizes either result into one stable response
shape (contract ``chat.turn.v1``).
"""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from investment_assistant import cli
from investment_assistant.llm.factory import DEFAULT_GEMINI_CONFIG_PATH
from investment_assistant.rag.answer import DISCLAIMER as RAG_DISCLAIMER
from investment_assistant.rag.history import build_retrieval_query, standalone_question
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH
from investment_assistant.webapi.errors import ApiError

JsonDict = dict[str, Any]

CONTRACT_VERSION = "chat.turn.v1"
_DEFAULT_LIMIT = 6
_MAX_LIMIT = 16
_MAX_MESSAGES = 200
_DEFAULT_ALPHA = 0.5
_VALID_MODES = ("answer", "detailed")


def chat_turn(body: JsonDict) -> JsonDict:
    """Handle one stateless chat turn: resolve history, answer, normalize."""

    messages = _require_messages(body)
    mode = str(body.get("mode") or "answer")
    if mode not in _VALID_MODES:
        raise ApiError(f"invalid mode: {mode!r}, expected one of {_VALID_MODES}")

    db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
    limit = _clamp_limit(body.get("limit"))
    call_real_api = _as_bool(body.get("call_real_api"), False)
    hybrid = _as_bool(body.get("hybrid"), True)
    alpha = _clamp_alpha(body.get("alpha"))

    try:
        retrieval_query = build_retrieval_query(messages)
        query = standalone_question(messages)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc

    if mode == "detailed":
        raw = cli.run_orchestrate_answer(
            query=query,
            search_query=retrieval_query,
            db_path=db_path,
            limit=limit,
            hybrid=hybrid,
            alpha=alpha,
            call_real_api=call_real_api,
        )
    else:
        raw = cli.run_rag_answer(
            query=query,
            db_path=db_path,
            limit=limit,
            call_real_api=call_real_api,
            retrieval_query=retrieval_query,
            hybrid=hybrid,
            alpha=alpha,
        )

    return _normalize(
        raw,
        mode=mode,
        original_query=_latest_user_content(messages),
        resolved_query=retrieval_query,
        hybrid=hybrid,
        alpha=alpha,
        limit=limit,
    )


def _normalize(
    raw: JsonDict,
    *,
    mode: str,
    original_query: str,
    resolved_query: str,
    hybrid: bool,
    alpha: float,
    limit: int,
) -> JsonDict:
    """Map either ``run_rag_answer`` or ``run_orchestrate_answer`` output to
    the unified ``chat.turn.v1`` message shape.

    Orchestrate output is detected solely by the presence of a "synthesis"
    key (only ``run_orchestrate_answer`` ever sets it) -- the caller's chosen
    ``mode`` is not used for this branch so the normalizer stays correct even
    if routing logic changes later.
    """

    results = raw.get("results") or []
    result_count = len(results)
    no_evidence = result_count == 0

    llm_meta: JsonDict | None
    if no_evidence:
        kind = "no_evidence"
        content = str(raw.get("answer", ""))
        # The orchestrate skip path carries neither an "llm" nor a "synthesis"
        # dict; synthesize a skipped marker so clients can always rely on
        # meta.llm.skipped for the no-evidence case.
        llm_meta = _llm_meta(raw.get("llm")) or _llm_meta(raw.get("synthesis")) or {
            "source": None,
            "warning": None,
            "skipped": True,
            "cache_key": None,
        }
        highlights = list(raw.get("highlights") or [])
    elif "synthesis" in raw:
        kind = "orchestrate"
        synthesis = raw.get("synthesis") or {}
        content = str(synthesis.get("text") or raw.get("answer", ""))
        llm_meta = _llm_meta(synthesis)
        highlights = list(raw.get("highlights") or [])
    else:
        kind = "rag_answer"
        content = str(raw.get("answer", ""))
        llm_meta = _llm_meta(raw.get("llm"))
        highlights = list(raw.get("highlights") or [])

    citations = [result.get("citation") for result in results if isinstance(result, dict)]
    disclaimer = raw.get("disclaimer") or RAG_DISCLAIMER

    # Budget reporting is informational; a broken/missing budget config must
    # not take down the chat response itself.
    try:
        budget: JsonDict | None = asdict(cli.build_budget_report(DEFAULT_GEMINI_CONFIG_PATH))
    except Exception:  # pragma: no cover - exercised via monkeypatched raiser
        budget = None

    return {
        "contract": {"version": CONTRACT_VERSION, "stream_ready": True},
        "message": {
            "role": "assistant",
            "kind": kind,
            "content": content,
            "citations": citations,
            "evidence": results,
            "meta": {
                "mode": mode,
                "disclaimer": disclaimer,
                "highlights": highlights,
                # Intentionally null in Sprint A: this endpoint does not
                # resolve a ticker to score/forecast yet -- Sprint C fills
                # these from the resolved entity.
                "stock_score": raw.get("stock_score"),
                "forecast": raw.get("stock_forecast"),
                "llm": llm_meta,
                "retrieval": {
                    "original_query": original_query,
                    "resolved_query": resolved_query,
                    "hybrid": hybrid,
                    "alpha": alpha,
                    "limit": limit,
                    "result_count": result_count,
                    "no_evidence": no_evidence,
                },
                "budget": budget,
                "simulation": None,
            },
        },
    }


def _llm_meta(raw_llm: object) -> JsonDict | None:
    if not isinstance(raw_llm, dict) or not raw_llm:
        return None
    return {
        "source": raw_llm.get("source"),
        "warning": raw_llm.get("warning"),
        "skipped": raw_llm.get("skipped"),
        "cache_key": raw_llm.get("cache_key"),
    }


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


def _latest_user_content(messages: list[dict[str, Any]]) -> str:
    latest = messages[-1]
    content = latest.get("content")
    return content if isinstance(content, str) else ""


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
