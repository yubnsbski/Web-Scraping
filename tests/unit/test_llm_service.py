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


def test_service_default_provider_label_is_gemini_for_backward_compat(tmp_path):
    service = build_service(tmp_path, FakeClient())
    response = service.generate(task_type="rag_answer", prompt="hello")
    assert response.source == "gemini"


def test_service_custom_provider_label_surfaces_on_success(tmp_path):
    service = LlmService(
        model="local:default",
        client=FakeClient(),
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=BudgetGuard(
            tmp_path / "usage.sqlite",
            BudgetConfig(daily_request_limit=10, monthly_request_limit=100),
        ),
        provider="local",
    )
    response = service.generate(task_type="rag_answer", prompt="hello")
    assert response.source == "local"


@dataclass
class RateLimitedClient:
    calls: int = 0

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        err = RuntimeError("rate_limit")
        err.reason = "rate_limit"  # type: ignore[attr-defined]
        raise err


def test_cooldown_minutes_records_cooldown_on_rate_limit_reason(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(daily_request_limit=10, monthly_request_limit=100),
    )
    service = LlmService(
        model="local:default",
        client=RateLimitedClient(),
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=guard,
        fallback=FallbackConfig(on_error="skip_llm"),
        provider="local",
        cooldown_minutes=30,
    )

    response = service.generate(task_type="rag_answer", prompt="hello")

    assert response.skipped is True
    assert response.source == "fallback:skip_llm:rate_limit"
    assert guard.in_cooldown() is True


def test_count_failed_attempts_counts_errors_against_daily_cap(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(
            daily_request_limit=1, monthly_request_limit=100, hard_stop_threshold_ratio=1.0
        ),
    )
    service = LlmService(
        model="local:default",
        client=FailingClient(),
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=guard,
        fallback=FallbackConfig(on_error="skip_llm"),
        provider="local",
        count_failed_attempts=True,
    )

    first = service.generate(task_type="rag_answer", prompt="one")
    second = service.generate(task_type="rag_answer", prompt="two")

    assert first.source == "fallback:skip_llm:error"
    # The failed first attempt counted against the daily cap (hard limit 1),
    # so the second (distinct, uncached) prompt is blocked before any client
    # call -- using the default on_daily_limit ("local_summary") fallback.
    assert second.source == "fallback:local_summary:daily_limit_reached"
    assert second.text == "two"


def test_without_count_failed_attempts_errors_do_not_count_against_daily_cap(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(
            daily_request_limit=1, monthly_request_limit=100, hard_stop_threshold_ratio=1.0
        ),
    )
    service = LlmService(
        model="gemini-test",
        client=FailingClient(),
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=guard,
        fallback=FallbackConfig(on_error="local_summary"),
    )

    service.generate(task_type="rag_answer", prompt="one")
    second = service.generate(task_type="rag_answer", prompt="two")

    # Default behavior (count_failed_attempts=False) is unchanged: a failed
    # call does not consume the daily budget, so a second distinct prompt is
    # still allowed to attempt the client (and fails again, same fallback).
    assert second.source == "fallback:local_summary:error"
