"""Unit tests for ``llm/service.py``'s ``GroundedLlmService``.

Mirrors ``test_llm_service.py``'s style, plus the Web-search-specific
behavior: cache keys bind today's date (freshness), and ``WebSource``
citations round-trip through cache hits.
"""

from __future__ import annotations

from dataclasses import dataclass

from investment_assistant.llm.budget_guard import BudgetConfig, BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.gemini_client import GroundedGeneration, WebSource
from investment_assistant.llm.service import FallbackConfig, GroundedLlmService


@dataclass
class FakeGroundedClient:
    calls: int = 0

    def generate_grounded(self, prompt: str, *, model: str) -> GroundedGeneration:
        self.calls += 1
        return GroundedGeneration(
            text=f"{model}: {prompt}",
            sources=(WebSource(url="https://example.com/a", title="A"),),
        )


@dataclass
class FailingGroundedClient:
    calls: int = 0
    reason: str | None = None

    def generate_grounded(self, prompt: str, *, model: str) -> GroundedGeneration:
        self.calls += 1
        err = RuntimeError("boom")
        if self.reason:
            err.reason = self.reason  # type: ignore[attr-defined]
        raise err


@dataclass
class FlakyThenOkGroundedClient:
    """Fails ``fail_times`` calls with a classified ``reason``, then succeeds."""

    fail_times: int
    reason: str = "server_error"
    calls: int = 0

    def generate_grounded(self, prompt: str, *, model: str) -> GroundedGeneration:
        self.calls += 1
        if self.calls <= self.fail_times:
            err = RuntimeError(f"boom {self.calls}")
            err.reason = self.reason  # type: ignore[attr-defined]
            raise err
        return GroundedGeneration(text=f"{model}: {prompt}", sources=())


def build_service(
    tmp_path,
    client,
    *,
    daily_limit=10,
    fallback=None,
    today_fn=None,
    max_retries=0,
    sleep_fn=None,
    cooldown_minutes=None,
    count_failed_attempts=False,
):
    return GroundedLlmService(
        model="gemini-web-test",
        client=client,
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=BudgetGuard(
            tmp_path / "usage.sqlite",
            BudgetConfig(
                daily_request_limit=daily_limit,
                monthly_request_limit=100,
                hard_stop_threshold_ratio=1.0,
                allowed_tasks=("web_answer",),
            ),
        ),
        fallback=fallback,
        today_fn=today_fn or (lambda: "2026-07-10"),
        max_retries=max_retries,
        sleep_fn=sleep_fn,
        cooldown_minutes=cooldown_minutes,
        count_failed_attempts=count_failed_attempts,
    )


def test_default_provider_label_is_gemini_web(tmp_path):
    client = FakeGroundedClient()
    service = build_service(tmp_path, client)

    response = service.generate_grounded(task_type="web_answer", prompt="hello")

    assert response.source == "gemini_web"
    assert response.text == "gemini-web-test: hello"
    assert response.sources == (WebSource(url="https://example.com/a", title="A"),)


def test_cache_hit_returns_sources_and_skips_client(tmp_path):
    client = FakeGroundedClient()
    service = build_service(tmp_path, client)

    first = service.generate_grounded(task_type="web_answer", prompt="hello")
    second = service.generate_grounded(task_type="web_answer", prompt="hello")

    assert first.source == "gemini_web"
    assert second.source == "cache"
    assert second.text == first.text
    assert second.sources == first.sources
    assert client.calls == 1


def test_cache_key_changes_with_todays_date(tmp_path):
    """Freshness: the same prompt on a different day must not hit cache."""

    client = FakeGroundedClient()
    dates = iter(["2026-07-10", "2026-07-11"])
    service = build_service(tmp_path, client, today_fn=lambda: next(dates))

    first = service.generate_grounded(task_type="web_answer", prompt="hello")
    second = service.generate_grounded(task_type="web_answer", prompt="hello")

    assert first.source == "gemini_web"
    assert second.source == "gemini_web"  # not a cache hit -- different day
    assert client.calls == 2


def test_budget_daily_limit_falls_back_and_skips_client(tmp_path):
    client = FakeGroundedClient()
    service = build_service(
        tmp_path,
        client,
        daily_limit=1,
        fallback=FallbackConfig(on_daily_limit="skip_llm"),
    )

    service.generate_grounded(task_type="web_answer", prompt="one")
    second = service.generate_grounded(task_type="web_answer", prompt="two")

    assert second.source == "fallback:skip_llm:daily_limit_reached"
    assert second.skipped is True
    assert second.text == ""
    assert second.sources == ()
    assert client.calls == 1


def test_task_not_allowed_blocks_before_client(tmp_path):
    client = FakeGroundedClient()
    service = GroundedLlmService(
        model="gemini-web-test",
        client=client,
        cache=LlmCache(tmp_path / "cache.sqlite"),
        budget_guard=BudgetGuard(
            tmp_path / "usage.sqlite",
            BudgetConfig(
                daily_request_limit=10,
                monthly_request_limit=100,
                allowed_tasks=("other_task",),
            ),
        ),
        today_fn=lambda: "2026-07-10",
    )

    response = service.generate_grounded(task_type="web_answer", prompt="hello")

    assert response.source == "fallback:local_summary:task_not_allowed"
    assert client.calls == 0


def test_retry_recovers_after_one_transient_server_error(tmp_path):
    client = FlakyThenOkGroundedClient(fail_times=1, reason="server_error")
    sleeps: list[float] = []
    service = build_service(tmp_path, client, max_retries=2, sleep_fn=sleeps.append)

    response = service.generate_grounded(task_type="web_answer", prompt="hello")

    assert response.text == "gemini-web-test: hello"
    assert response.source == "gemini_web"
    assert client.calls == 2
    assert sleeps == [1.0]


def test_retry_exhausted_falls_back(tmp_path):
    client = FailingGroundedClient(reason="server_error")
    sleeps: list[float] = []
    service = build_service(
        tmp_path,
        client,
        fallback=FallbackConfig(on_error="skip_llm"),
        max_retries=2,
        sleep_fn=sleeps.append,
    )

    response = service.generate_grounded(task_type="web_answer", prompt="hello")

    assert client.calls == 3
    assert sleeps == [1.0, 2.0]
    assert response.source == "fallback:skip_llm:server_error"
    assert response.skipped is True


def test_rate_limit_never_retries_and_records_cooldown(tmp_path):
    client = FailingGroundedClient(reason="rate_limit")
    sleeps: list[float] = []
    service = build_service(
        tmp_path,
        client,
        fallback=FallbackConfig(on_error="skip_llm"),
        cooldown_minutes=15,
        max_retries=2,
        sleep_fn=sleeps.append,
    )

    response = service.generate_grounded(task_type="web_answer", prompt="hello")

    assert client.calls == 1
    assert sleeps == []
    assert response.source == "fallback:skip_llm:rate_limit"
    assert service.budget_guard.in_cooldown() is True
