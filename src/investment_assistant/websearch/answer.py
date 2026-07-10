"""Guarded Web-grounded answer prompt building and local fake generation.

Mirrors ``rag/answer.py`` closely on purpose: ``generate_web_answer`` returns
the same raw shape ``run_rag_answer`` produces (plus a ``"web": True``
marker and ``sources``-derived citations) so
``brainstem.compliance.ComplianceGuard._normalize`` needs only a small,
additive branch to handle it.
"""

from __future__ import annotations

from investment_assistant.llm.gemini_client import GroundedGeneration, WebSource
from investment_assistant.llm.service import GroundedLlmResponse, GroundedLlmService

WEB_ANSWER_TASK_TYPE = "web_answer"

# Web answers must not claim to be based on local documents (the RAG
# disclaimer wording) -- they are grounded in live Google Search results.
WEB_DISCLAIMER = (
    "これは投資助言ではなく、Web検索結果に基づく調査メモの下書きです。"
    "情報の正確性は出典元をご確認ください。"
    "最終的な投資判断はユーザー本人が行ってください。"
)


class LocalWebAnswerClient:
    """Deterministic no-network client for dry-run Web-grounded answers."""

    def generate_grounded(self, prompt: str, *, model: str) -> GroundedGeneration:
        _ = model
        query = _extract_query(prompt)
        text = "\n".join(
            (
                "ローカルWeb回答ドラフト（実Gemini Grounding未使用）",
                f"質問: {query}",
                "根拠: オフラインのためWeb検索は実行していません（ダミー情報源2件）。",
                "不確実性: 実際のWeb検索結果に基づく回答ではありません。",
                "信頼度: 低",
                f"免責: {WEB_DISCLAIMER}",
            )
        )
        sources = (
            WebSource(url="https://example.com/local-web-source-1", title="ローカルダミー情報源1"),
            WebSource(url="https://example.com/local-web-source-2", title="ローカルダミー情報源2"),
        )
        return GroundedGeneration(text=text, sources=sources)


def build_web_answer_prompt(query: str) -> str:
    """Build a compliance-aware prompt for guarded Web-grounded answer generation."""

    return "\n".join(
        (
            "あなたは投資調査メモ作成を補助するアシスタントです。",
            "最新のWeb情報を検索して、質問に回答してください。",
            "各主張には検索結果の根拠を紐づけてください。",
            "事実と、そこからの解釈は明確に分けて記述してください。",
            "個別商品の売買を断定的に推奨しないでください。",
            "自動売買、実注文、確定的な投資判断は行わないでください。",
            "回答全体の信頼度を 高 / 中 / 低 のいずれかで明示してください。",
            "",
            "質問",
            query,
            "",
            "出力要件",
            "- 要点（検索結果に基づく事実と解釈を分けて記述）",
            "- 不確実性（検索結果で確認できない点）",
            "- 信頼度: 高 / 中 / 低",
            f"- 免責: {WEB_DISCLAIMER}",
        )
    )


def generate_web_answer(*, service: GroundedLlmService, query: str) -> dict[str, object]:
    """Generate a Web-grounded, citation-aware answer through ``GroundedLlmService``.

    Returns the same raw shape ``rag.answer.generate_rag_answer`` produces
    (``query``/``answer``/``results``/``llm``/``disclaimer``), plus
    ``"web": True`` so ``ComplianceGuard`` can route it to the ``web_answer``
    kind. ``results`` carries one entry per grounding source, in the same
    ``search_result_to_dict`` shape (``source``/``text``/``score``/
    ``citation``) the RAG path uses, so the existing evidence/citation
    frontend components render it unchanged.
    """

    prompt = build_web_answer_prompt(query)
    response = service.generate_grounded(task_type=WEB_ANSWER_TASK_TYPE, prompt=prompt)
    answer = response.text
    if not str(answer).strip():
        answer = _blank_web_answer_fallback(response.source)
    results = [_source_to_result(source) for source in response.sources]
    return {
        "query": query,
        "answer": answer,
        "results": results,
        "llm": _response_to_dict(response),
        "disclaimer": WEB_DISCLAIMER,
        "web": True,
    }


_WEB_BUDGET_EXHAUSTED_MESSAGE = (
    "AI利用枠の上限に達したため、Web検索による回答を生成できませんでした。"
)
_WEB_TRANSIENT_FAILURE_MESSAGE = (
    "Web検索による回答生成に一時的に失敗しました。時間をおいてもう一度お試しください。"
)


def _blank_web_answer_fallback(source: str) -> str:
    """Deterministic Japanese message shown when grounded generation produced no text.

    Mirrors ``rag.answer._blank_answer_fallback``'s budget-vs-transient split,
    without highlight bullets (Web answers have no local evidence excerpt).
    """

    if "daily_limit" in source or "monthly_limit" in source:
        return _WEB_BUDGET_EXHAUSTED_MESSAGE
    return _WEB_TRANSIENT_FAILURE_MESSAGE


def _source_to_result(source: WebSource) -> dict[str, object]:
    return {
        "source": source.url,
        "text": source.title,
        "score": None,
        "citation": {"label": source.title, "url": source.url},
    }


def _response_to_dict(response: GroundedLlmResponse) -> dict[str, object]:
    return {
        "source": response.source,
        "warning": response.warning,
        "skipped": response.skipped,
        "cache_key": response.cache_key,
    }


def _extract_query(prompt: str) -> str:
    """Pull the question back out of ``build_web_answer_prompt``'s output.

    Same whole-line heading match as ``rag.answer._extract_section``, kept
    separate (rather than imported) since this only needs the single
    ``質問`` section, not a start/end pair.
    """

    _, separator, remainder = prompt.partition("\n質問\n")
    if not separator:
        return prompt.strip()
    section, _, _ = remainder.partition("\n\n")
    return section.strip()
