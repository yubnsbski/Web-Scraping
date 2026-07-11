"""Persistent user-facing (and AI-facing) virtual trading book -- Sprint V1/V2.

Minkabu-style 仮想取引: a *user* manually places virtual buy/sell orders
through the web UI, and (Sprint V2) a deterministic autopilot strategy
(:mod:`investment_assistant.papertrade.autopilot`) places its own virtual
orders under a separate book, so the two 運用実績 (equity curves) can be
compared side by side. **Simulation only -- no real orders are ever placed**
(``AGENTS.md``: "自動売買機能は実装しない"). See
:data:`investment_assistant.papertrade.PAPERTRADE_DISCLAIMER`.

This module reuses the already-reviewed P1 mechanics
(:mod:`investment_assistant.papertrade.mechanics`,
:mod:`investment_assistant.papertrade.account`,
:mod:`investment_assistant.papertrade.calendar`) rather than reimplementing
tick rounding, cash/position bookkeeping, or the capital-gains tax ledger.
It does **not** reuse the P1 engine's ``fill_price`` (slippage + price-limit
clamp against the *next* day's open): a live virtual order has no "next
day" to gap into -- the user (or the autopilot) is acting on the price
already on screen. Fills here happen directly at a known close, rounded to
the nearest valid 呼値 (tick rounds up for buys, down for sells, per
:func:`~investment_assistant.papertrade.mechanics.round_to_tick`), matching
how Minkabu's 現在値注文 behaves. This is a deliberate, documented deviation
from the AI-backtest fill model, not an oversight.

Two independent accounts share one SQLite file, distinguished by the
``account`` column on ``vt_trades`` (``"user"`` | ``"ai"``): each has its own
``vt_meta``-stored initial cash and is replayed independently through its
own :class:`~investment_assistant.papertrade.account.Account` (and therefore
its own :class:`~investment_assistant.papertrade.mechanics.TaxLedger` --
gains/losses never net across the two books). This lets a human's manual
trades and the autopilot's automated trades coexist in one store without
ever touching each other's cash or positions.

**Positions are never cached.** Every read (:func:`build_portfolio`,
:func:`build_performance`, :meth:`VirtualBroker.account_as_of`) rebuilds
state by replaying that account's ``vt_trades`` rows in ``id`` order through
a fresh :class:`Account`. One user's trade count is small (tens to low
hundreds), so replay cost is negligible, and it eliminates an entire class
of cache-invalidation bugs a cached positions table would invite -- the
trade log is the single source of truth.

**Settlement-date approximation.** T+2 受渡日 is computed via
:meth:`~investment_assistant.papertrade.calendar.TradingCalendar.add_business_days`,
which requires the target date to already be a *known* trading date. Because
every live fill happens at the *latest* available close, there is by
definition no "next day" bar loaded yet, so a plain calendar built only from
loaded bar dates could never resolve T+2 for a same-day order. This module
therefore extends the loaded calendar with a handful of synthetic Mon-Fri
dates after the last known bar date (see :func:`_extended_calendar`) purely
so a settlement date can still be displayed. This is an approximation (it
does not know about JP market holidays in that future window), but
settlement date is display/audit-only here -- v1 cash accounting is
order-date based, matching ``account.py``'s own documented choice -- so the
approximation never affects cash, positions, or tax correctness.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from pathlib import Path
from typing import Any, Literal

from investment_assistant.papertrade.account import Account, Order, Position, Side
from investment_assistant.papertrade.calendar import TradingCalendar
from investment_assistant.papertrade.mechanics import ZERO_COMMISSION, round_to_tick
from investment_assistant.papertrade.universe import Bar

JsonDict = dict[str, Any]
BarsMap = Mapping[str, Sequence[Bar]]

AccountId = Literal["user", "ai"]
_VALID_ACCOUNTS: tuple[AccountId, ...] = ("user", "ai")

DEFAULT_VIRTUAL_STORE_PATH = Path("data/runtime/virtual_trading.sqlite")
DEFAULT_INITIAL_CASH = 10_000_000.0
DEFAULT_AUTOPILOT_PRESET = "balanced"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vt_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vt_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL,
    shares INTEGER NOT NULL,
    price REAL NOT NULL,
    commission REAL NOT NULL,
    realized_pnl REAL,
    tax_delta INTEGER,
    cash_after REAL NOT NULL,
    account TEXT NOT NULL DEFAULT 'user'
);

CREATE INDEX IF NOT EXISTS idx_vt_trades_account ON vt_trades(account, id);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_side(value: str) -> Side:
    if value == "buy":
        return "buy"
    if value == "sell":
        return "sell"
    raise ValueError(f"invalid side in stored trade: {value!r}")


def _as_account(value: str) -> AccountId:
    if value == "user":
        return "user"
    if value == "ai":
        return "ai"
    raise ValueError(f"invalid account in stored trade: {value!r}")


# --- persistence -------------------------------------------------------


@dataclass(frozen=True)
class TradeRecord:
    """One persisted row of ``vt_trades``."""

    id: int
    ts: str
    trade_date: str
    ticker: str
    name: str
    side: Side
    shares: int
    price: float
    commission: float
    realized_pnl: float | None
    tax_delta: int | None
    cash_after: float
    account: AccountId


class VirtualTradingStore:
    """SQLite persistence for both virtual trading books (user + AI).

    Follows the same connect-per-call, commit-or-rollback style as
    ``papertrade/store.py``. ``CREATE TABLE IF NOT EXISTS`` makes opening an
    existing store idempotent; the default path is always overridable, and
    tests must always pass a ``tmp_path`` file.
    """

    def __init__(self, path: str | Path = DEFAULT_VIRTUAL_STORE_PATH) -> None:
        self.path = Path(path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            for account in _VALID_ACCOUNTS:
                conn.execute(
                    "INSERT OR IGNORE INTO vt_meta (key, value) VALUES (?, ?)",
                    (f"initial_cash:{account}", str(DEFAULT_INITIAL_CASH)),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO vt_meta (key, value) VALUES (?, ?)",
                    (f"created_at:{account}", _now_iso()),
                )
            conn.execute(
                "INSERT OR IGNORE INTO vt_meta (key, value) VALUES (?, ?)",
                ("autopilot:preset", DEFAULT_AUTOPILOT_PRESET),
            )
            conn.execute(
                "INSERT OR IGNORE INTO vt_meta (key, value) VALUES (?, ?)",
                ("autopilot:auto", "true"),
            )

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

    # --- meta -----------------------------------------------------------

    def _meta_str(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM vt_meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row is not None else None

    def _set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO vt_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def initial_cash(self, account: AccountId = "user") -> float:
        value = self._meta_str(f"initial_cash:{account}")
        return float(value) if value is not None else DEFAULT_INITIAL_CASH

    def created_at(self, account: AccountId = "user") -> str | None:
        return self._meta_str(f"created_at:{account}")

    def autopilot_preset(self) -> str:
        return self._meta_str("autopilot:preset") or DEFAULT_AUTOPILOT_PRESET

    def set_autopilot_preset(self, name: str) -> None:
        self._set_meta("autopilot:preset", name)

    def autopilot_auto(self) -> bool:
        """Always ``True`` -- the AI account's autopilot cannot be turned off."""
        return True

    def autopilot_last_run_date(self) -> str | None:
        return self._meta_str("autopilot:last_run_date")

    def set_autopilot_last_run_date(self, trade_date: str) -> None:
        self._set_meta("autopilot:last_run_date", trade_date)

    # --- trades -----------------------------------------------------------

    def trades(self, account: AccountId | None = None) -> list[TradeRecord]:
        sql = (
            "SELECT id, ts, trade_date, ticker, name, side, shares, price, commission, "
            "realized_pnl, tax_delta, cash_after, account FROM vt_trades"
        )
        params: tuple[Any, ...] = ()
        if account is not None:
            sql += " WHERE account = ?"
            params = (account,)
        sql += " ORDER BY id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            TradeRecord(
                id=row[0],
                ts=row[1],
                trade_date=row[2],
                ticker=row[3],
                name=row[4],
                side=_as_side(row[5]),
                shares=row[6],
                price=row[7],
                commission=row[8],
                realized_pnl=row[9],
                tax_delta=row[10],
                cash_after=row[11],
                account=_as_account(row[12]),
            )
            for row in rows
        ]

    def append_trade(
        self,
        *,
        ts: str,
        trade_date: str,
        ticker: str,
        name: str,
        side: Side,
        shares: int,
        price: float,
        commission: float,
        realized_pnl: float | None,
        tax_delta: int | None,
        cash_after: float,
        account: AccountId,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO vt_trades
                    (ts, trade_date, ticker, name, side, shares, price, commission,
                     realized_pnl, tax_delta, cash_after, account)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    trade_date,
                    ticker,
                    name,
                    side,
                    shares,
                    price,
                    commission,
                    realized_pnl,
                    tax_delta,
                    cash_after,
                    account,
                ),
            )
            return int(cursor.lastrowid or 0)

    def reset(self, initial_cash: float = DEFAULT_INITIAL_CASH) -> None:
        """Wipe both accounts' trades and meta (including autopilot state)."""

        with self._connect() as conn:
            conn.execute("DELETE FROM vt_trades")
            conn.execute("DELETE FROM vt_meta")
            for account in _VALID_ACCOUNTS:
                conn.execute(
                    "INSERT INTO vt_meta (key, value) VALUES (?, ?)",
                    (f"initial_cash:{account}", str(float(initial_cash))),
                )
                conn.execute(
                    "INSERT INTO vt_meta (key, value) VALUES (?, ?)",
                    (f"created_at:{account}", _now_iso()),
                )
            conn.execute(
                "INSERT INTO vt_meta (key, value) VALUES (?, ?)",
                ("autopilot:preset", DEFAULT_AUTOPILOT_PRESET),
            )
            conn.execute(
                "INSERT INTO vt_meta (key, value) VALUES (?, ?)",
                ("autopilot:auto", "true"),
            )


