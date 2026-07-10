"""Unit tests for ``websearch/answer.py``.

Mirrors ``test_rag_answer.py``'s style: a fake duck-typed
``GroundedLlmService`` (``.generate_grounded``) drives ``generate_web_answer``
without any network access.
"""

from __future__ import annotations

from investment_assistant.llm.gemini_client import WebSource
from investment_assistant.llm.service import GroundedLlmResponse
from investment_assistant.websearch.answer import (
    WEB_ANSWER_TASK_TYPE,
    WEB_DISCLAIMER,
    LocalWebAnswerClient,
    build_web_answer_prompt,
    generate_web_answer,
)


class _FakeGroundedService:
    def __init__(self, response: GroundedLlmResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate_grounded(
        self, *, task_type: str, prompt: str, priority: str = "normal"
    ) -> GroundedLlmResponse:
        self.calls.append({"task_type": task_type, "prompt": prompt, "priority": priority})
        return self.response


def test_generate_web_answer_returns_rag_like_shape_with_web_marker():
    sources = (
        WebSource(url="https://a.example/", title="A社ニュース"),
        WebSource(url="https://b.example/", title="B社レポート"),
    )
    response = GroundedLlmResponse(
        text="回答本文", source="gemini_web", cache_key="k", sources=sources
    )
    service = _FakeGroundedService(response)

    result = generate_web_answer(service=service, query="KDDIの最新ニュースは？")

    assert result["query"] == "KDDIの最新ニュースは？"
    assert result["answer"] == "回答本文"
    assert result["web"] is True
    assert result["disclaimer"] == WEB_DISCLAIMER
    assert "Web検索結果" in WEB_DISCLAIMER
    assert result["llm"] == {
        "source": "gemini_web",
        "warning": False,
        "skipped": False,
        "cache_key": "k",
    }
    results = result["results"]
    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0] == {
        "source": "https://a.example/",
        "text": "A社ニュース",
        "score": None,
        "citation": {"label": "A社ニュース", "url": "https://a.example/"},
    }
    assert service.calls == [
        {
            "task_type": WEB_ANSWER_TASK_TYPE,
            "prompt": build_web_answer_prompt("KDDIの最新ニュースは？"),
            "priority": "normal",
        }
    ]


def test_generate_web_answer_no_sources_still_returns_web_marker():
    response = GroundedLlmResponse(text="回答本文", source="gemini_web", cache_key="k")
    service = _FakeGroundedService(response)

    result = generate_web_answer(service=service, query="質問")

    assert result["web"] is True
    assert result["results"] == []


def test_blank_text_transient_error_gets_non_empty_message():
    response = GroundedLlmResponse(
        text="", source="fallback:local_summary:error", cache_key="k", warning=True
    )
    service = _FakeGroundedService(response)

    result = generate_web_answer(service=service, query="質問")

    answer = result["answer"]
    assert isinstance(answer, str)
    assert answer.strip() != ""
    assert "Web検索による回答生成に一時的に失敗しました" in answer


def test_blank_text_daily_limit_gets_budget_exhausted_message():
    response = GroundedLlmResponse(
        text="", source="fallback:skip_llm:daily_limit_reached", cache_key="k", skipped=True
    )
    service = _FakeGroundedService(response)

    result = generate_web_answer(service=service, query="質問")

    assert "AI利用枠の上限に達したため" in result["answer"]


def test_blank_text_monthly_limit_gets_budget_exhausted_message():
    response = GroundedLlmResponse(
        text="", source="fallback:skip_llm:monthly_limit_reached", cache_key="k", skipped=True
    )
    service = _FakeGroundedService(response)

    result = generate_web_answer(service=service, query="質問")

    assert "AI利用枠の上限に達したため" in result["answer"]


def test_build_web_answer_prompt_includes_query_and_disclaimer():
    prompt = build_web_answer_prompt("トヨタの配当方針は？")

    assert "トヨタの配当方針は？" in prompt
    assert WEB_DISCLAIMER in prompt
    assert "個別商品の売買を断定的に推奨しない" in prompt


def test_local_web_answer_client_offline_path_returns_template_and_two_sources():
    prompt = build_web_answer_prompt("トヨタの配当方針は？")

    result = LocalWebAnswerClient().generate_grounded(prompt, model="gemini-test")

    assert "トヨタの配当方針は？" in result.text
    assert WEB_DISCLAIMER in result.text
    assert len(result.sources) == 2
    assert all(source.url and source.title for source in result.sources)


def test_local_web_answer_client_through_generate_web_answer_end_to_end(tmp_path):
    from investment_assistant.llm.budget_guard import BudgetConfig, BudgetGuard
    from investment_assistant.llm.cache import LlmCache
    from investment_assistant.llm.service import GroundedLlmService

    service = GroundedLlmService(
        model="gemini-test",
        client=LocalWebAnswerClient(),
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=BudgetGuard(
            tmp_path / "usage.sqlite",
            BudgetConfig(daily_request_limit=10, monthly_request_limit=100),
        ),
        provider="local_template",
        today_fn=lambda: "2026-07-10",
    )

    result = generate_web_answer(service=service, query="トヨタの配当方針は？")

    assert result["web"] is True
    assert result["llm"]["source"] == "local_template"
    assert len(result["results"]) == 2
