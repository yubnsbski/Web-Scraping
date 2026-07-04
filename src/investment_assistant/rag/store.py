"""SQLite store for local RAG documents and chunks."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from investment_assistant.rag.chunker import Document, TextChunk
from investment_assistant.rag.embeddings import Embedder, HashingEmbedder
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

    def __init__(
        self,
        db_path: str | Path = DEFAULT_RAG_DB_PATH,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.fts_enabled = False
        self.embedder = embedder if embedder is not None else HashingEmbedder()
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
            conn.execute("DELETE FROM rag_embeddings WHERE source = ?", (document.source,))
            if chunks:
                vectors = self.embedder.embed([chunk.text for chunk in chunks])
                conn.executemany(
                    "INSERT INTO rag_embeddings (chunk_id, source, vector_json) VALUES (?, ?, ?)",
                    [
                        (chunk.chunk_id, chunk.source, json.dumps([round(v, 6) for v in vector]))
                        for chunk, vector in zip(chunks, vectors, strict=True)
                    ],
                )
                # Record which embedder produced the stored vectors so search can
                # embed queries in the same space (avoids silent space mismatch).
                conn.execute(
                    "INSERT INTO rag_meta (key, value) VALUES ('embedder', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (getattr(self.embedder, "name", "hashing"),),
                )
        return len(chunks)

    def stored_embedder_name(self) -> str | None:
        """Return the embedder name recorded at index time, if any."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM rag_meta WHERE key = 'embedder'"
            ).fetchone()
        return str(row[0]) if row else None

    def iter_embeddings(self) -> list[tuple[StoredChunk, list[float]]]:
        """Return all stored chunks paired with their embedding vectors."""

        sql = """
            SELECT
                rag_chunks.chunk_id,
                rag_chunks.source,
                rag_chunks.chunk_index,
                rag_chunks.text,
                rag_chunks.content_hash,
                rag_documents.metadata_json,
                rag_embeddings.vector_json
            FROM rag_embeddings
            JOIN rag_chunks ON rag_chunks.chunk_id = rag_embeddings.chunk_id
            JOIN rag_documents ON rag_documents.source = rag_chunks.source
        """
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [(_stored_chunk(row), _vector_from_json(str(row[6]))) for row in rows]

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

    def prune_documents(self, keep_sources: set[str], *, under_prefix: str | None = None) -> int:
        """Delete documents no longer eligible for indexing.

        Considers existing sources that equal ``under_prefix`` or sit under it
        as a directory (when given) and deletes any of those not present in
        ``keep_sources`` -- along with their chunks, embeddings, and FTS rows
        -- in a single transaction. Returns the number of documents pruned.
        A sibling path that merely shares a string prefix (e.g. ``rag`` vs.
        ``rag_priority1``) is not considered "under" it -- see
        ``_is_under_prefix``.

        The set difference is computed in Python (rather than a SQL
        ``NOT IN``) to avoid SQLite's bound-parameter limit when there are
        many existing sources.
        """

        with self._connect() as conn:
            rows = conn.execute("SELECT source FROM rag_documents").fetchall()
            all_sources = {str(row[0]) for row in rows}
            existing_sources_under_prefix = (
                {source for source in all_sources if _is_under_prefix(source, under_prefix)}
                if under_prefix is not None
                else all_sources
            )
            to_delete = existing_sources_under_prefix - keep_sources
            if not to_delete:
                return 0
            for batch in _chunked(sorted(to_delete), 500):
                placeholders = ",".join("?" for _ in batch)
                conn.execute(
                    f"DELETE FROM rag_documents WHERE source IN ({placeholders})", batch
                )
                conn.execute(
                    f"DELETE FROM rag_chunks WHERE source IN ({placeholders})", batch
                )
                conn.execute(
                    f"DELETE FROM rag_embeddings WHERE source IN ({placeholders})", batch
                )
                if self.fts_enabled:
                    conn.execute(
                        f"DELETE FROM rag_chunks_fts WHERE source IN ({placeholders})", batch
                    )
        return len(to_delete)

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_embeddings (
                    chunk_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    vector_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_embeddings_source ON rag_embeddings(source)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self.fts_enabled = self._ensure_fts(conn)
            self._backfill_embeddings(conn)

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

    def _backfill_embeddings(self, conn: sqlite3.Connection) -> None:
        """Embed existing chunks when the embeddings table is empty."""

        embedding_rows = conn.execute("SELECT COUNT(*) FROM rag_embeddings").fetchone()[0]
        chunk_rows = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        if int(embedding_rows) > 0 or int(chunk_rows) == 0:
            return
        rows = conn.execute("SELECT chunk_id, source, text FROM rag_chunks").fetchall()
        vectors = self.embedder.embed([str(row[2]) for row in rows])
        conn.executemany(
            "INSERT INTO rag_embeddings (chunk_id, source, vector_json) VALUES (?, ?, ?)",
            [
                (str(row[0]), str(row[1]), json.dumps([round(v, 6) for v in vector]))
                for row, vector in zip(rows, vectors, strict=True)
            ],
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _vector_from_json(value: str) -> list[float]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [float(item) for item in parsed]


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


def _chunked(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _is_under_prefix(source: str, prefix: str) -> bool:
    """Return whether ``source`` is ``prefix`` itself or a path beneath it.

    Both ``source`` (``Document.source``, see ``rag/chunker.py``) and
    ``prefix`` (``under_prefix``, see ``rag/indexer.py``) are ``str(Path(...))``
    forms using the OS-native separator. A bare ``str.startswith(prefix)``
    check would wrongly match sibling paths that merely share a string
    prefix -- e.g. ``.../rag_priority1`` "starts with" ``.../rag`` -- so a
    separator boundary (or exact equality) is required.
    """

    return source == prefix or source.startswith(prefix + os.sep)


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


def read_stored_embedder_name(db_path: str | Path) -> str | None:
    """Read the embedder name recorded in an existing RAG DB without opening it.

    Used by search to choose a query embedder matching the indexed corpus. A
    raw read avoids triggering schema creation or embedding backfill. Returns
    ``None`` for a missing DB or a corpus indexed before meta was tracked.
    """

    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    try:
        try:
            row = conn.execute(
                "SELECT value FROM rag_meta WHERE key = 'embedder'"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    finally:
        conn.close()
    return str(row[0]) if row else None
