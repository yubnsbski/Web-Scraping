"""Sprint Cache — pre-computed score store for instant output (出力系).

スコアをSQLiteにキャッシュしておき、リクエスト時はDB読み取りのみで即時応答。

Table: sprint_scores
  ticker      TEXT PRIMARY KEY
  name        TEXT
  score_json  TEXT   -- DividendScoredStock.to_dict() の JSON全体
  ranked_at   TEXT   -- ISO8601 UTC

SprintCache.get_ranked()  → list[dict]  (ネットワーク不要、数ms)
SprintCache.upsert_scores() → 更新トリガー (フリック収集後に呼ぶ)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from investment_assistant.data.store import DEFAULT_DB_PATH

_log = logging.getLogger("data.sprint_cache")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sprint_scores (
    ticker      TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    score_json  TEXT NOT NULL,
    ranked_at   TEXT NOT NULL
)
"""


class SprintCache:
    """キャッシュ済みスコアの読み書き。InvestmentDataStoreと同じDBファイルを共有。"""

    def __init__(self, store_or_path=None) -> None:
        if store_or_path is None:
            self._db_path = Path(DEFAULT_DB_PATH)
        elif hasattr(store_or_path, "_db_path"):
            # InvestmentDataStore instance
            self._db_path = Path(store_or_path._db_path)
        else:
            self._db_path = Path(store_or_path)
        self._ensure_table()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    # ── writes ────────────────────────────────────────────────────────────────

    def upsert_scores(self, scored_stocks: list) -> int:
        """DividendScoredStock オブジェクトのリストをキャッシュに保存。"""
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                s.input.ticker,
                s.input.name,
                json.dumps(s.to_dict(), ensure_ascii=False),
                now,
            )
            for s in scored_stocks
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO sprint_scores (ticker, name, score_json, ranked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    name=excluded.name,
                    score_json=excluded.score_json,
                    ranked_at=excluded.ranked_at
                """,
                rows,
            )
        _log.debug("upserted %d sprint scores", len(rows))
        return len(rows)

    def delete_ticker(self, ticker: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sprint_scores WHERE ticker = ?", (ticker,))

    # ── reads ─────────────────────────────────────────────────────────────────

    def get_ranked(
        self,
        tickers: list[str] | None = None,
        top_n: int | None = None,
    ) -> list[dict]:
        """スコア済みデータをキャッシュから取得。ネットワーク不要・即時。

        Returns ranked list sorted by total_score DESC.
        """
        with self._connect() as conn:
            if tickers:
                placeholders = ",".join("?" * len(tickers))
                rows = conn.execute(
                    f"SELECT score_json, ranked_at FROM sprint_scores WHERE ticker IN ({placeholders})",
                    tickers,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT score_json, ranked_at FROM sprint_scores"
                ).fetchall()

        results = []
        for score_json, ranked_at in rows:
            try:
                d = json.loads(score_json)
                d["cached_at"] = ranked_at
                results.append(d)
            except (json.JSONDecodeError, KeyError) as exc:
                _log.warning("corrupt sprint cache entry: %s", exc)

        results.sort(key=lambda r: r.get("breakdown", {}).get("total_score", 0), reverse=True)
        if top_n:
            results = results[:top_n]

        # Re-assign rank after sort
        for i, r in enumerate(results, start=1):
            r["rank"] = i

        return results

    def coverage(self) -> dict:
        """キャッシュの収録状況サマリー。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ticker, name, ranked_at FROM sprint_scores ORDER BY ranked_at DESC"
            ).fetchall()

        if not rows:
            return {"cached": 0, "oldest": None, "newest": None, "tickers": []}

        oldest = min(r[2] for r in rows)
        newest = max(r[2] for r in rows)
        return {
            "cached": len(rows),
            "oldest": oldest,
            "newest": newest,
            "tickers": [{"ticker": r[0], "name": r[1], "ranked_at": r[2]} for r in rows],
        }

    def is_stale(self, max_age_hours: float = 26.0) -> bool:
        """キャッシュが古い（最終更新から max_age_hours 以上経過）かどうか。"""
        cov = self.coverage()
        if not cov["newest"]:
            return True
        from investment_assistant.data.flick_collector import _parse_dt
        from datetime import timedelta
        newest_dt = _parse_dt(cov["newest"])
        if newest_dt is None:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        return newest_dt < cutoff