# --- calendar helpers ----------------------------------------------------


def _real_calendar(bars: BarsMap) -> TradingCalendar:
    """The trading calendar of every date actually present in ``bars``."""

    dates: set[str] = set()
    for ticker_bars in bars.values():
        for bar in ticker_bars:
            dates.add(bar.date)
    return TradingCalendar(dates)


def _extended_calendar(
    bars: BarsMap, *, lookahead: int = 10, extra_dates: Iterable[str] = ()
) -> TradingCalendar:
    """``_real_calendar`` extended with synthetic Mon-Fri dates for T+2 lookups.

    ``extra_dates`` folds in trade dates that may no longer be present in the
    currently loaded ``bars`` window (e.g. if ``daily_bars.csv`` is ever
    trimmed to a rolling window). Without this, replaying an old trade whose
    ``trade_date`` fell out of the bars window would make
    ``TradingCalendar.add_business_days`` raise ``ValueError`` for a
    settlement-date lookup that is display-only and irrelevant to cash,
    position, or tax correctness -- see the module docstring's
    "Settlement-date approximation" section.
    """

    dates = {bar.date for ticker_bars in bars.values() for bar in ticker_bars}
    dates.update(extra_dates)
    if not dates:
        return TradingCalendar(dates)
    cursor = _date.fromisoformat(max(dates))
    added = 0
    while added < lookahead:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:  # Monday=0 .. Friday=4
            dates.add(cursor.isoformat())
            added += 1
    return TradingCalendar(dates)


