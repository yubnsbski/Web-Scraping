"""JSON API handlers for the ``/api/vtrade/*`` virtual trading endpoints.

Thin adapter, matching the shape of ``webapi/chat.py`` and
``webapi/market.py``: every handler here is a plain ``dict in -> dict out``
function the framework-agnostic router in ``webapi/service.py`` calls
directly. See :mod:`investment_assistant.papertrade.virtual` for the actual
simulation engine (``VirtualBroker``, ``build_portfolio``,
``build_performance``) and :mod:`investment_assistant.papertrade.autopilot`
for the deterministic AI strategy this module lazily ticks forward.

**Two rejection shapes, on purpose.** A malformed *request* (missing
ticker, a non-buy/non-sell ``side``, a non-numeric ``shares``) is a caller
bug and raises :class:`~investment_assistant.webapi.errors.ApiError`, which
``handle_api`` turns into a non-200 HTTP response. A well-formed order the
*broker* declines for a business reason (odd lot, insufficient virtual cash,
oversell, unknown ticker) is an expected, routine outcome -- it comes back
as an HTTP 200 body ``{"ok": false, "reason": <code>, "message": <Japanese>}``
so the frontend can show it inline without treating it as a network/server
error. ``reason`` mirrors :class:`~investment_assistant.papertrade.virtual.ExecutionReport`'s
machine-readable codes; ``message`` is the matching user-facing Japanese text.

**Data source.** Bars come from ``local_docs/market/daily_bars.csv`` via
:func:`~investment_assistant.papertrade.universe.load_daily_bars`; names and
sectors come from ``local_docs/jpx/data_j_converted.csv`` via
:func:`~investment_assistant.papertrade.universe.load_sector_map`. Both are
read-only inputs this module never writes (that CSV/JPX-audit tooling
belongs to a different, parallel workstream -- see ``.claude/active-team.md``).
Paths are held in a small module-level :class:`_DataSource` record,
overridable via :func:`configure` so tests never touch the real
``local_docs/`` tree; each load is cached at module scope keyed by
``(path, mtime)`` so a hot ``/api/vtrade/*`` request doesn't re-parse the
full daily-bars CSV on every call, while a test (or a real data refresh)
that replaces the file on disk is picked up on the next call without a
process restart.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from investment_assistant.papertrade import PAPERTRADE_DISCLAIMER, autopilot
from investment_assistant.papertrade.mechanics import round_to_tick
from investment_assistant.papertrade.universe import SectorInfo, load_daily_bars, load_sector_map
from investment_assistant.papertrade.virtual import (
    DEFAULT_INITIAL_CASH,
    DEFAULT_VIRTUAL_STORE_PATH,
    AccountId,
    BarsMap,
    OrderRequest,
    VirtualBroker,
    VirtualTradingStore,
    build_performance,
    build_portfolio,
)
from investment_assistant.webapi.errors import ApiError

JsonDict = dict[str, Any]
SectorMap = dict[str, SectorInfo]

DEFAULT_DAILY_BARS_PATH = Path("local_docs/market/daily_bars.csv")
DEFAULT_JPX_MASTER_PATH = Path("local_docs/jpx/data_j_converted.csv")

_MAX_BARS_TICKERS = 24
_DEFAULT_BARS_DAYS = 90
_MAX_BARS_DAYS = 400
_MAX_LIVE_TICKERS = 24

_JST = ZoneInfo("Asia/Tokyo")
# TSE regular session, ignoring exchange holidays -- this only gates whether
# it's worth spending a Yahoo Finance fetch on "is the market moving right
# now", not a trading-calendar authority.
_MORNING_SESSION = (dt.time(9, 0), dt.time(11, 30))
_AFTERNOON_SESSION = (dt.time(12, 30), dt.time(15, 0))

_REASON_MESSAGES: dict[str, str] = {
    "invalid_lot": "株数は100株（単元）の倍数で入力してください",
    "insufficient_cash": "仮想資金が不足しています",
    "oversell": "保有株数を超える売り注文はできません",
    "unknown_ticker": "銘柄コードが見つかりません（データ未収録の可能性があります）",
    "no_price": "価格情報が見つかりません（指定した日の株価データがありません）",
}
_DEFAULT_REASON_MESSAGE = "注文を実行できませんでした"


# --- data source / cache ----------------------------------------------------


@dataclass
class _DataSource:
    daily_bars_path: Path = DEFAULT_DAILY_BARS_PATH
    jpx_master_path: Path = DEFAULT_JPX_MASTER_PATH
    store_path: Path = DEFAULT_VIRTUAL_STORE_PATH


_source = _DataSource()
_bars_cache: dict[tuple[str, float], BarsMap] = {}
_sectors_cache: dict[tuple[str, float], SectorMap] = {}

# Test-only seams for /api/vtrade/live: real usage never sets these, so the
# handler calls the real clock and the real Yahoo Finance fetcher.
_clock_override: Callable[[], dt.datetime] | None = None
_intraday_fetch_override: Callable[[str], str] | None = None

# The HTTP layer is a ThreadingHTTPServer (see webapi/server.py), so two
# requests can hit these handlers concurrently -- e.g. the web UI open in two
# tabs, each triggering the autopilot lazy tick at once. Every path that
# MUTATES the virtual book (orders, resets, autopilot cycles, config writes)
# serializes on this process-local lock so a catch-up can never run the same
# bar date twice and interleaved writes can never corrupt the trade log.
# Read-only endpoints stay lock-free (SQLite handles concurrent readers).
_MUTATION_LOCK = threading.Lock()


def configure(
    *,
    daily_bars_path: str | Path | None = None,
    jpx_master_path: str | Path | None = None,
    store_path: str | Path | None = None,
    clock: Callable[[], dt.datetime] | None = None,
    intraday_fetch: Callable[[str], str] | None = None,
) -> None:
    """Override this module's data source paths (tests only -- never call in production)."""

    global _source, _clock_override, _intraday_fetch_override
    _source = _DataSource(
        daily_bars_path=(
            Path(daily_bars_path) if daily_bars_path is not None else _source.daily_bars_path
        ),
        jpx_master_path=(
            Path(jpx_master_path) if jpx_master_path is not None else _source.jpx_master_path
        ),
        store_path=Path(store_path) if store_path is not None else _source.store_path,
    )
    if clock is not None:
        _clock_override = clock
    if intraday_fetch is not None:
        _intraday_fetch_override = intraday_fetch


