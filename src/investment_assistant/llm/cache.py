"""SQLite cache for LLM responses."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


class LlmCache:
    """Persist prompt responses to avoid repeated Gemini API calls."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl_days: int = 30,
        enabled: bool = True,
        max_rows: int | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl = timedelta(days=ttl_days)
        self.enabled = enabled
        self.max_rows = max_rows
        self._ensure_schema()

    @staticmethod
    def make_key(task_type: str, model: str, prompt: str) -> str:
        """Create a stable cache key for an LLM request."""

        source = f"{task_type}\0{model}\0{prompt}".encode()
        return hashlib.sha256(source).hexdigest()

    def get(self, key: str, *, now: datetime | None = None) -> str | None:
        """Return a cached response if present and not expired."""

        if not self.enabled:
            return None
        current = now or datetime.now(UTC)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response, created_at FROM llm_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        response, created_at_raw = row
        created_at = datetime.fromisoformat(str(created_at_raw))
        if current - created_at > self.ttl:
            return None
        return str(response)

    def set(self, key: str, response: str, *, now: datetime | None = None) -> None:
        """Store or replace a cached response."""

        if not self.enabled:
            return
        current = now or datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_cache (cache_key, response, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    response = excluded.response,
                    created_at = excluded.created_at
                """,
                (key, response, current.isoformat()),
            )
        if self.max_rows is not None:
            self.enforce_max_rows()

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete cache rows older than the TTL. Returns the number removed."""

        if not self.enabled:
            return 0
        cutoff = (now or datetime.now(UTC)) - self.ttl
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM llm_cache WHERE created_at < ?", (cutoff.isoformat(),)
            )
            return int(cursor.rowcount)

    def enforce_max_rows(self, max_rows: int | None = None) -> int:
        """Keep only the newest ``max_rows`` rows. Returns the number removed."""

        limit = max_rows if max_rows is not None else self.max_rows
        if limit is None:
            return 0
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM llm_cache
                WHERE cache_key NOT IN (
                    SELECT cache_key FROM llm_cache ORDER BY created_at DESC LIMIT ?
                )
                """,
                (max(0, limit),),
            )
            return int(cursor.rowcount)

    def clear(self) -> int:
        """Delete all cached LLM responses. Returns the number removed."""

        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM llm_cache")
            return int(cursor.rowcount)

    def count(self) -> int:
        """Return the number of cached LLM responses."""

        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()
            return int(row[0])

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    response TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
