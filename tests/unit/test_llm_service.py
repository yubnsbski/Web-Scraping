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


@dataclass
class FlakyThenOkClient:
    """Fails ``fail_times`` calls with a classified ``reason``, then succeeds."""

    fail_times: int
    reason: str = "server_error"
    calls: int = 0

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            err = RuntimeError(f"boom {self.calls}")
            err.reason = self.reason  # type: ignore[attr-defined]
            raise err
        return f"{model}: {prompt}"


@dataclass
class AlwaysFailingClassifiedClient:
    reason: str = "server_error"
    calls: int = 0

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        err = RuntimeError("boom")
        err.reason = self.reason  # type: ignore[attr-defined]
        raise err


def test_retry_recovers_after_one_transient_server_error(tmp_path):
    client = FlakyThenOkClient(fail_times=1, reason="server_error")
    sleeps: list[float] = []
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(daily_request_limit=10, monthly_request_limit=100),
    )
    service = LlmService(
        model="gemini-test",
        client=client,
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=guard,
        max_retries=2,
        sleep_fn=sleeps.append,
    )

    response = service.generate(task_type="rag_answer", prompt="hello")

    assert response.text == "gemini-test: hello"
    assert response.source == "gemini"
    assert client.calls == 2
    assert sleeps == [1.0]
    assert guard.count_daily() == 1  # the failed retry attempt was not counted


def test_retry_exhausted_after_max_retries_falls_back(tmp_path):
    client = AlwaysFailingClassifiedClient(reason="server_error")
    sleeps: list[float] = []
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(daily_request_limit=10, monthly_request_limit=100),
    )
    service = LlmService(
        model="gemini-test",
        client=client,
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=guard,
        fallback=FallbackConfig(on_error="local_summary"),
        max_retries=2,
        sleep_fn=sleeps.append,
    )

    response = service.generate(task_type="rag_answer", prompt="hello")

    # max_retries + 1 total attempts, exactly one fallback response.
    assert client.calls == 3
    assert sleeps == [1.0, 2.0]
    assert response.source == "fallback:local_summary:server_error"
    assert response.text == "hello"


def test_empty_response_reason_never_retries(tmp_path):
    """empty_response is an HTTP 200 that already consumed free-tier quota;
    retrying it would double-spend, so it must fall straight to the fallback."""

    client = AlwaysFailingClassifiedClient(reason="empty_response")
    sleeps: list[float] = []
    service = LlmService(
        model="gemini-test",
        client=client,
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=BudgetGuard(
            tmp_path / "usage.sqlite",
            BudgetConfig(daily_request_limit=10, monthly_request_limit=100),
        ),
        fallback=FallbackConfig(on_error="local_summary"),
        max_retries=2,
        sleep_fn=sleeps.append,
    )

    response = service.generate(task_type="rag_answer", prompt="hello")

    assert client.calls == 1
    assert sleeps == []
    assert response.source == "fallback:local_summary:empty_response"
    assert response.text == "hello"


def test_rate_limit_reason_never_retries_and_still_records_cooldown(tmp_path):
    client = AlwaysFailingClassifiedClient(reason="rate_limit")
    sleeps: list[float] = []
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(daily_request_limit=10, monthly_request_limit=100),
    )
    service = LlmService(
        model="local:default",
        client=client,
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=guard,
        fallback=FallbackConfig(on_error="skip_llm"),
        provider="local",
        cooldown_minutes=30,
        max_retries=2,
        sleep_fn=sleeps.append,
    )

    response = service.generate(task_type="rag_answer", prompt="hello")

    assert client.calls == 1
    assert sleeps == []
    assert response.source == "fallback:skip_llm:rate_limit"
    assert guard.in_cooldown() is True


def test_max_retries_zero_default_matches_today_single_attempt_behavior(tmp_path):
    client = FailingClient()
    service = build_service(tmp_path, client)

    response = service.generate(task_type="rag_answer", prompt="hello")

    assert client.calls == 1
    assert response.source == "fallback:local_summary:error"


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


def test_cache_never_leaks_across_provider_labels(tmp_path):
    """An offline-template answer must not satisfy a real-provider call.

    Both providers share the same cache DB, model, and prompt; only the
    ``provider`` label differs (as in ``run_rag_answer`` / ``run_web_answer``
    with call_real_api False vs True). Regression for the live bug where a
    dry-run dummy answer was returned to a call_real_api=True request.
    """

    cache = LlmCache(tmp_path / "cache.sqlite")
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(
            daily_request_limit=10,
            monthly_request_limit=100,
            hard_stop_threshold_ratio=1.0,
            allowed_tasks=("rag_answer",),
        ),
    )
    offline_client = FakeClient()
    real_client = FakeClient()
    offline = LlmService(
        model="gemini-test", client=offline_client, cache=cache,
        budget_guard=guard, provider="local_template",
    )
    real = LlmService(
        model="gemini-test", client=real_client, cache=cache,
        budget_guard=guard, provider="gemini",
    )

    first = offline.generate(task_type="rag_answer", prompt="hello")
    second = real.generate(task_type="rag_answer", prompt="hello")

    assert first.source == "local_template"
    assert second.source == "gemini"  # cache miss: the real client was called
    assert offline_client.calls == 1
    assert real_client.calls == 1
    assert first.cache_key != second.cache_key