def _price_history(bars: BarsMap) -> dict[str, list[tuple[str, float]]]:
    return {
        ticker: sorted(((bar.date, bar.close) for bar in ticker_bars), key=lambda item: item[0])
        for ticker, ticker_bars in bars.items()
    }


def _price_as_of(history: Sequence[tuple[str, float]], as_of: str) -> float | None:
    """The latest close in ``history`` on or before ``as_of`` (forward-fill)."""

    result: float | None = None
    for bar_date, close in history:
        if bar_date > as_of:
            break
        result = close
    return result


def _latest_price_map(bars: BarsMap) -> tuple[dict[str, float], dict[str, str]]:
    prices: dict[str, float] = {}
    dates: dict[str, str] = {}
    for ticker, ticker_bars in bars.items():
        if not ticker_bars:
            continue
        latest = max(ticker_bars, key=lambda bar: bar.date)
        prices[ticker] = latest.close
        dates[ticker] = latest.date
    return prices, dates


def _latest_overall_date(bars: BarsMap) -> str | None:
    dates = [bar.date for ticker_bars in bars.values() for bar in ticker_bars]
    return max(dates) if dates else None


# --- replay ----------------------------------------------------------------


def _replay(
    trades: Sequence[TradeRecord], *, initial_cash: float, calendar: TradingCalendar
) -> Account:
    """Rebuild one account's cash + position state from its trade log.

    Every trade here was already accepted by :meth:`VirtualBroker.submit_order`
    at order time, so a rejection on replay means the trade log and the
    account state it is supposed to reproduce have diverged -- a bug, not a
    routine outcome, hence ``RuntimeError`` rather than a silent skip.
    """

    account = Account(cash=initial_cash)
    for trade in trades:
        order = Order(
            ticker=trade.ticker,
            side=trade.side,
            shares=trade.shares,
            decision_date=trade.trade_date,
        )
        if trade.side == "buy":
            result = account.execute_buy(
                order, trade.price, trade.trade_date, calendar, ZERO_COMMISSION
            )
        else:
            result = account.execute_sell(
                order, trade.price, trade.trade_date, calendar, ZERO_COMMISSION
            )
        if not result.ok:
            raise RuntimeError(
                f"virtual trading replay inconsistency: stored trade id={trade.id} "
                f"({trade.account}/{trade.side} {trade.ticker}) failed to replay "
                f"(reason={result.reason!r})"
            )
    return account