def reset_data_source() -> None:
    """Restore the default data source paths (test teardown)."""

    global _source, _clock_override, _intraday_fetch_override
    _source = _DataSource()
    _bars_cache.clear()
    _sectors_cache.clear()
    _clock_override = None
    _intraday_fetch_override = None


def _cache_key(path: Path) -> tuple[str, float]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    return (str(path), mtime)


def _bars() -> BarsMap:
    path = _source.daily_bars_path
    key = _cache_key(path)
    if key not in _bars_cache:
        _bars_cache.clear()
        _bars_cache[key] = load_daily_bars(path) if path.is_file() else {}
    return _bars_cache[key]


def _sectors() -> SectorMap:
    path = _source.jpx_master_path
    key = _cache_key(path)
    if key not in _sectors_cache:
        _sectors_cache.clear()
        _sectors_cache[key] = load_sector_map(path) if path.is_file() else {}
    return _sectors_cache[key]


def _store() -> VirtualTradingStore:
    return VirtualTradingStore(_source.store_path)


def _rejection(reason: str) -> JsonDict:
    return {
        "ok": False,
        "reason": reason,
        "message": _REASON_MESSAGES.get(reason, _DEFAULT_REASON_MESSAGE),
    }


# --- shared payload builders -------------------------------------------------


def _portfolio_payload(
    store: VirtualTradingStore, bars: BarsMap, sectors: SectorMap, *, account: AccountId
) -> JsonDict:
    snapshot = build_portfolio(store.path, bars=bars, account=account)
    positions: list[JsonDict] = []
    for position in snapshot.positions:
        info = sectors.get(position.ticker)
        positions.append(
            {
                "ticker": position.ticker,
                "name": info.name if info else "",
                "sector": info.sector33 if info else "",
                "shares": position.shares,
                "avg_cost": position.avg_cost,
                "price": position.price,
                "price_date": position.price_date,
                "value": position.value,
                "unrealized_pnl": position.unrealized_pnl,
                "unrealized_pnl_pct": position.unrealized_pnl_pct,
            }
        )
    return {
        "as_of": snapshot.as_of,
        "initial_cash": snapshot.initial_cash,
        "cash": snapshot.cash,
        "equity": snapshot.equity,
        "invested_value": snapshot.invested_value,
        "unrealized_pnl": snapshot.unrealized_pnl,
        "realized_pnl": snapshot.realized_pnl,
        "tax_withheld": snapshot.tax_withheld,
        "total_return_pct": snapshot.total_return_pct,
        "positions": positions,
        "trade_count": snapshot.trade_count,
        "disclaimer": PAPERTRADE_DISCLAIMER,
    }


