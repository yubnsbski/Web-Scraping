"""Gemini API usage budget guard backed by SQLite."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class BudgetConfig:
    """Request budget configuration."""

    daily_request_limit: int
    monthly_request_limit: int
    warning_threshold_ratio: float = 0.8
    hard_stop_threshold_ratio: float = 0.95
    allowed_tasks: tuple[str, ...] = ()
    blocked_tasks: tuple[str, ...] = ()


@dataclass(frozen=True)
class BudgetDecision:
    """Decision returned before an LLM request."""

    allowed: bool
    reason: str
    daily_count: int
    monthly_count: int
    warning: bool = False


class BudgetGuard:
    """Track and enforce daily/monthly request budgets."""

    def __init__(self, db_path: str | Path, config: BudgetConfig) -> None:
        self.db_path = Path(db_path)
        self.config = config
        self._ensure_schema()

    def check(self, task_type: str, *, at: datetime | None = None) -> BudgetDecision:
        """Return whether a non-cached LLM request may be made."""

        if task_type in self.config.blocked_tasks:
            return BudgetDecision(False, "task_blocked", 0, 0)
        if self.config.allowed_tasks and task_type not in self.config.allowed_tasks:
            return BudgetDecision(False, "task_not_allowed", 0, 0)

        now = at or datetime.now(UTC)
        daily_count = self.count_daily(now)
        monthly_count = self.count_monthly(now)

        if self.in_cooldown(at=now):
            return BudgetDecision(False, "cooldown", daily_count, monthly_count)

        if daily_count >= self._hard_daily_limit():
            return BudgetDecision(False, "daily_limit_reached", daily_count, monthly_count)
        if monthly_count >= self._hard_monthly_limit():
            return BudgetDecision(False, "monthly_limit_reached", daily_count, monthly_count)

        daily_warning_limit = self.config.daily_request_limit * self.config.warning_threshold_ratio
        monthly_warning_limit = (
            self.config.monthly_request_limit * self.config.warning_threshold_ratio
        )
        warning = daily_count >= daily_warning_limit or monthly_count >= monthly_warning_limit
        return BudgetDecision(True, "allowed", daily_count, monthly_count, warning)

    def record_call(
        self,
        task_type: str,
        model: str,
        request_hash: str,
        *,
        cache_hit: bool = False,
        at: datetime | None = None,
    ) -> None:
        """Record an LLM service event.

        Cache hits are recorded for observability, but budget counts only include
        non-cache-hit calls.
        """

        now = at or datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gemini_usage (called_at, task_type, model, cache_hit, request_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now.isoformat(), task_type, model, int(cache_hit), request_hash),
            )

    def record_cooldown(self, minutes: int, *, at: datetime | None = None) -> None:
        """Put this guard's provider into cooldown for ``minutes`` minutes.

        Used after a rate-limit error so the service skips the provider without
        spawning another process/request until the cooldown expires. A single
        row (id=1) tracks the cooldown horizon; a new call simply overwrites it.
        """

        now = at or datetime.now(UTC)
        until = now + timedelta(minutes=minutes)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_cooldown (id, until_at) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET until_at = excluded.until_at
                """,
                (until.isoformat(),),
            )

    def cooldown_until(self) -> datetime | None:
        """Return the cooldown horizon, if any is recorded."""

        with self._connect() as conn:
            row = conn.execute("SELECT until_at FROM llm_cooldown WHERE id = 1").fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(str(row[0]))

    def in_cooldown(self, *, at: datetime | None = None) -> bool:
        """Return whether this guard's provider is currently in cooldown."""

        until = self.cooldown_until()
        if until is None:
            return False
        now = at or datetime.now(UTC)
        return now < until

    def count_daily(self, at: datetime | None = None) -> int:
        """Count non-cached calls for the UTC date containing ``at``."""

        now = at or datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self._count_since(start)

    def count_monthly(self, at: datetime | None = None) -> int:
        """Count non-cached calls for the UTC month containing ``at``."""

        now = at or datetime.now(UTC)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self._count_since(start)

    def _hard_daily_limit(self) -> int:
        return max(0, int(self.config.daily_request_limit * self.config.hard_stop_threshold_ratio))

    def _hard_monthly_limit(self) -> int:
        hard_limit = self.config.monthly_request_limit * self.config.hard_stop_threshold_ratio
        return max(0, int(hard_limit))

    def _count_since(self, start: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM gemini_usage
                WHERE called_at >= ? AND cache_hit = 0
                """,
                (start.isoformat(),),
            ).fetchone()
        return int(row[0])

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gemini_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    called_at TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    model TEXT NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    request_hash TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gemini_usage_called_at ON gemini_usage(called_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_cooldown (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    until_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