def _load_account(store: VirtualTradingStore, *, account: AccountId, bars: BarsMap) -> Account:
    trades = store.trades(account=account)
    calendar = _extended_calendar(bars, extra_dates=(t.trade_date for t in trades))
    return _replay(trades, initial_cash=store.initial_cash(account), calendar=calendar)


# --- order execution (VirtualBroker) ---------------------------------------


@dataclass(frozen=True)
class OrderRequest:
    """A decided (not yet filled) virtual order for one account's book.

    ``trade_date`` is ``None`` for a live order (fills at the latest known
    close -- the web UI's user-facing path) or an explicit historical bar
    date (the autopilot's per-cycle path, which must fill at that cycle
    date's close, not "now").
    """

    ticker: str
    side: Side
    shares: int
    account: AccountId = "user"
    name: str = ""
    trade_date: str | None = None


@dataclass(frozen=True)
class OrderFill:
    """A filled virtual order, ready for JSON serialization by the webapi layer."""

    ticker: str
    name: str
    side: Side
    shares: int
    price: float
    commission: float
    trade_date: str
    settlement_date: str
    realized_pnl: float | None
    tax_delta: int | None
    account: AccountId


@dataclass(frozen=True)
class ExecutionReport:
    """Outcome of :meth:`VirtualBroker.submit_order`.

    ``fill`` is ``None`` on rejection, with ``reason`` set to a short
    machine-readable code (``"invalid_lot"``, ``"unknown_ticker"``,
    ``"no_price"``, ``"insufficient_cash"``, ``"oversell"``) rather than
    raising -- mirrors :class:`~investment_assistant.papertrade.account.OrderResult`.
    """

    fill: OrderFill | None
    reason: str | None = None
    cash: float | None = None
    equity: float | None = None

    @property
    def ok(self) -> bool:
        return self.fill is not None