def _performance_payload(
    store: VirtualTradingStore, bars: BarsMap, *, account: AccountId
) -> JsonDict:
    result = build_performance(store.path, bars=bars, account=account)
    return {
        "curve": [
            {"date": point.date, "equity": point.equity, "cash": point.cash}
            for point in result.curve
        ],
        "initial_cash": result.initial_cash,
        "total_return_pct": result.total_return_pct,
        "max_drawdown": result.max_drawdown,
        "realized_pnl": result.realized_pnl,
        "unrealized_pnl": result.unrealized_pnl,
        "as_of": result.as_of,
        "disclaimer": PAPERTRADE_DISCLAIMER,
    }


# --- endpoints ---------------------------------------------------------------


def vtrade_quote(body: JsonDict) -> JsonDict:
    """``POST /api/vtrade/quote`` -- latest close + minimum buy cost for one ticker."""

    ticker = str(body.get("ticker") or "").strip()
    if not ticker:
        raise ApiError("ticker is required")

    ticker_bars = _bars().get(ticker)
    if not ticker_bars:
        return _rejection("unknown_ticker")

    latest = max(ticker_bars, key=lambda bar: bar.date)
    info = _sectors().get(ticker)
    min_cost = round_to_tick(latest.close, side="buy") * 100
    return {
        "ok": True,
        "ticker": ticker,
        "name": info.name if info else "",
        "sector": info.sector33 if info else "",
        "price": latest.close,
        "date": latest.date,
        "lot": 100,
        "min_cost": min_cost,
    }


def vtrade_portfolio(_body: JsonDict) -> JsonDict:
    """``GET /api/vtrade/portfolio`` -- the user's current virtual book."""

    return _portfolio_payload(_store(), _bars(), _sectors(), account="user")


def vtrade_order(body: JsonDict) -> JsonDict:
    """``POST /api/vtrade/order`` -- place one user virtual buy/sell order."""

    ticker = str(body.get("ticker") or "").strip()
    if not ticker:
        raise ApiError("ticker is required")

    side = body.get("side")
    if side not in ("buy", "sell"):
        raise ApiError("side must be 'buy' or 'sell'")

    shares = _require_positive_int(body.get("shares"), field="shares")

    sectors = _sectors()
    info = sectors.get(ticker)
    broker = VirtualBroker(_store().path, bars=_bars())
    with _MUTATION_LOCK:
        report = broker.submit_order(
            OrderRequest(
                ticker=ticker,
                side=side,
                shares=shares,
                account="user",
                name=info.name if info else "",
            )
        )
    if not report.ok:
        return _rejection(report.reason or "unknown")

    fill = report.fill
    assert fill is not None
    return {
        "ok": True,
        "fill": {
            "ticker": fill.ticker,
            "name": fill.name,
            "side": fill.side,
            "shares": fill.shares,
            "price": fill.price,
            "commission": fill.commission,
            "trade_date": fill.trade_date,
            "settlement_date": fill.settlement_date,
            "realized_pnl": fill.realized_pnl,
            "tax_delta": fill.tax_delta,
        },
        "cash": report.cash,
        "equity": report.equity,
    }


def vtrade_history(_body: JsonDict) -> JsonDict:
    """``GET /api/vtrade/history`` -- every trade, both accounts, newest first."""

    trades = sorted(_store().trades(), key=lambda trade: trade.id, reverse=True)
    return {
        "trades": [
            {
                "id": trade.id,
                "ts": trade.ts,
                "trade_date": trade.trade_date,
                "ticker": trade.ticker,
                "name": trade.name,
                "side": trade.side,
                "shares": trade.shares,
                "price": trade.price,
                "commission": trade.commission,
                "realized_pnl": trade.realized_pnl,
                "tax_delta": trade.tax_delta,
                "cash_after": trade.cash_after,
                "account": trade.account,
            }
            for trade in trades
        ],
        "count": len(trades),
    }


