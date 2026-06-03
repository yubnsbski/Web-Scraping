"""Guarded RAG answer prompt building and local fake generation helpers."""

from __future__ import annotations

from dataclasses import asdict

from investment_assistant.llm.service import LlmResponse, LlmService
from investment_assistant.rag.search import build_answer_context, search_chunks
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
            "個別商品の売買を断定的に推奨しないでください。",
            "自動売買、実注文、確定的な投資判断は行わないでください。",
            "根拠、不確実性、免責を必ず含めてください。",
            "引用は [1] のようなコンテキスト番号で示してください。",
            "",
            "質問",
            query,
            "",
            "ローカル文書コンテキスト",
            context,
            "",
            "出力要件",
            "- 要点",
            "- 根拠と引用",
            "- 不確実性",
            f"- 免責: {DISCLAIMER}",
        )
    )


def generate_rag_answer(
    *,
    store: RagStore,
    service: LlmService,
    query: str,
    limit: int = 5,
) -> dict[str, object]:
    """Search local RAG chunks and generate an answer through ``LlmService``."""

    results = search_chunks(store, query=query, limit=limit)
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
    return {
        "query": query,
        "answer": response.text,
        "context": context,
        "results": [asdict(result) for result in results],
        "llm": _response_to_dict(response),
        "disclaimer": DISCLAIMER,
    }


def _response_to_dict(response: LlmResponse) -> dict[str, object]:
    return {
        "source": response.source,
        "warning": response.warning,
        "skipped": response.skipped,
        "cache_key": response.cache_key,
    }


def _extract_section(text: str, start_heading: str, end_heading: str) -> str:
    _, _, remainder = text.partition(start_heading)
    section, _, _ = remainder.partition(end_heading)
    return section.strip()
