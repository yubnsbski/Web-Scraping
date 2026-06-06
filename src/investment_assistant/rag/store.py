"""SQLite store for local RAG documents and chunks."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from investment_assistant.rag.chunker import Document, TextChunk
from investment_assistant.rag.tokenize import tokens_to_index_text

DEFAULT_RAG_DB_PATH = Path(".cache/investment_assistant/rag.sqlite")


@dataclass(frozen=True)
class StoredChunk:
    """Chunk row returned from the RAG store."""

    chunk_id: str
    source: str
    chunk_index: int
    text: str
    content_hash: str
    metadata: dict[str, str] = field(default_factory=dict)


class RagStore:
    """Persist documents and chunks in SQLite for local search."""

    def __init__(self, db_path: str | Path = DEFAULT_RAG_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.fts_enabled = False
        self._ensure_schema()

    def upsert_document(self, document: Document, chunks: list[TextChunk]) -> int:
        """Replace chunks for a document and return the number stored."""

        now = datetime.now(UTC).isoformat()
        metadata_json = json.dumps(document.metadata, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rag_documents (source, content_hash, indexed_at, metadata_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    indexed_at = excluded.indexed_at,
                    metadata_json = excluded.metadata_json
                """,
                (document.source, document.content_hash, now, metadata_json),
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
            if self.fts_enabled:
                conn.execute(
                    "DELETE FROM rag_chunks_fts WHERE source = ?", (document.source,)
                )
                conn.executemany(
                    """
                    INSERT INTO rag_chunks_fts (chunk_id, source, tokens)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (chunk.chunk_id, chunk.source, tokens_to_index_text(chunk.text))
                        for chunk in chunks
                    ],
                )
        return len(chunks)

    def search_bm25(
        self, query_tokens: list[str], *, limit: int
    ) -> list[tuple[StoredChunk, float]]:
        """Return chunks ranked by FTS5 BM25 relevance (most relevant first).

        Relevance is reported as ``-bm25`` so that larger numbers mean a better
        match. Returns an empty list when FTS is unavailable or no tokens match.
        """

        if not self.fts_enabled or not query_tokens or limit <= 0:
            return []
        match_expr = " OR ".join(_fts_quote(token) for token in query_tokens)
        sql = """
            SELECT
                rag_chunks.chunk_id,
                rag_chunks.source,
                rag_chunks.chunk_index,
                rag_chunks.text,
                rag_chunks.content_hash,
                rag_documents.metadata_json,
                bm25(rag_chunks_fts) AS score
            FROM rag_chunks_fts
            JOIN rag_chunks ON rag_chunks.chunk_id = rag_chunks_fts.chunk_id
            JOIN rag_documents ON rag_documents.source = rag_chunks.source
            WHERE rag_chunks_fts MATCH ?
            ORDER BY score, rag_chunks.source, rag_chunks.chunk_index
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (match_expr, limit)).fetchall()
        return [(_stored_chunk(row), round(-float(row[6]), 6)) for row in rows]

    def list_chunks(self, *, limit: int | None = None) -> list[StoredChunk]:
        """Return stored chunks in source/index order."""

        sql = """
            SELECT
                rag_chunks.chunk_id,
                rag_chunks.source,
                rag_chunks.chunk_index,
                rag_chunks.text,
                rag_chunks.content_hash,
                rag_documents.metadata_json
            FROM rag_chunks
            JOIN rag_documents ON rag_documents.source = rag_chunks.source
            ORDER BY rag_chunks.source, rag_chunks.chunk_index
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
                    indexed_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            _ensure_column(
                conn,
                table="rag_documents",
                column="metadata_json",
                definition="TEXT NOT NULL DEFAULT '{}'",
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
            self.fts_enabled = self._ensure_fts(conn)

    def _ensure_fts(self, conn: sqlite3.Connection) -> bool:
        """Create the FTS5 search table, returning False if FTS5 is unavailable."""

        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    source UNINDEXED,
                    tokens,
                    tokenize='unicode61'
                )
                """
            )
        except sqlite3.OperationalError:
            return False
        self._backfill_fts(conn)
        return True

    @staticmethod
    def _backfill_fts(conn: sqlite3.Connection) -> None:
        """Populate the FTS table from existing chunks when it is empty.

        Lets databases indexed before FTS existed become searchable without a
        manual re-index.
        """

        fts_rows = conn.execute("SELECT COUNT(*) FROM rag_chunks_fts").fetchone()[0]
        chunk_rows = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        if int(fts_rows) > 0 or int(chunk_rows) == 0:
            return
        rows = conn.execute("SELECT chunk_id, source, text FROM rag_chunks").fetchall()
        conn.executemany(
            "INSERT INTO rag_chunks_fts (chunk_id, source, tokens) VALUES (?, ?, ?)",
            [(str(row[0]), str(row[1]), tokens_to_index_text(str(row[2]))) for row in rows],
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


def _ensure_column(
    conn: sqlite3.Connection,
    *,
    table: str,
    column: str,
    definition: str,
) -> None:
    existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _stored_chunk(row: sqlite3.Row | tuple[object, ...]) -> StoredChunk:
    return StoredChunk(
        chunk_id=str(row[0]),
        source=str(row[1]),
        chunk_index=int(cast(Any, row[2])),
        text=str(row[3]),
        content_hash=str(row[4]),
        metadata=_metadata_from_json(str(row[5])),
    )


def _fts_quote(token: str) -> str:
    """Quote a token as an FTS5 string literal so it is matched verbatim."""

    escaped = token.replace('"', '""')
    return f'"{escaped}"'


def _metadata_from_json(value: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(item) for key, item in parsed.items()}
