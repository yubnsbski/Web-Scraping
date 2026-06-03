"""SQLite store for local RAG documents and chunks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from investment_assistant.rag.chunker import Document, TextChunk

DEFAULT_RAG_DB_PATH = Path(".cache/investment_assistant/rag.sqlite")


@dataclass(frozen=True)
class StoredChunk:
    """Chunk row returned from the RAG store."""

    chunk_id: str
    source: str
    chunk_index: int
    text: str
    content_hash: str


class RagStore:
    """Persist documents and chunks in SQLite for local search."""

    def __init__(self, db_path: str | Path = DEFAULT_RAG_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._ensure_schema()

    def upsert_document(self, document: Document, chunks: list[TextChunk]) -> int:
        """Replace chunks for a document and return the number stored."""

        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rag_documents (source, content_hash, indexed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    indexed_at = excluded.indexed_at
                """,
                (document.source, document.content_hash, now),
            )
            conn.execute("DELETE FROM rag_chunks WHERE source = ?", (document.source,))
            conn.executemany(
                """
                INSERT INTO rag_chunks (chunk_id, source, chunk_index, text, content_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.source,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.content_hash,
                    )
                    for chunk in chunks
                ],
            )
        return len(chunks)

    def list_chunks(self, *, limit: int | None = None) -> list[StoredChunk]:
        """Return stored chunks in source/index order."""

        sql = """
            SELECT chunk_id, source, chunk_index, text, content_hash
            FROM rag_chunks
            ORDER BY source, chunk_index
        """
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_stored_chunk(row) for row in rows]

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_documents (
                    source TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(source) REFERENCES rag_documents(source)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_index
                ON rag_chunks(source, chunk_index)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


def _stored_chunk(row: sqlite3.Row | tuple[object, ...]) -> StoredChunk:
    return StoredChunk(
        chunk_id=str(row[0]),
        source=str(row[1]),
        chunk_index=int(cast(Any, row[2])),
        text=str(row[3]),
        content_hash=str(row[4]),
    )
