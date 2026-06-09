"""SQLite HTTP response cache for safe data ingestion."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class CachedHttpResponse:
    """Cached response payload with metadata."""

    url: str
    status_code: int
    headers_json: str
    body: bytes
    fetched_at: datetime


class HttpCache:
    """Persist HTTP responses to avoid repeated network requests."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl_seconds: int = 3600,
        enabled: bool = True,
        max_rows: int | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl = timedelta(seconds=ttl_seconds)
        self.enabled = enabled
        self.max_rows = max_rows
        self._ensure_schema()

    def get(self, url: str, *, now: datetime | None = None) -> CachedHttpResponse | None:
        """Return a cached response if present and within TTL."""

        if not self.enabled:
            return None
        current = now or datetime.now(UTC)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT url, status_code, headers_json, body, fetched_at
                FROM http_cache
                WHERE url = ?
                """,
                (url,),
            ).fetchone()
        if row is None:
            return None
        fetched_at = datetime.fromisoformat(str(row[4]))
        if current - fetched_at > self.ttl:
            return None
        return CachedHttpResponse(
            url=str(row[0]),
            status_code=int(row[1]),
            headers_json=str(row[2]),
            body=bytes(row[3]),
            fetched_at=fetched_at,
        )

    def set(
        self,
        *,
        url: str,
        status_code: int,
        headers_json: str,
        body: bytes,
        now: datetime | None = None,
    ) -> None:
        """Store or replace a cached response."""

        if not self.enabled:
            return
        current = now or datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO http_cache (url, status_code, headers_json, body, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    status_code = excluded.status_code,
                    headers_json = excluded.headers_json,
                    body = excluded.body,
                    fetched_at = excluded.fetched_at
                """,
                (url, status_code, headers_json, body, current.isoformat()),
            )
        if self.max_rows is not None:
            self.enforce_max_rows()

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete cached responses older than the TTL. Returns the number removed."""

        if not self.enabled:
            return 0
        cutoff = (now or datetime.now(UTC)) - self.ttl
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM http_cache WHERE fetched_at < ?", (cutoff.isoformat(),)
            )
            return int(cursor.rowcount)

    def enforce_max_rows(self, max_rows: int | None = None) -> int:
        """Keep only the newest ``max_rows`` cached responses. Returns removed count."""

        limit = max_rows if max_rows is not None else self.max_rows
        if limit is None:
            return 0
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM http_cache
                WHERE url NOT IN (
                    SELECT url FROM http_cache ORDER BY fetched_at DESC LIMIT ?
                )
                """,
                (max(0, limit),),
            )
            return int(cursor.rowcount)

    def clear(self) -> int:
        """Delete all cached HTTP responses. Returns the number removed."""

        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM http_cache")
            return int(cursor.rowcount)

    def count(self) -> int:
        """Return the number of cached HTTP responses."""

        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM http_cache").fetchone()
            return int(row[0])

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS http_cache (
                    url TEXT PRIMARY KEY,
                    status_code INTEGER NOT NULL,
                    headers_json TEXT NOT NULL,
                    body BLOB NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
