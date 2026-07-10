"""SQLite persistence for paper-trading runs.

Follows the same connect-per-call, commit-or-rollback style as
``rag/store.py``. Schema covers everything the P2 engine and P3 learning
loop need to record and later render into ``report.md``/``report.html``:
run metadata, per-cycle windows and policy snapshots, every order and fill,
end-of-day position marks, per-cycle metrics, generated memos, and the
policy-parameter change history (so an operator can audit exactly what the
LLM changed and why -- design doc requirement #4, "変化量は常にウォッチ
可能に").

``create_tables`` is idempotent (``CREATE TABLE IF NOT EXISTS``), so opening
an existing store never destroys data, and the default path is always
overridable -- tests must never touch the real
``data/runtime/papertrade.sqlite`` and instead pass a ``tmp_path`` file.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_STORE_PATH = Path("data/runtime/papertrade.sqlite")

JsonDict = dict[str, Any]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    strategy TEXT NOT NULL,
    params_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
    run_id TEXT NOT NULL,
    cycle_index INTEGER NOT NULL,
    decision_date TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    PRIMARY KEY (run_id, cycle_index)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_index INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    shares INTEGER NOT NULL,
    decision_date TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_run ON orders(run_id, cycle_index);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_index INTEGER NOT NULL,
    order_id INTEGER,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    date TEXT NOT NULL,
    price REAL NOT NULL,
    shares INTEGER NOT NULL,
    commission REAL NOT NULL,
    clamped INTEGER NOT NULL,
    settlement_date TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fills_run ON fills(run_id, cycle_index);

CREATE TABLE IF NOT EXISTS positions_eod (
    run_id TEXT NOT NULL,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    shares INTEGER NOT NULL,
    close REAL NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (run_id, date, ticker)
);

CREATE TABLE IF NOT EXISTS cycle_metrics (
    run_id TEXT NOT NULL,
    cycle_index INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (run_id, cycle_index)
);

CREATE TABLE IF NOT EXISTS memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_index INTEGER NOT NULL,
    path TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memos_run ON memos(run_id, cycle_index);

CREATE TABLE IF NOT EXISTS policy_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_index INTEGER NOT NULL,
    old_json TEXT NOT NULL,
    new_json TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_policy_history_run ON policy_history(run_id, cycle_index);
"""


