"""Unit tests for :mod:`investment_assistant.papertrade.virtual`.

Every store lives under ``tmp_path`` -- never the real
``data/runtime/virtual_trading.sqlite`` (offline-first, per ``AGENTS.md``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.papertrade.universe import Bar
from investment_assistant.papertrade.virtual import (
    OrderRequest,
    VirtualBroker,
    VirtualTradingStore,
    build_performance,
    build_portfolio,
)


def _bars_series(ticker: str, dates_closes: list[tuple[str, float]]) -> list[Bar]:
    return [
        Bar(ticker=ticker, date=d, open=c, high=c, low=c, close=c, volume=1_000)
        for d, c in dates_closes
    ]


# --- tick rounding ------------------------------------------------------


def test_buy_rounds_up_to_tick_boundary(tmp_path: Path) -> None:
    # 3002 falls in the (3000, 5000] band -> tick size 5; 3002/5 = 600.4 -> ceil to 601*5.
    bars = {"1000": _bars_series("1000", [("2026-01-05", 3002.0)])}
    broker = VirtualBroker(tmp_path / "vt.sqlite", bars=bars)

    report = broker.submit_order(
        OrderRequest(ticker="1000", side="buy", shares=100, account="user")
    )

    assert report.ok
    assert report.fill is not None
    assert report.fill.price == 3005.0


def test_sell_rounds_down_to_tick_boundary(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"
    bars = {"1000": _bars_series("1000", [("2026-01-05", 3002.0)])}
    broker = VirtualBroker(store_path, bars=bars)
    broker.submit_order(OrderRequest(ticker="1000", side="buy", shares=100, account="user"))

    report = broker.submit_order(
        OrderRequest(ticker="1000", side="sell", shares=100, account="user")
    )

    assert report.ok
    assert report.fill is not None
    assert report.fill.price == 3000.0  # 600.4 -> floor to 600*5


# --- rejections -----------------------------------------------------------


def test_submit_order_rejects_invalid_lot(tmp_path: Path) -> None:
    bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0)])}
    broker = VirtualBroker(tmp_path / "vt.sqlite", bars=bars)

    report = broker.submit_order(
        OrderRequest(ticker="1000", side="buy", shares=150, account="user")
    )

    assert not report.ok
    assert report.reason == "invalid_lot"


def test_submit_order_rejects_unknown_ticker(tmp_path: Path) -> None:
    bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0)])}
    broker = VirtualBroker(tmp_path / "vt.sqlite", bars=bars)

    report = broker.submit_order(
        OrderRequest(ticker="9999", side="buy", shares=100, account="user")
    )

    assert not report.ok
    assert report.reason == "unknown_ticker"


def test_submit_order_rejects_insufficient_cash(tmp_path: Path) -> None:
    bars = {"1000": _bars_series("1000", [("2026-01-05", 100_000.0)])}
    broker = VirtualBroker(tmp_path / "vt.sqlite", bars=bars)

    # 200 shares * 100,000 yen = 20,000,000 > default 10,000,000 initial cash.
    report = broker.submit_order(
        OrderRequest(ticker="1000", side="buy", shares=200, account="user")
    )

    assert not report.ok
    assert report.reason == "insufficient_cash"


def test_submit_order_rejects_oversell(tmp_path: Path) -> None:
    bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0)])}
    broker = VirtualBroker(tmp_path / "vt.sqlite", bars=bars)

    report = broker.submit_order(
        OrderRequest(ticker="1000", side="sell", shares=100, account="user")
    )

    assert not report.ok
    assert report.reason == "oversell"


# --- tax withholding / refund -----------------------------------------------


def test_sell_gain_withholds_tax_then_later_loss_refunds(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"

    bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0)])}
    broker = VirtualBroker(store_path, bars=bars)
    buy = broker.submit_order(OrderRequest(ticker="1000", side="buy", shares=100, account="user"))
    assert buy.ok

    bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0), ("2026-01-06", 2000.0)])}
    broker = VirtualBroker(store_path, bars=bars)
    sell_gain = broker.submit_order(
        OrderRequest(ticker="1000", side="sell", shares=100, account="user")
    )
    assert sell_gain.ok
    assert sell_gain.fill is not None
    assert sell_gain.fill.realized_pnl == pytest.approx(100_000.0)
    # 100,000 * 20.315% = 20,315 (exact, no rounding ambiguity).
    assert sell_gain.fill.tax_delta == 20_315

    bars = {
        "1000": _bars_series("1000", [("2026-01-05", 1000.0), ("2026-01-06", 2000.0)]),
        "2000": _bars_series("2000", [("2026-01-07", 1000.0)]),
    }
    broker = VirtualBroker(store_path, bars=bars)
    buy2 = broker.submit_order(OrderRequest(ticker="2000", side="buy", shares=100, account="user"))
    assert buy2.ok

    bars = {
        "1000": _bars_series("1000", [("2026-01-05", 1000.0), ("2026-01-06", 2000.0)]),
        "2000": _bars_series("2000", [("2026-01-07", 1000.0), ("2026-01-08", 500.0)]),
    }
    broker = VirtualBroker(store_path, bars=bars)
    sell_loss = broker.submit_order(
        OrderRequest(ticker="2000", side="sell", shares=100, account="user")
    )
    assert sell_loss.ok
    assert sell_loss.fill is not None
    assert sell_loss.fill.realized_pnl == pytest.approx(-50_000.0)
    # cumulative pnl 100,000 - 50,000 = 50,000 -> tax due round(50,000 * 0.20315) = 10,158
    # (10,157.5 rounds half-up); delta vs the 20,315 already withheld is a 10,157 refund.
    assert sell_loss.fill.tax_delta == -10_157


# --- replay determinism -----------------------------------------------------


def test_replay_is_deterministic_across_store_reopen(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"
    bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0)])}
    broker = VirtualBroker(store_path, bars=bars)
    broker.submit_order(OrderRequest(ticker="1000", side="buy", shares=100, account="user"))

    snapshot1 = build_portfolio(store_path, bars=bars, account="user")
    # Reopen: a brand-new broker/store instance over the same sqlite file.
    broker2 = VirtualBroker(store_path, bars=bars)
    snapshot2 = broker2.portfolio(account="user")

    assert snapshot1 == snapshot2


# --- equity curve -----------------------------------------------------------


def test_equity_curve_forward_fills_missing_ticker_bar(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"
    buy_bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0)])}
    broker = VirtualBroker(store_path, bars=buy_bars)
    buy = broker.submit_order(OrderRequest(ticker="1000", side="buy", shares=100, account="user"))
    assert buy.ok

    # "1000" has no bar on 01-06 (forward-filled from 01-05); "2000" anchors 01-06 in the
    # calendar so the date still appears in the curve.
    full_bars = {
        "1000": _bars_series("1000", [("2026-01-05", 1000.0), ("2026-01-07", 1050.0)]),
        "2000": _bars_series(
            "2000", [("2026-01-05", 500.0), ("2026-01-06", 505.0), ("2026-01-07", 510.0)]
        ),
    }
    result = build_performance(store_path, bars=full_bars, account="user")

    dates = [point.date for point in result.curve]
    assert dates == ["2026-01-05", "2026-01-06", "2026-01-07"]

    # 05: bought 100 @ 1000 (tick=1, no rounding) -> cash 9,900,000 + 100*1000 = 10,000,000.
    assert result.curve[0].cash == pytest.approx(9_900_000.0)
    assert result.curve[0].equity == pytest.approx(10_000_000.0)
    # 06: no bar for "1000" -> forward-filled at 1000 -> equity unchanged.
    assert result.curve[1].equity == pytest.approx(10_000_000.0)
    # 07: "1000" closes at 1050 -> equity = 9,900,000 + 100*1050 = 10,005,000.
    assert result.curve[2].equity == pytest.approx(10_005_000.0)

    assert result.as_of == "2026-01-07"
    assert result.unrealized_pnl == pytest.approx(5_000.0)
    assert result.total_return_pct == pytest.approx(0.05)
    assert result.max_drawdown <= 0.0


# --- two-account isolation ---------------------------------------------------


def test_ai_and_user_accounts_are_isolated(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"
    bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0)])}
    broker = VirtualBroker(store_path, bars=bars)

    ai_buy = broker.submit_order(OrderRequest(ticker="1000", side="buy", shares=100, account="ai"))
    assert ai_buy.ok

    user_portfolio = build_portfolio(store_path, bars=bars, account="user")
    ai_portfolio = build_portfolio(store_path, bars=bars, account="ai")

    assert user_portfolio.positions == ()
    assert user_portfolio.trade_count == 0
    assert user_portfolio.cash == pytest.approx(user_portfolio.initial_cash)

    assert len(ai_portfolio.positions) == 1
    assert ai_portfolio.positions[0].ticker == "1000"
    assert ai_portfolio.cash < ai_portfolio.initial_cash


def test_realized_pnl_and_tax_do_not_leak_between_accounts(tmp_path: Path) -> None:
    """A taxable gain booked in one account's book must never surface in the other's."""

    store_path = tmp_path / "vt.sqlite"
    bars = {
        "1000": _bars_series(
            "1000", [("2026-01-05", 1000.0), ("2026-01-06", 2000.0), ("2026-01-07", 2000.0)]
        )
    }
    broker = VirtualBroker(store_path, bars=bars)

    # "ai" books a large realized gain (buy low, sell high); "user" only buys (no realization).
    ai_buy = broker.submit_order(
        OrderRequest(
            ticker="1000", side="buy", shares=100, account="ai", trade_date="2026-01-05"
        )
    )
    assert ai_buy.ok
    ai_sell = broker.submit_order(
        OrderRequest(
            ticker="1000", side="sell", shares=100, account="ai", trade_date="2026-01-06"
        )
    )
    assert ai_sell.ok
    assert ai_sell.fill is not None
    assert ai_sell.fill.realized_pnl is not None and ai_sell.fill.realized_pnl > 0
    assert ai_sell.fill.tax_delta is not None and ai_sell.fill.tax_delta > 0

    user_buy = broker.submit_order(
        OrderRequest(
            ticker="1000", side="buy", shares=100, account="user", trade_date="2026-01-07"
        )
    )
    assert user_buy.ok

    user_portfolio = build_portfolio(store_path, bars=bars, account="user")
    ai_portfolio = build_portfolio(store_path, bars=bars, account="ai")

    assert user_portfolio.realized_pnl == pytest.approx(0.0)
    assert user_portfolio.tax_withheld == 0
    assert ai_portfolio.realized_pnl > 0
    assert ai_portfolio.tax_withheld > 0

    user_performance = build_performance(store_path, bars=bars, account="user")
    ai_performance = build_performance(store_path, bars=bars, account="ai")

    assert user_performance.realized_pnl == pytest.approx(0.0)
    assert ai_performance.realized_pnl > 0


def test_reset_wipes_both_accounts(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"
    bars = {"1000": _bars_series("1000", [("2026-01-05", 1000.0)])}
    broker = VirtualBroker(store_path, bars=bars)
    broker.submit_order(OrderRequest(ticker="1000", side="buy", shares=100, account="user"))
    broker.submit_order(OrderRequest(ticker="1000", side="buy", shares=100, account="ai"))

    store = VirtualTradingStore(store_path)
    store.reset(initial_cash=5_000_000.0)

    assert store.trades() == []
    assert store.initial_cash("user") == pytest.approx(5_000_000.0)
    assert store.initial_cash("ai") == pytest.approx(5_000_000.0)
    assert store.autopilot_last_run_date() is None
    assert store.autopilot_auto() is True
    assert store.autopilot_preset() == "balanced"


# --- replay against a trimmed bars window --------------------------------


def test_replay_survives_trade_dates_outside_the_current_bars_window(tmp_path: Path) -> None:
    """A trade recorded when older bars were loaded must still replay cleanly
    once ``daily_bars.csv`` no longer carries that date (e.g. a rolling
    window). The settlement-date lookup this exercises is display-only, but
    it must not raise and take down the whole portfolio/performance read.
    """

    store_path = tmp_path / "vt.sqlite"
    wide_bars = {
        "1000": _bars_series(
            "1000", [("2026-01-05", 1000.0), ("2026-01-06", 1000.0), ("2026-01-07", 1000.0)]
        )
    }
    broker = VirtualBroker(store_path, bars=wide_bars)
    buy = broker.submit_order(
        OrderRequest(
            ticker="1000", side="buy", shares=100, account="user", trade_date="2026-01-05"
        )
    )
    assert buy.ok

    # Simulate the bars source trimming away the trade's date (2026-01-05 is gone).
    trimmed_bars = {
        "1000": _bars_series("1000", [("2026-01-06", 1000.0), ("2026-01-07", 1000.0)])
    }

    portfolio = build_portfolio(store_path, bars=trimmed_bars, account="user")
    assert portfolio.trade_count == 1
    assert portfolio.positions[0].ticker == "1000"

    performance = build_performance(store_path, bars=trimmed_bars, account="user")
    assert performance.curve

    trimmed_broker = VirtualBroker(store_path, bars=trimmed_bars)
    account = trimmed_broker.account_as_of("user", "2026-01-07")
    assert account.positions["1000"].shares == 100