class VirtualBroker:
    """The single entry point through which every virtual order is placed.

    This is the **Phase-2 virtual execution layer**: every order placed by a
    human through the web UI (``webapi/virtual_trade.py``) and every order
    placed by the deterministic autopilot strategy
    (:mod:`investment_assistant.papertrade.autopilot`) flows through this
    same :meth:`submit_order`, regardless of caller. Shaping the order path
    this way (validate -> price -> execute -> record, behind one narrow
    broker-like surface) is what makes it straightforward to compare a
    human's and the AI's 運用実績 on equal footing, and keeps exactly one
    place where "did this order actually happen" is decided.

    A **Phase-3 real-broker adapter** would implement this same
    ``submit_order`` surface against a real brokerage API -- but is
    deliberately **not** implemented anywhere in this codebase.
    ``AGENTS.md`` prohibits real orders / auto-trading outright
    ("自動売買機能は実装しない"); adding one would require a separate,
    explicit legal review first ("実注文や自動売買を追加する場合は、
    別途法務レビューを必須にする"). This class only ever talks to the local
    SQLite trade log -- it has no network access and cannot place a real
    order.
    """

    def __init__(self, path: str | Path, *, bars: BarsMap) -> None:
        self.store = VirtualTradingStore(path)
        self.bars = bars

    def submit_order(self, request: OrderRequest) -> ExecutionReport:
        ticker = request.ticker.strip()
        if request.shares <= 0 or request.shares % 100 != 0:
            return ExecutionReport(fill=None, reason="invalid_lot")

        ticker_bars = self.bars.get(ticker)
        if not ticker_bars:
            return ExecutionReport(fill=None, reason="unknown_ticker")

        if request.trade_date is None:
            bar = max(ticker_bars, key=lambda item: item.date)
        else:
            found_bar = next(
                (item for item in ticker_bars if item.date == request.trade_date), None
            )
            if found_bar is None:
                return ExecutionReport(fill=None, reason="no_price")
            bar = found_bar

        price = round_to_tick(bar.close, side=request.side)
        trade_date = bar.date

        calendar = _extended_calendar(self.bars)
        account = _load_account(self.store, account=request.account, bars=self.bars)

        order = Order(
            ticker=ticker, side=request.side, shares=request.shares, decision_date=trade_date
        )
        realized_before = account.realized_pnl
        tax_before = account.tax_ledger.cumulative_tax_withheld
        if request.side == "buy":
            result = account.execute_buy(order, price, trade_date, calendar, ZERO_COMMISSION)
        else:
            result = account.execute_sell(order, price, trade_date, calendar, ZERO_COMMISSION)

        if not result.ok:
            assert result.reason is not None
            return ExecutionReport(fill=None, reason=result.reason)

        fill = result.fill
        assert fill is not None
        realized_pnl = (account.realized_pnl - realized_before) if request.side == "sell" else None
        tax_delta = (
            account.tax_ledger.cumulative_tax_withheld - tax_before
            if request.side == "sell"
            else None
        )

        self.store.append_trade(
            ts=_now_iso(),
            trade_date=trade_date,
            ticker=ticker,
            name=request.name,
            side=request.side,
            shares=request.shares,
            price=fill.price,
            commission=fill.commission,
            realized_pnl=realized_pnl,
            tax_delta=tax_delta,
            cash_after=account.cash,
            account=request.account,
        )

        prices, _ = _latest_price_map(self.bars)
        equity = account.equity(prices)

        order_fill = OrderFill(
            ticker=ticker,
            name=request.name,
            side=request.side,
            shares=request.shares,
            price=fill.price,
            commission=fill.commission,
            trade_date=trade_date,
            settlement_date=fill.settlement_date,
            realized_pnl=realized_pnl,
            tax_delta=tax_delta,
            account=request.account,
        )
        return ExecutionReport(fill=order_fill, cash=account.cash, equity=equity)

    def portfolio(self, account: AccountId = "user") -> PortfolioSnapshot:
        return build_portfolio(self.store.path, bars=self.bars, account=account)

    def performance(self, account: AccountId = "user") -> PerformanceResult:
        return build_performance(self.store.path, bars=self.bars, account=account)

    def account_as_of(self, account: AccountId, as_of: str) -> Account:
        """Replay ``account``'s trades through ``as_of`` (inclusive), no later.

        Used by the autopilot's per-cycle logic, which must reason about
        "positions held as of the cycle date" without ever looking ahead at
        prices or trades from a later date.
        """

        trades = [t for t in self.store.trades(account=account) if t.trade_date <= as_of]
        calendar = _extended_calendar(self.bars, extra_dates=(t.trade_date for t in trades))
        return _replay(trades, initial_cash=self.store.initial_cash(account), calendar=calendar)

    def equity_as_of(self, account: AccountId, as_of: str) -> float:
        """Mark-to-``as_of`` equity for ``account`` (no look-ahead pricing)."""

        acct = self.account_as_of(account, as_of)
        history = _price_history(self.bars)
        marks: dict[str, float] = {}
        for ticker in acct.positions:
            price = _price_as_of(history.get(ticker, ()), as_of)
            if price is not None:
                marks[ticker] = price
        return acct.equity(marks)