class PaperTradeStore:
    """SQLite-backed persistence for one or more paper-trading runs."""

    def __init__(self, path: str | Path = DEFAULT_STORE_PATH) -> None:
        self.path = Path(path)
        self.create_tables()

    def create_tables(self) -> None:
        """Create the schema if it does not already exist (idempotent)."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- runs ---------------------------------------------------------

    def insert_run(
        self,
        *,
        run_id: str,
        kind: str,
        strategy: str,
        params: JsonDict,
        started_at: str,
        config: JsonDict,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, kind, strategy, params_json, started_at, config_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    kind = excluded.kind,
                    strategy = excluded.strategy,
                    params_json = excluded.params_json,
                    started_at = excluded.started_at,
                    config_json = excluded.config_json
                """,
                (
                    run_id,
                    kind,
                    strategy,
                    json.dumps(params, ensure_ascii=False, sort_keys=True),
                    started_at,
                    json.dumps(config, ensure_ascii=False, sort_keys=True),
                ),
            )

    def get_run(self, run_id: str) -> JsonDict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, kind, strategy, params_json, started_at, config_json "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0],
            "kind": row[1],
            "strategy": row[2],
            "params": json.loads(row[3]),
            "started_at": row[4],
            "config": json.loads(row[5]),
        }

    # --- cycles ---------------------------------------------------------

    def insert_cycle(
        self,
        *,
        run_id: str,
        cycle_index: int,
        decision_date: str,
        start_date: str,
        end_date: str,
        policy: JsonDict,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cycles
                    (run_id, cycle_index, decision_date, start_date, end_date, policy_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, cycle_index) DO UPDATE SET
                    decision_date = excluded.decision_date,
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    policy_json = excluded.policy_json
                """,
                (
                    run_id,
                    cycle_index,
                    decision_date,
                    start_date,
                    end_date,
                    json.dumps(policy, ensure_ascii=False, sort_keys=True),
                ),
            )

    def list_cycles(self, run_id: str) -> list[JsonDict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cycle_index, decision_date, start_date, end_date, policy_json "
                "FROM cycles WHERE run_id = ? ORDER BY cycle_index",
                (run_id,),
            ).fetchall()
        return [
            {
                "cycle_index": row[0],
                "decision_date": row[1],
                "start_date": row[2],
                "end_date": row[3],
                "policy": json.loads(row[4]),
            }
            for row in rows
        ]

    # --- orders / fills ---------------------------------------------------

    def insert_order(
        self,
        *,
        run_id: str,
        cycle_index: int,
        ticker: str,
        side: str,
        shares: int,
        decision_date: str,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO orders (run_id, cycle_index, ticker, side, shares, decision_date)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, cycle_index, ticker, side, shares, decision_date),
            )
            return int(cursor.lastrowid or 0)

    def list_orders(self, run_id: str, *, cycle_index: int | None = None) -> list[JsonDict]:
        sql = (
            "SELECT id, cycle_index, ticker, side, shares, decision_date "
            "FROM orders WHERE run_id = ?"
        )
        params: list[Any] = [run_id]
        if cycle_index is not None:
            sql += " AND cycle_index = ?"
            params.append(cycle_index)
        sql += " ORDER BY id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": row[0],
                "cycle_index": row[1],
                "ticker": row[2],
                "side": row[3],
                "shares": row[4],
                "decision_date": row[5],
            }
            for row in rows
        ]

    def insert_fill(
        self,
        *,
        run_id: str,
        cycle_index: int,
        order_id: int | None,
        ticker: str,
        side: str,
        date: str,
        price: float,
        shares: int,
        commission: float,
        clamped: bool,
        settlement_date: str,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO fills
                    (run_id, cycle_index, order_id, ticker, side, date, price, shares,
                     commission, clamped, settlement_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    cycle_index,
                    order_id,
                    ticker,
                    side,
                    date,
                    price,
                    shares,
                    commission,
                    int(clamped),
                    settlement_date,
                ),
            )
            return int(cursor.lastrowid or 0)

    def list_fills(self, run_id: str, *, cycle_index: int | None = None) -> list[JsonDict]:
        sql = (
            "SELECT id, cycle_index, order_id, ticker, side, date, price, shares, "
            "commission, clamped, settlement_date FROM fills WHERE run_id = ?"
        )
        params: list[Any] = [run_id]
        if cycle_index is not None:
            sql += " AND cycle_index = ?"
            params.append(cycle_index)
        sql += " ORDER BY id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": row[0],
                "cycle_index": row[1],
                "order_id": row[2],
                "ticker": row[3],
                "side": row[4],
                "date": row[5],
                "price": row[6],
                "shares": row[7],
                "commission": row[8],
                "clamped": bool(row[9]),
                "settlement_date": row[10],
            }
            for row in rows
        ]

    # --- positions_eod ------------------------------------------------

    def insert_positions_eod(
        self,
        *,
        run_id: str,
        date: str,
        ticker: str,
        shares: int,
        close: float,
        value: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO positions_eod (run_id, date, ticker, shares, close, value)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, date, ticker) DO UPDATE SET
                    shares = excluded.shares,
                    close = excluded.close,
                    value = excluded.value
                """,
                (run_id, date, ticker, shares, close, value),
            )

    def list_positions_eod(self, run_id: str, *, date: str | None = None) -> list[JsonDict]:
        sql = "SELECT date, ticker, shares, close, value FROM positions_eod WHERE run_id = ?"
        params: list[Any] = [run_id]
        if date is not None:
            sql += " AND date = ?"
            params.append(date)
        sql += " ORDER BY date, ticker"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "date": row[0],
                "ticker": row[1],
                "shares": row[2],
                "close": row[3],
                "value": row[4],
            }
            for row in rows
        ]

    # --- cycle_metrics --------------------------------------------------

    def insert_cycle_metrics(
        self, *, run_id: str, cycle_index: int, metrics: JsonDict
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cycle_metrics (run_id, cycle_index, metrics_json)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id, cycle_index) DO UPDATE SET
                    metrics_json = excluded.metrics_json
                """,
                (run_id, cycle_index, json.dumps(metrics, ensure_ascii=False, sort_keys=True)),
            )

    def list_cycle_metrics(self, run_id: str) -> list[JsonDict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cycle_index, metrics_json FROM cycle_metrics "
                "WHERE run_id = ? ORDER BY cycle_index",
                (run_id,),
            ).fetchall()
        return [{"cycle_index": row[0], "metrics": json.loads(row[1])} for row in rows]

    # --- memos ------------------------------------------------------------

    def insert_memo(self, *, run_id: str, cycle_index: int, path: str, body: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO memos (run_id, cycle_index, path, body) VALUES (?, ?, ?, ?)",
                (run_id, cycle_index, path, body),
            )
            return int(cursor.lastrowid or 0)

    def list_memos(self, run_id: str) -> list[JsonDict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, cycle_index, path, body FROM memos "
                "WHERE run_id = ? ORDER BY cycle_index",
                (run_id,),
            ).fetchall()
        return [
            {"id": row[0], "cycle_index": row[1], "path": row[2], "body": row[3]}
            for row in rows
        ]

    # --- policy_history -----------------------------------------------

    def insert_policy_history(
        self,
        *,
        run_id: str,
        cycle_index: int,
        old: JsonDict,
        new: JsonDict,
        reason: str,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO policy_history (run_id, cycle_index, old_json, new_json, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    cycle_index,
                    json.dumps(old, ensure_ascii=False, sort_keys=True),
                    json.dumps(new, ensure_ascii=False, sort_keys=True),
                    reason,
                ),
            )
            return int(cursor.lastrowid or 0)

    def list_policy_history(self, run_id: str) -> list[JsonDict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, cycle_index, old_json, new_json, reason FROM policy_history "
                "WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "cycle_index": row[1],
                "old": json.loads(row[2]),
                "new": json.loads(row[3]),
                "reason": row[4],
            }
            for row in rows
        ]
