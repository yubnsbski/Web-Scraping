"""Guarded RAG answer prompt building and local fake generation helpers."""

from __future__ import annotations

from investment_assistant.llm.service import LlmResponse, LlmService
from investment_assistant.rag.search import (
    DEFAULT_HYBRID_ALPHA,
    build_answer_context,
    evidence_highlights,
    hybrid_search,
    search_chunks,
    search_result_to_dict,
)
from investment_assistant.rag.store import RagStore

RAG_ANSWER_TASK_TYPE = "rag_answer"
DISCLAIMER = (
    "これは投資助言ではなく、ローカル文書に基づく調査メモの下書きです。"
    "最終的な投資判断はユーザー本人が行ってください。"
)


class LocalRagAnswerClient:
    """Deterministic no-network client for dry-run RAG answer generation."""

    def generate(self, prompt: str, *, model: str) -> str:
        _ = model
        query = _extract_section(prompt, "質問", "ローカル文書コンテキスト")
        context = _extract_section(prompt, "ローカル文書コンテキスト", "出力要件")
        context_preview = " ".join(context.split())[:500]
        return "\n".join(
            (
                "ローカルRAG回答ドラフト（実Gemini API未使用）",
                f"質問: {query}",
                f"根拠候補: {context_preview}",
                "不確実性: ローカル文書検索に一致した範囲だけを根拠にしています。",
                f"免責: {DISCLAIMER}",
            )
        )


def build_rag_answer_prompt(*, query: str, context: str) -> str:
    """Build a compliance-aware prompt for guarded RAG answer generation."""

    return "\n".join(
        (
            "あなたは投資調査メモ作成を補助するアシスタントです。",
            "以下のローカル文書コンテキストだけを根拠に回答してください。",
            "コンテキストに無い情報は推測せず、"
            "不足する場合は「コンテキスト不足のため回答できません」と述べてください。",
            "各主張の文末に必ず [1] のような根拠コンテキスト番号を付けてください。"
            "番号は提示順に対応します。",
            "事実と解釈を分け、冗長な前置きを避けて簡潔かつ緻密に書いてください。",
            "個別商品の売買を断定的に推奨しないでください。",
            "自動売買、実注文、確定的な投資判断は行わないでください。",
            "回答全体の信頼度を 高 / 中 / 低 のいずれかで明示してください。",
            "",
            "質問",
            query,
            "",
            "ローカル文書コンテキスト",
            context,
            "",
            "出力要件",
            "- 要点（各文に [n] 引用）",
            "- 根拠と引用",
            "- 不確実性（コンテキストで確認できない点）",
            "- 信頼度: 高 / 中 / 低",
            f"- 免責: {DISCLAIMER}",
        )
    )


def generate_rag_answer(
    *,
    store: RagStore,
    service: LlmService,
    query: str,
    limit: int = 5,
    retrieval_query: str | None = None,
    hybrid: bool = False,
    alpha: float = DEFAULT_HYBRID_ALPHA,
) -> dict[str, object]:
    """Search local RAG chunks and generate an answer through ``LlmService``.

    ``retrieval_query`` (when given) is used for search instead of ``query``,
    so a history-aware retrieval string (e.g. carrying a ticker mentioned in
    an earlier chat turn) can steer search without changing the question the
    LLM sees. The prompt always uses ``query``.
    """

    search_text = retrieval_query or query
    # Hybrid queries must be embedded in the same space the corpus was indexed
    # with, so the store's embedder (resolved by the caller from DB meta) is
    # passed through instead of letting hybrid_search default to hashing.
    results = (
        hybrid_search(
            store,
            query=search_text,
            limit=limit,
            alpha=alpha,
            embedder=store.embedder,
        )
        if hybrid
        else search_chunks(store, query=search_text, limit=limit)
    )
    context = build_answer_context(results)
    if not results:
        return {
            "query": query,
            "answer": "関連するローカル文書チャンクがないため、LLM回答生成をスキップしました。",
            "context": context,
            "results": [],
            "llm": _response_to_dict(
                LlmResponse(text="", source="skipped:no_context", cache_key="", skipped=True)
            ),
            "disclaimer": DISCLAIMER,
        }

    prompt = build_rag_answer_prompt(query=query, context=context)
    response = service.generate(task_type=RAG_ANSWER_TASK_TYPE, prompt=prompt)
    highlights = evidence_highlights(results)
    answer = response.text
    if not str(answer).strip():
        answer = _blank_answer_fallback(response.source, highlights)
    return {
        "query": query,
        "answer": answer,
        "context": context,
        "highlights": highlights,
        "results": [search_result_to_dict(result) for result in results],
        "llm": _response_to_dict(response),
        "disclaimer": DISCLAIMER,
    }


# Period-neutral wording: this message covers both the daily and the monthly
# budget limits, so it must not claim 「本日の」.
_BUDGET_EXHAUSTED_MESSAGE = (
    "AI利用枠の上限に達したため、AIによる回答を生成できませんでした。"
)
_TRANSIENT_FAILURE_MESSAGE = (
    "AIによる回答生成に一時的に失敗しました。時間をおいてもう一度お試しください。"
)


def _blank_answer_fallback(source: str, highlights: list[dict[str, object]]) -> str:
    """Deterministic Japanese message shown when the LLM produced no text.

    ``source`` is ``LlmResponse.source`` (e.g. ``"fallback:local_summary:error"``
    or ``"fallback:skip_llm:daily_limit_reached"``): a budget-exhaustion reason
    gets a distinct message from a generic transient failure. When evidence
    highlights are available, up to three are appended as a short excerpt so
    the user is not left with a bare apology.
    """

    if "daily_limit" in source or "monthly_limit" in source:
        message = _BUDGET_EXHAUSTED_MESSAGE
    else:
        message = _TRANSIENT_FAILURE_MESSAGE

    bullets = [_highlight_to_line(item) for item in highlights[:3]]
    bullets = [line for line in bullets if line]
    if bullets:
        message += "\n\n検索で見つかった根拠の抜粋:\n" + "\n".join(
            f"- {line}" for line in bullets
        )
    return message


def _highlight_to_line(item: object) -> str:
    """Coerce one ``evidence_highlights`` item into a short display string."""

    if not isinstance(item, dict):
        return str(item).strip()

    label = item.get("name") or item.get("source") or ""
    parts = [str(part) for part in (item.get("forecast"), item.get("tags")) if part]
    detail = " / ".join(parts)
    line = f"{label}: {detail}" if label and detail else str(label or detail)
    return line.strip()


def _response_to_dict(response: LlmResponse) -> dict[str, object]:
    return {
        "source": response.source,
        "warning": response.warning,
        "skipped": response.skipped,
        "cache_key": response.cache_key,
    }


def _extract_section(text: str, start_heading: str, end_heading: str) -> str:
    """Extract the body between two standalone heading lines.

    Headings are matched as whole lines (``\\n<heading>\\n``) so instruction
    text that merely mentions a heading word does not start the section early.
    """

    _, separator, remainder = text.partition(f"\n{start_heading}\n")
    if not separator:
        _, _, remainder = text.partition(start_heading)
    section, _, _ = remainder.partition(f"\n{end_heading}\n")
    return section.strip()