# --- portfolio snapshot ------------------------------------------------


@dataclass(frozen=True)
class PositionSnapshot:
    ticker: str
    shares: int
    avg_cost: float
    price: float | None
    price_date: str | None
    value: float
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None


@dataclass(frozen=True)
class PortfolioSnapshot:
    as_of: str | None
    initial_cash: float
    cash: float
    equity: float
    invested_value: float
    unrealized_pnl: float
    realized_pnl: float
    tax_withheld: int
    total_return_pct: float
    positions: tuple[PositionSnapshot, ...]
    trade_count: int


def build_portfolio(
    path: str | Path, *, bars: BarsMap, account: AccountId = "user"
) -> PortfolioSnapshot:
    """Current-state snapshot for one account: cash, positions marked at latest close."""

    store = VirtualTradingStore(path)
    trades = store.trades(account=account)
    initial_cash = store.initial_cash(account)
    calendar = _extended_calendar(bars, extra_dates=(t.trade_date for t in trades))
    acct = _replay(trades, initial_cash=initial_cash, calendar=calendar)
    prices, price_dates = _latest_price_map(bars)
    as_of = _latest_overall_date(bars)

    positions: list[PositionSnapshot] = []
    invested_value = 0.0
    unrealized_total = 0.0
    for ticker in sorted(acct.positions):
        position: Position = acct.positions[ticker]
        price = prices.get(ticker)
        value = position.shares * (price if price is not None else position.avg_cost)
        invested_value += value
        pnl: float | None = None
        pnl_pct: float | None = None
        if price is not None:
            pnl = (price - position.avg_cost) * position.shares
            unrealized_total += pnl
            if position.avg_cost:
                pnl_pct = (price / position.avg_cost - 1.0) * 100.0
        positions.append(
            PositionSnapshot(
                ticker=ticker,
                shares=position.shares,
                avg_cost=position.avg_cost,
                price=price,
                price_date=price_dates.get(ticker),
                value=value,
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl_pct,
            )
        )

    equity = acct.cash + invested_value
    total_return_pct = ((equity / initial_cash) - 1.0) * 100.0 if initial_cash else 0.0

    return PortfolioSnapshot(
        as_of=as_of,
        initial_cash=initial_cash,
        cash=acct.cash,
        equity=equity,
        invested_value=invested_value,
        unrealized_pnl=unrealized_total,
        realized_pnl=acct.realized_pnl,
        tax_withheld=acct.tax_ledger.cumulative_tax_withheld,
        total_return_pct=total_return_pct,
        positions=tuple(positions),
        trade_count=len(trades),
    )


