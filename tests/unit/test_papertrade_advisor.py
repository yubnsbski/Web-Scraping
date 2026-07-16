"""Unit tests for :mod:`investment_assistant.papertrade.advisor`.

All-synthetic bars and a ``tmp_path`` store -- offline-first per ``AGENTS.md``.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from investment_assistant.papertrade import advisor
from investment_assistant.papertrade.autopilot import BALANCED
from investment_assistant.papertrade.universe import Bar, SectorInfo
from investment_assistant.papertrade.virtual import (
    OrderRequest,
    VirtualBroker,
    VirtualTradingStore,
)


def _bars(ticker: str, closes: list[float], *, start: date = date(2026, 1, 1)) -> list[Bar]:
    out: list[Bar] = []
    d = start
    for close in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(
            Bar(
                ticker=ticker,
                date=d.isoformat(),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=200_000,
            )
        )
        d += timedelta(days=1)
    return out


_SECTORS = {
    "1000": SectorInfo(
        ticker="1000", name="テスト電力", sector33="電気・ガス業", market="プライム（内国株式）"
    )
}


def test_position_signals_ma_gap_and_lines() -> None:
    # 30 flat bars at 1000 then a jump to 1200: price is above its 20-day MA.
    closes = [1000.0] * 30 + [1200.0]
    bars = {"1000": _bars("1000", closes)}

    signal = advisor.build_position_signals(
        bars,
        _SECTORS,
        BALANCED,
        ticker="1000",
        name="",
        shares=100,
        avg_cost=1000.0,
        price=1200.0,
        unrealized_pnl_pct=20.0,
    )

    assert signal.name == "テスト電力"
    assert signal.sector == "電気・ガス業"
    assert signal.ma20_gap_pct is not None and signal.ma20_gap_pct > 0
    assert signal.momentum_60d_pct is not None and signal.momentum_60d_pct > 0
    # BALANCED: stop -8% / take +15% of avg_cost, tick-rounded downward (sell).
    assert signal.stop_loss_price == 920.0
    assert signal.take_profit_price == 1150.0


def test_timing_stats_scores_early_sell_and_good_buy() -> None:
    # Rising series: a buy early on is well-timed; a sell mid-way is an
    # early sell (the price keeps rising afterwards).
    closes = [1000.0 + 10.0 * i for i in range(40)]
    bars = {"1000": _bars("1000", closes)}
    all_dates = [bar.date for bar in bars["1000"]]

    from investment_assistant.papertrade.virtual import TradeRecord

    trades = [
        TradeRecord(
            id=1,
            ts="t",
            trade_date=all_dates[5],
            ticker="1000",
            name="",
            side="buy",
            shares=100,
            price=closes[5],
            commission=0.0,
            realized_pnl=None,
            tax_delta=None,
            cash_after=0.0,
            account="user",
        ),
        TradeRecord(
            id=2,
            ts="t",
            trade_date=all_dates[20],
            ticker="1000",
            name="",
            side="sell",
            shares=100,
            price=closes[20],
            commission=0.0,
            realized_pnl=0.0,
            tax_delta=0,
            cash_after=0.0,
            account="user",
        ),
        # Too recent to judge: fewer than horizon bars after it -> skipped.
        TradeRecord(
            id=3,
            ts="t",
            trade_date=all_dates[-2],
            ticker="1000",
            name="",
            side="buy",
            shares=100,
            price=closes[-2],
            commission=0.0,
            realized_pnl=None,
            tax_delta=None,
            cash_after=0.0,
            account="user",
        ),
    ]

    stats = advisor.build_timing_stats(trades, bars)

    assert stats.buys_evaluated == 1
    assert stats.buy_timing_win_rate_pct == 100.0
    assert stats.avg_move_after_buy_pct is not None and stats.avg_move_after_buy_pct > 0
    assert stats.sells_evaluated == 1
    # Price rose after the sell -> the sell was NOT well-timed.
    assert stats.sell_timing_win_rate_pct == 0.0
    assert stats.avg_move_after_sell_pct is not None and stats.avg_move_after_sell_pct > 0


def test_build_advice_context_and_local_advice(tmp_path: Path) -> None:
    closes = [1000.0] * 35
    bars = {"1000": _bars("1000", closes)}
    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    broker = VirtualBroker(store.path, bars=bars)
    report = broker.submit_order(
        OrderRequest(ticker="1000", side="buy", shares=100, account="user", name="テスト電力")
    )
    assert report.ok

    context = advisor.build_advice_context(
        store.trades(account="user"),
        bars,
        _SECTORS,
        store_path=store.path,
        account="user",
        preset_name="balanced",
    )

    assert context.trade_count == 1
    assert len(context.positions) == 1
    assert context.cash_ratio_pct < 100.0

    text = advisor.render_local_advice(context)
    assert "投資助言ではありません" in text
    assert "1000" in text

    prompt = advisor.build_advice_prompt(context)
    assert "断定的な売買推奨は禁止" in prompt
    assert "逆指値" in prompt
    assert "テスト電力" in prompt


def test_local_advice_empty_book_mentions_split_entry(tmp_path: Path) -> None:
    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    context = advisor.build_advice_context(
        store.trades(account="user"),
        {},
        _SECTORS,
        store_path=store.path,
        account="user",
        preset_name="balanced",
    )

    assert context.positions == ()
    text = advisor.render_local_advice(context)
    assert "全額現金" in text
    assert "投資助言ではありません" in text


def test_local_advice_flags_early_sell_tendency() -> None:
    closes = [1000.0 + 10.0 * i for i in range(40)]
    bars = {"1000": _bars("1000", closes)}
    all_dates = [bar.date for bar in bars["1000"]]
    from investment_assistant.papertrade.virtual import TradeRecord

    trades = [
        TradeRecord(
            id=1,
            ts="t",
            trade_date=all_dates[10],
            ticker="1000",
            name="",
            side="sell",
            shares=100,
            price=closes[10],
            commission=0.0,
            realized_pnl=0.0,
            tax_delta=0,
            cash_after=0.0,
            account="user",
        )
    ]
    timing = advisor.build_timing_stats(trades, bars)
    context = advisor.AdviceContext(
        account="user",
        as_of=all_dates[-1],
        preset=BALANCED,
        cash=10_000_000.0,
        equity=10_000_000.0,
        cash_ratio_pct=100.0,
        total_return_pct=0.0,
        trade_count=1,
        positions=(),
        timing=timing,
    )

    text = advisor.render_local_advice(context)
    assert "早売り傾向" in text