def vtrade_performance(_body: JsonDict) -> JsonDict:
    """``GET /api/vtrade/performance`` -- the user's equity curve."""

    return _performance_payload(_store(), _bars(), account="user")


def vtrade_reset(body: JsonDict) -> JsonDict:
    """``POST /api/vtrade/reset`` -- wipe both books (requires explicit confirm)."""

    if body.get("confirm") is not True:
        raise ApiError("confirm must be true to reset virtual trading data")

    initial_cash = DEFAULT_INITIAL_CASH
    raw_cash = body.get("initial_cash")
    if raw_cash is not None:
        try:
            initial_cash = float(raw_cash)
        except (TypeError, ValueError) as exc:
            raise ApiError("initial_cash must be a number") from exc
        if initial_cash <= 0:
            raise ApiError("initial_cash must be positive")

    with _MUTATION_LOCK:
        _store().reset(initial_cash=initial_cash)
    return {"ok": True, "initial_cash": initial_cash}


def vtrade_bars(body: JsonDict) -> JsonDict:
    """``POST /api/vtrade/bars`` -- recent OHLCV series for up to 24 tickers."""

    tickers = _ticker_list(body.get("tickers"))
    if not tickers:
        raise ApiError("tickers must be a non-empty list")
    tickers = tickers[:_MAX_BARS_TICKERS]

    days = _DEFAULT_BARS_DAYS
    raw_days = body.get("days")
    if raw_days is not None:
        try:
            days = int(raw_days)
        except (TypeError, ValueError) as exc:
            raise ApiError("days must be an integer") from exc
    days = max(1, min(days, _MAX_BARS_DAYS))

    bars_map = _bars()
    sectors = _sectors()
    as_of = _latest_overall_date(bars_map)

    series: list[JsonDict] = []
    missing: list[str] = []
    for ticker in tickers:
        ticker_bars = bars_map.get(ticker)
        if not ticker_bars:
            missing.append(ticker)
            continue
        window = sorted(ticker_bars, key=lambda bar: bar.date)[-days:]
        info = sectors.get(ticker)
        last_close = window[-1].close if window else None
        prev_close = window[-2].close if len(window) >= 2 else None
        day_change_pct = (
            (last_close / prev_close - 1.0) * 100.0
            if last_close is not None and prev_close
            else None
        )
        period_change_pct = (
            (window[-1].close / window[0].close - 1.0) * 100.0
            if window and window[0].close
            else None
        )
        series.append(
            {
                "ticker": ticker,
                "name": info.name if info else "",
                "sector": info.sector33 if info else "",
                "bars": [
                    {
                        "date": bar.date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    }
                    for bar in window
                ],
                "last_close": last_close,
                "prev_close": prev_close,
                "day_change_pct": day_change_pct,
                "period_change_pct": period_change_pct,
            }
        )

    return {"as_of": as_of, "series": series, "missing": missing}


def _is_tse_session_open(now: dt.datetime) -> bool:
    """True during TSE regular trading hours (weekday 9:00-11:30 / 12:30-15:00 JST).

    Ignores exchange holidays -- this is a cheap gate on "is it worth fetching
    a live price right now", not a trading-calendar authority.
    """

    local = now.astimezone(_JST)
    if local.weekday() >= 5:
        return False
    t = local.time()
    in_morning = _MORNING_SESSION[0] <= t <= _MORNING_SESSION[1]
    in_afternoon = _AFTERNOON_SESSION[0] <= t <= _AFTERNOON_SESSION[1]
    return in_morning or in_afternoon


