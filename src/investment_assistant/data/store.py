"""SQLite-backed time-series store for investment data.

Design goals:
- All writes are timestamped → full history, never overwrite
- Cross-source validation happens at query time
- Lightweight: stdlib sqlite3 only, no ORM
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator

from investment_assistant.data.models import (
    DataQualityFlag,
    DividendHistory,
    FinancialSummary,
    StockQuote,
)

DEFAULT_DB_PATH = Path("data/runtime/investment_data.sqlite")


class InvestmentDataStore:
    """Thread-safe SQLite store for stock quotes, dividends, and financials."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── schema ──────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS stock_quotes (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    name        TEXT NOT NULL,
                    price       REAL NOT NULL,
                    price_date  TEXT NOT NULL,
                    dps_ttm     REAL NOT NULL DEFAULT 0,
                    eps_ttm     REAL NOT NULL DEFAULT 0,
                    per         REAL NOT NULL DEFAULT 0,
                    pbr         REAL NOT NULL DEFAULT 0,
                    market_cap_m REAL NOT NULL DEFAULT 0,
                    sector      TEXT NOT NULL DEFAULT '',
                    source      TEXT NOT NULL,
                    fetched_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dividend_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    fiscal_year INTEGER NOT NULL,
                    dps         REAL NOT NULL,
                    source      TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(ticker, fiscal_year, source)
                );

                CREATE TABLE IF NOT EXISTS financial_summary (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker                  TEXT NOT NULL,
                    fiscal_year             INTEGER NOT NULL,
                    revenue_m               REAL NOT NULL DEFAULT 0,
                    operating_profit_m      REAL NOT NULL DEFAULT 0,
                    net_profit_m            REAL NOT NULL DEFAULT 0,
                    total_assets_m          REAL NOT NULL DEFAULT 0,
                    equity_m                REAL NOT NULL DEFAULT 0,
                    interest_bearing_debt_m REAL NOT NULL DEFAULT 0,
                    operating_cf_m          REAL NOT NULL DEFAULT 0,
                    eps                     REAL NOT NULL DEFAULT 0,
                    bps                     REAL NOT NULL DEFAULT 0,
                    roe                     REAL NOT NULL DEFAULT 0,
                    equity_ratio            REAL NOT NULL DEFAULT 0,
                    source                  TEXT NOT NULL,
                    recorded_at             TEXT NOT NULL,
                    UNIQUE(ticker, fiscal_year, source)
                );

                CREATE TABLE IF NOT EXISTS data_quality_flags (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    field       TEXT NOT NULL,
                    severity    TEXT NOT NULL,
                    message     TEXT NOT NULL,
                    detected_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_quotes_ticker_date
                    ON stock_quotes(ticker, price_date);
                CREATE INDEX IF NOT EXISTS idx_div_ticker_year
                    ON dividend_history(ticker, fiscal_year);
                CREATE INDEX IF NOT EXISTS idx_fin_ticker_year
                    ON financial_summary(ticker, fiscal_year);
                CREATE INDEX IF NOT EXISTS idx_flags_ticker
                    ON data_quality_flags(ticker, detected_at);
            """)

    # ── writes ───────────────────────────────────────────────────────────────

    def upsert_quote(self, q: StockQuote) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stock_quotes
                    (ticker, name, price, price_date, dps_ttm, eps_ttm, per, pbr,
                     market_cap_m, sector, source, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    q.ticker, q.name, q.price, q.price_date.isoformat(),
                    q.dps_ttm, q.eps_ttm, q.per, q.pbr,
                    q.market_cap_m, q.sector, q.source,
                    q.fetched_at.isoformat(),
                ),
            )

    def upsert_dividend(self, d: DividendHistory) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dividend_history
                    (ticker, fiscal_year, dps, source, recorded_at)
                VALUES (?,?,?,?,?)
                """,
                (d.ticker, d.fiscal_year, d.dps, d.source, d.recorded_at.isoformat()),
            )

    def upsert_financial(self, f: FinancialSummary) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO financial_summary
                    (ticker, fiscal_year, revenue_m, operating_profit_m, net_profit_m,
                     total_assets_m, equity_m, interest_bearing_debt_m, operating_cf_m,
                     eps, bps, roe, equity_ratio, source, recorded_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f.ticker, f.fiscal_year, f.revenue_m, f.operating_profit_m,
                    f.net_profit_m, f.total_assets_m, f.equity_m,
                    f.interest_bearing_debt_m, f.operating_cf_m,
                    f.eps, f.bps, f.roe, f.equity_ratio, f.source,
                    f.recorded_at.isoformat(),
                ),
            )

    def save_flags(self, flags: list[DataQualityFlag]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO data_quality_flags (ticker, field, severity, message, detected_at)
                VALUES (?,?,?,?,?)
                """,
                [
                    (f.ticker, f.field, f.severity, f.message, f.detected_at.isoformat())
                    for f in flags
                ],
            )

    # ── reads ────────────────────────────────────────────────────────────────

    def latest_quote(self, ticker: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT ticker, name, price, price_date, dps_ttm, eps_ttm,
                       per, pbr, market_cap_m, sector, source, fetched_at
                FROM stock_quotes
                WHERE ticker = ?
                ORDER BY fetched_at DESC
                LIMIT 1
                """,
                (ticker,),
            ).fetchone()
        if row is None:
            return None
        keys = ["ticker", "name", "price", "price_date", "dps_ttm", "eps_ttm",
                "per", "pbr", "market_cap_m", "sector", "source", "fetched_at"]
        return dict(zip(keys, row))

    def dividend_history(self, ticker: str, years: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker, fiscal_year, dps, source, recorded_at
                FROM dividend_history
                WHERE ticker = ?
                ORDER BY fiscal_year DESC
                LIMIT ?
                """,
                (ticker, years),
            ).fetchall()
        keys = ["ticker", "fiscal_year", "dps", "source", "recorded_at"]
        return [dict(zip(keys, r)) for r in rows]

    def financial_history(self, ticker: str, years: int = 5) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker, fiscal_year, revenue_m, operating_profit_m, net_profit_m,
                       total_assets_m, equity_m, interest_bearing_debt_m, operating_cf_m,
                       eps, bps, roe, equity_ratio, source, recorded_at
                FROM financial_summary
                WHERE ticker = ?
                ORDER BY fiscal_year DESC
                LIMIT ?
                """,
                (ticker, years),
            ).fetchall()
        keys = ["ticker", "fiscal_year", "revenue_m", "operating_profit_m", "net_profit_m",
                "total_assets_m", "equity_m", "interest_bearing_debt_m", "operating_cf_m",
                "eps", "bps", "roe", "equity_ratio", "source", "recorded_at"]
        return [dict(zip(keys, r)) for r in rows]

    def recent_flags(self, ticker: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker, field, severity, message, detected_at
                FROM data_quality_flags
                WHERE ticker = ?
                ORDER BY detected_at DESC
                LIMIT ?
                """,
                (ticker, limit),
            ).fetchall()
        keys = ["ticker", "field", "severity", "message", "detected_at"]
        return [dict(zip(keys, r)) for r in rows]

    def all_tickers(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM stock_quotes ORDER BY ticker"
            ).fetchall()
        return [r[0] for r in rows]

    def sector_peers(self, sector: str) -> list[dict]:
        """Return latest quote for every ticker in the same sector."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT q.ticker, q.name, q.price, q.dps_ttm, q.eps_ttm,
                       q.per, q.pbr, q.market_cap_m, q.sector
                FROM stock_quotes q
                INNER JOIN (
                    SELECT ticker, MAX(fetched_at) AS max_at
                    FROM stock_quotes
                    WHERE sector = ?
                    GROUP BY ticker
                ) latest ON q.ticker = latest.ticker AND q.fetched_at = latest.max_at
                ORDER BY q.ticker
                """,
                (sector,),
            ).fetchall()
        keys = ["ticker", "name", "price", "dps_ttm", "eps_ttm",
                "per", "pbr", "market_cap_m", "sector"]
        return [dict(zip(keys, r)) for r in rows]

    # ── internal ─────────────────────────────────────────────────────────────

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
