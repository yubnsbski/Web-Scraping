"""Stage 6+7 (comply, assemble): disclaimer/citation enforcement and the
``chat.turn.v1`` response shape.

Moved verbatim from ``webapi/chat.py`` (``_normalize`` / ``_llm_meta``) --
same behavior, same output shape, just relocated per blueprint section 2:
``ComplianceGuard`` is where citation-required / no-evidence-skip / budget
degradation is enforced server-side.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from investment_assistant import cli
from investment_assistant.brainstem.contracts import (
    BrainstemRequest,
    GenerationAttempt,
    ResolvedContext,
)
from investment_assistant.llm.factory import DEFAULT_GEMINI_CONFIG_PATH
from investment_assistant.rag.answer import DISCLAIMER as RAG_DISCLAIMER

JsonDict = dict[str, Any]

CONTRACT_VERSION = "chat.turn.v1"


class ComplianceGuard:
    """Normalizes a :class:`GenerationAttempt` into the ``chat.turn.v1`` shape."""

    def assemble(
        self,
        *,
        request: BrainstemRequest,
        resolved: ResolvedContext,
        attempt: GenerationAttempt,
    ) -> JsonDict:
        return _normalize(
            dict(attempt.raw),
            mode=request.answer_mode,
            original_query=resolved.original_query,
            resolved_query=resolved.retrieval_query,
            hybrid=request.hybrid,
            alpha=request.alpha,
            limit=request.limit,
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
    highlights: list[Any]
    if raw.get("small_talk"):
        kind = "small_talk"
        content = str(raw.get("answer", ""))
        llm_meta = _llm_meta(raw.get("llm"))
        highlights = []
    elif raw.get("web"):
        # A Web-grounded answer (``websearch.answer.generate_web_answer``,
        # via the web_grounded route or an "auto" rag-fallback) is never
        # "no evidence" even when ``results`` is empty (e.g. Gemini answered
        # without a grounding hit) -- it is its own kind, checked before the
        # no_evidence/synthesis branches below. ``no_evidence`` in
        # meta.retrieval still reflects the actual result count either way.
        kind = "web_answer"
        content = str(raw.get("answer", ""))
        llm_meta = _llm_meta(raw.get("llm"))
        highlights = []
    elif no_evidence:
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
    is_small_talk = kind == "small_talk"
    # Small talk never searches anything, so "no evidence" (which implies a
    # failed/empty search) does not apply; and it is not investment content,
    # so the RAG disclaimer must not be shown (frontend hides it when falsy).
    reported_no_evidence = False if is_small_talk else no_evidence
    disclaimer = "" if is_small_talk else (raw.get("disclaimer") or RAG_DISCLAIMER)

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
                    "no_evidence": reported_no_evidence,
                    # True when "auto" source_mode fell back from local RAG
                    # to a Web-grounded answer (generation.py sets the flag).
                    "auto_fallback": bool(raw.get("auto_fallback")),
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