def vtrade_live(body: JsonDict) -> JsonDict:
    """``POST /api/vtrade/live`` -- latest intraday tick per ticker, market hours only.

    Outside TSE hours this returns immediately with ``open: false`` and makes
    no network call. During market hours it re-scrapes each ticker's Yahoo
    Finance Japan quote page (see ``portfolio/yahoo_intraday.py``) for the most
    recent minute bar -- a polling snapshot, not a push stream, so the
    frontend re-calls this every ~30-60s while the 仮想取引 tab is open to get
    a "live" feel during the trading session.
    """

    tickers = _ticker_list(body.get("tickers"))[:_MAX_LIVE_TICKERS]
    now = (_clock_override or (lambda: dt.datetime.now(_JST)))()
    is_open = _is_tse_session_open(now)
    if not tickers or not is_open:
        return {"open": is_open, "as_of": now.isoformat(), "quotes": {}}

    from investment_assistant.portfolio._market_common import DEFAULT_YAHOO_RATE_LIMIT_POLICY
    from investment_assistant.portfolio.yahoo_intraday import fetch_yahoo_intraday

    result = fetch_yahoo_intraday(
        tickers, fetch=_intraday_fetch_override, rate_limit=DEFAULT_YAHOO_RATE_LIMIT_POLICY
    )
    intraday = result.get("intraday")
    quotes: JsonDict = {}
    if isinstance(intraday, dict):
        for ticker, ticks in intraday.items():
            if not ticks:
                continue
            last = ticks[-1]
            price = last.get("close")
            if price is None:
                continue
            quotes[ticker] = {"price": price, "time": last.get("time")}
    return {
        "open": True,
        "as_of": now.isoformat(),
        "quotes": quotes,
        "notes": result.get("notes", {}),
    }


def vtrade_ai_portfolio(_body: JsonDict) -> JsonDict:
    """``GET /api/vtrade/ai/portfolio`` -- lazily ticks autopilot, then the AI's book."""

    store = _store()
    bars = _bars()
    sectors = _sectors()
    with _MUTATION_LOCK:
        autopilot.catch_up(store, bars, sectors)
    payload = _portfolio_payload(store, bars, sectors, account="ai")
    payload["preset"] = store.autopilot_preset()
    payload["last_run_date"] = store.autopilot_last_run_date()
    payload["auto"] = store.autopilot_auto()
    return payload


def vtrade_ai_performance(_body: JsonDict) -> JsonDict:
    """``GET /api/vtrade/ai/performance`` -- lazily ticks autopilot, then its equity curve."""

    store = _store()
    bars = _bars()
    sectors = _sectors()
    with _MUTATION_LOCK:
        autopilot.catch_up(store, bars, sectors)
    return _performance_payload(store, bars, account="ai")


def vtrade_autopilot_run(_body: JsonDict) -> JsonDict:
    """``POST /api/vtrade/autopilot/run`` -- force one catch-up regardless of the auto flag."""

    store = _store()
    with _MUTATION_LOCK:
        summaries = autopilot.catch_up(store, _bars(), _sectors(), force=True)
    return {
        "ok": True,
        "ran": [
            {"date": summary.date, "buys": summary.buy_count, "sells": summary.sell_count}
            for summary in summaries
        ],
        "last_run_date": store.autopilot_last_run_date(),
    }


def vtrade_autopilot_config(body: JsonDict) -> JsonDict:
    """``POST /api/vtrade/autopilot/config`` -- update the persisted preset.

    The autopilot's ``auto`` flag is not configurable: the AI account always
    runs its lazy catch-up tick, so a request that tries to turn it off is
    rejected rather than silently ignored.
    """

    store = _store()

    raw_preset = body.get("preset")
    preset_name: str | None = None
    if raw_preset is not None:
        preset_name = str(raw_preset).strip()
        if preset_name not in autopilot.PRESETS:
            raise ApiError(
                f"unknown preset: {preset_name!r} (expected one of "
                f"{sorted(autopilot.PRESETS)})"
            )

    raw_auto = body.get("auto")
    if raw_auto is not None and raw_auto is not True:
        raise ApiError("auto cannot be disabled -- the AI account's autopilot always runs")

    with _MUTATION_LOCK:
        if preset_name is not None:
            store.set_autopilot_preset(preset_name)

    return {"ok": True, "preset": store.autopilot_preset(), "auto": store.autopilot_auto()}


# --- small parsing helpers ----------------------------------------------------


def _require_positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise ApiError(f"{field} must be a positive integer")
    if isinstance(value, int):
        shares = value
    elif isinstance(value, float) and value.is_integer():
        shares = int(value)
    else:
        raise ApiError(f"{field} must be a positive integer")
    if shares <= 0:
        raise ApiError(f"{field} must be a positive integer")
    return shares


def _ticker_list(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part for part in raw.replace(",", " ").split() if part]
    return []


def _latest_overall_date(bars: BarsMap) -> str | None:
    dates = [bar.date for ticker_bars in bars.values() for bar in ticker_bars]
    return max(dates) if dates else None
