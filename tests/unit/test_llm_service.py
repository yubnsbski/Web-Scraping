from __future__ import annotations

from dataclasses import dataclass

from investment_assistant.llm.budget_guard import BudgetConfig, BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.service import FallbackConfig, LlmService


@dataclass
class FakeClient:
    calls: int = 0

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        return f"{model}: {prompt}"


@dataclass
class FailingClient:
    calls: int = 0

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        raise RuntimeError("boom")


def build_service(tmp_path, client, *, daily_limit=10, fallback=None):
    return LlmService(
        model="gemini-test",
        client=client,
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=BudgetGuard(
            tmp_path / "usage.sqlite",
            BudgetConfig(
                daily_request_limit=daily_limit,
                monthly_request_limit=100,
                hard_stop_threshold_ratio=1.0,
                allowed_tasks=("rag_answer",),
            ),
        ),
        fallback=fallback,
    )


def test_service_uses_client_then_cache(tmp_path):
    client = FakeClient()
    service = build_service(tmp_path, client)

    first = service.generate(task_type="rag_answer", prompt="hello")
    second = service.generate(task_type="rag_answer", prompt="hello")

    assert first.text == "gemini-test: hello"
    assert first.source == "gemini"
    assert second.text == "gemini-test: hello"
    assert second.source == "cache"
    assert client.calls == 1


def test_service_falls_back_when_task_not_allowed(tmp_path):
    client = FakeClient()
    service = build_service(
        tmp_path,
        client,
        fallback=FallbackConfig(on_error="local_summary"),
    )

    response = service.generate(task_type="bulk_news_summary", prompt="long prompt")

    assert response.text == "long prompt"
    assert response.source == "fallback:local_summary:task_not_allowed"
    assert client.calls == 0


def test_service_falls_back_to_local_summary_on_client_error_by_default(tmp_path):
    client = FailingClient()
    service = build_service(tmp_path, client)

    response = service.generate(task_type="rag_answer", prompt="hello")

    assert response.skipped is False
    assert response.source == "fallback:local_summary:error"
    assert response.text == "hello"
    assert client.calls == 1


def test_service_falls_back_on_daily_limit(tmp_path):
    client = FakeClient()
    service = build_service(tmp_path, client, daily_limit=1)

    first = service.generate(task_type="rag_answer", prompt="one")
    second = service.generate(task_type="rag_answer", prompt="two")

    assert first.source == "gemini"
    assert second.source == "fallback:local_summary:daily_limit_reached"
    assert second.text == "two"
    assert client.calls == 1
