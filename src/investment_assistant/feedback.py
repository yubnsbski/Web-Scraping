"""User feedback (👍/👎) on AI Chat answers — a lightweight learning signal.

Each rating is recorded against the sources that grounded the answer. The net
score per source (👍 = +1, 👎 = -1) is then used by retrieval to gently re-rank:
sources the user found helpful float up, unhelpful ones sink. This is the
"learning loop" — the assistant adapts to feedback over time. Local SQLite only.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_FEEDBACK_DB_PATH = ".cache/investment_assistant/feedback.sqlite"

_RATING_VALUES = {"up": 1, "down": -1}


class FeedbackStore:
    """Persist and aggregate thumbs-up/down feedback per grounding source."""

    def __init__(self, db_path: str | Path = DEFAULT_FEEDBACK_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._ensure_schema()

    def record(
        self,
        *,
        rating: str,
        sources: Sequence[str] | None = None,
        question: str = "",
        answer_preview: str = "",
    ) -> dict[str, object]:
        """Record one feedback event (one row per grounding source)."""

        value = _RATING_VALUES.get(str(rating).strip().lower())
        if value is None:
            msg = "rating must be 'up' or 'down'"
            raise ValueError(msg)

        cleaned = [str(s).strip() for s in (sources or []) if str(s).strip()]
        rows_sources = cleaned or [""]  # still record the event with no source
        event_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO feedback "
                "(event_id, created_at, question, answer_preview, rating, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (event_id, now, question[:500], answer_preview[:500], value, source)
                    for source in rows_sources
                ],
            )
        return {"event_id": event_id, "rating": rating, "sources": cleaned}

    def source_scores(self) -> dict[str, int]:
        """Return the net feedback score (sum of ±1) per non-empty source."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, COALESCE(SUM(rating), 0) FROM feedback "
                "WHERE source <> '' GROUP BY source"
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def summary(self) -> dict[str, object]:
        """Aggregate counts of feedback events plus per-source net scores."""

        with self._connect() as conn:
            total = int(
                conn.execute("SELECT COUNT(DISTINCT event_id) FROM feedback").fetchone()[0]
            )
            up = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT event_id) FROM feedback WHERE rating > 0"
                ).fetchone()[0]
            )
        scores = self.source_scores()
        return {
            "total": total,
            "up": up,
            "down": total - up,
            "rated_sources": len(scores),
            "by_source": scores,
        }

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    question TEXT NOT NULL DEFAULT '',
                    answer_preview TEXT NOT NULL DEFAULT '',
                    rating INTEGER NOT NULL,
                    source TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_source ON feedback(source)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


def feedback_source_scores(db_path: str | Path) -> dict[str, int]:
    """Return per-source feedback scores, or empty if no feedback DB exists yet."""

    if not Path(db_path).exists():
        return {}
    return FeedbackStore(db_path).source_scores()
