from __future__ import annotations

from datetime import UTC, datetime

from investment_assistant.llm.budget_guard import BudgetConfig, BudgetGuard


def test_budget_guard_allows_allowed_task(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(
            daily_request_limit=10,
            monthly_request_limit=100,
            allowed_tasks=("rag_answer",),
        ),
    )

    decision = guard.check("rag_answer")

    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_budget_guard_blocks_disallowed_task(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(
            daily_request_limit=10,
            monthly_request_limit=100,
            allowed_tasks=("rag_answer",),
        ),
    )

    decision = guard.check("bulk_news_summary")

    assert decision.allowed is False
    assert decision.reason == "task_not_allowed"


def test_budget_guard_stops_at_hard_daily_threshold(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(
            daily_request_limit=10,
            monthly_request_limit=100,
            hard_stop_threshold_ratio=0.5,
        ),
    )
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    for index in range(5):
        guard.record_call("rag_answer", "gemini", f"hash-{index}", at=now)

    decision = guard.check("rag_answer", at=now)

    assert decision.allowed is False
    assert decision.reason == "daily_limit_reached"
    assert decision.daily_count == 5


def test_cache_hits_do_not_count_against_budget(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(daily_request_limit=1, monthly_request_limit=1, hard_stop_threshold_ratio=1.0),
    )
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)

    guard.record_call("rag_answer", "gemini", "hash", cache_hit=True, at=now)

    assert guard.check("rag_answer", at=now).allowed is True


def test_cooldown_blocks_check_with_cooldown_reason(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(daily_request_limit=100, monthly_request_limit=1000),
    )
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)

    assert guard.in_cooldown(at=now) is False

    guard.record_cooldown(30, at=now)

    assert guard.in_cooldown(at=now) is True
    decision = guard.check("rag_answer", at=now)
    assert decision.allowed is False
    assert decision.reason == "cooldown"


def test_cooldown_expires_after_configured_minutes(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(daily_request_limit=100, monthly_request_limit=1000),
    )
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    guard.record_cooldown(30, at=now)

    still_cooling = now.replace(minute=29)
    after_cooldown = now.replace(hour=13, minute=1)

    assert guard.in_cooldown(at=still_cooling) is True
    assert guard.in_cooldown(at=after_cooldown) is False
    assert guard.check("rag_answer", at=after_cooldown).allowed is True


def test_record_cooldown_overwrites_previous_cooldown(tmp_path):
    guard = BudgetGuard(
        tmp_path / "usage.sqlite",
        BudgetConfig(daily_request_limit=100, monthly_request_limit=1000),
    )
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    guard.record_cooldown(30, at=now)
    guard.record_cooldown(5, at=now)

    just_past_five = now.replace(minute=6)
    assert guard.in_cooldown(at=just_past_five) is False