# --- performance (equity curve) -----------------------------------------


@dataclass(frozen=True)
class EquityPoint:
    date: str
    equity: float
    cash: float


@dataclass(frozen=True)
class PerformanceResult:
    curve: tuple[EquityPoint, ...]
    initial_cash: float
    total_return_pct: float
    max_drawdown: float
    realized_pnl: float
    unrealized_pnl: float
    as_of: str | None


def _max_drawdown(equities: Sequence[float]) -> float:
    """Largest peak-to-trough decline in ``equities``, as a negative percentage.

    Deviation note: the sprint brief pointed at a shared
    ``papertrade.metrics.max_drawdown`` helper, but no ``papertrade/metrics.py``
    module exists in this worktree (only ``forecasting/metrics.py``, which is
    unrelated, and ``portfolio/loader.py``'s private ``_max_drawdown_pct``,
    which belongs to a different, off-limits package for this sprint). This
    reimplements the same standard peak-to-trough formula locally rather than
    adding a new shared ``papertrade/metrics.py`` that a parallel session
    might independently add too.
    """

    if not equities:
        return 0.0
    peak = equities[0]
    worst = 0.0
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            drawdown = (value - peak) / peak * 100.0
            worst = min(worst, drawdown)
    return round(worst, 2)


def build_performance(
    path: str | Path, *, bars: BarsMap, account: AccountId = "user"
) -> PerformanceResult:
    """Daily equity curve for one account from its first trade to the latest known date."""

    store = VirtualTradingStore(path)
    trades = store.trades(account=account)
    initial_cash = store.initial_cash(account)

    if not trades:
        return PerformanceResult(
            curve=(),
            initial_cash=initial_cash,
            total_return_pct=0.0,
            max_drawdown=0.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            as_of=None,
        )

    real_calendar = _real_calendar(bars)
    extended_calendar = _extended_calendar(bars, extra_dates=(t.trade_date for t in trades))
    first_trade_date = min(t.trade_date for t in trades)
    price_history = _price_history(bars)

    points: list[EquityPoint] = []
    baseline_date = real_calendar.nth_after(first_trade_date, -1)
    if baseline_date is not None:
        points.append(EquityPoint(date=baseline_date, equity=initial_cash, cash=initial_cash))

    account_full: Account | None = None
    for trade_date in real_calendar.dates:
        if trade_date < first_trade_date:
            continue
        relevant = [t for t in trades if t.trade_date <= trade_date]
        acct = _replay(relevant, initial_cash=initial_cash, calendar=extended_calendar)
        marks: dict[str, float] = {}
        for ticker in acct.positions:
            price = _price_as_of(price_history.get(ticker, ()), trade_date)
            if price is not None:
                marks[ticker] = price
        points.append(EquityPoint(date=trade_date, equity=acct.equity(marks), cash=acct.cash))
        account_full = acct

    assert account_full is not None  # at least one trade -> at least one date >= first_trade_date
    as_of = real_calendar.dates[-1] if real_calendar.dates else None
    unrealized_pnl = 0.0
    if as_of is not None:
        for ticker, position in account_full.positions.items():
            price = _price_as_of(price_history.get(ticker, ()), as_of)
            if price is not None:
                unrealized_pnl += (price - position.avg_cost) * position.shares

    equities = [point.equity for point in points]
    max_dd = _max_drawdown(equities)
    total_return_pct = (
        ((points[-1].equity / initial_cash) - 1.0) * 100.0 if initial_cash and points else 0.0
    )

    return PerformanceResult(
        curve=tuple(points),
        initial_cash=initial_cash,
        total_return_pct=total_return_pct,
        max_drawdown=max_dd,
        realized_pnl=account_full.realized_pnl,
        unrealized_pnl=unrealized_pnl,
        as_of=as_of,
    )
