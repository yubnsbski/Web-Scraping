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
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl = timedelta(seconds=ttl_seconds)
        self.enabled = enabled
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
