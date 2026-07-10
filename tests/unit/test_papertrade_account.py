"""Unit tests for :mod:`investment_assistant.papertrade.account`."""

from __future__ import annotations

import pytest

from investment_assistant.papertrade.account import Account, Order
from investment_assistant.papertrade.calendar import TradingCalendar
from investment_assistant.papertrade.mechanics import CommissionModel, TaxLedger

DATES = [f"2026-01-{d:02d}" for d in range(1, 20)]


def _calendar() -> TradingCalendar:
    return TradingCalendar(DATES)


def test_execute_buy_happy_path_moves_cash_and_opens_position() -> None:
    account = Account(cash=1_000_000.0)
    order = Order(ticker="1000", side="buy", shares=100, decision_date="2026-01-04")
    result = account.execute_buy(
        order, price=1000.0, date="2026-01-05", calendar=_calendar(),
        commission_model=CommissionModel.zero(),
    )

    assert result.ok is True
    assert result.fill is not None
    assert result.fill.price == 1000.0
    assert result.fill.commission == 0.0
    assert result.fill.settlement_date == "2026-01-07"  # T+2
    assert account.cash == pytest.approx(1_000_000.0 - 100_000.0)
    assert account.positions["1000"].shares == 100
    assert account.positions["1000"].avg_cost == pytest.approx(1000.0)


def test_execute_buy_moving_average_cost() -> None:
    account = Account(cash=10_000_000.0)
    model = CommissionModel.zero()
    calendar = _calendar()

    account.execute_buy(
        Order("1000", "buy", 100, "2026-01-04"), price=1000.0, date="2026-01-05",
        calendar=calendar, commission_model=model,
    )
    account.execute_buy(
        Order("1000", "buy", 200, "2026-01-06"), price=1300.0, date="2026-01-07",
        calendar=calendar, commission_model=model,
    )

    # avg cost = (100*1000 + 200*1300) / 300 = (100000 + 260000) / 300 = 1200.0 exactly
    position = account.positions["1000"]
    assert position.shares == 300
    assert position.avg_cost == pytest.approx(1200.0)


def test_execute_buy_rejects_insufficient_cash() -> None:
    account = Account(cash=1_000.0)
    order = Order("1000", "buy", 100, "2026-01-04")
    result = account.execute_buy(
        order, price=1000.0, date="2026-01-05", calendar=_calendar(),
        commission_model=CommissionModel.zero(),
    )
    assert result.ok is False
    assert result.fill is None
    assert result.reason == "insufficient_cash"
    assert account.cash == 1_000.0  # unchanged
    assert "1000" not in account.positions


def test_execute_buy_rejects_odd_lot() -> None:
    account = Account(cash=10_000_000.0)
    order = Order("1000", "buy", 150, "2026-01-04")
    with pytest.raises(ValueError):
        account.execute_buy(
            order, price=1000.0, date="2026-01-05", calendar=_calendar(),
            commission_model=CommissionModel.zero(),
        )


def test_execute_buy_rejects_wrong_side() -> None:
    account = Account(cash=10_000_000.0)
    order = Order("1000", "sell", 100, "2026-01-04")
    with pytest.raises(ValueError):
        account.execute_buy(
            order, price=1000.0, date="2026-01-05", calendar=_calendar(),
            commission_model=CommissionModel.zero(),
        )


def test_execute_sell_happy_path_realizes_pnl() -> None:
    account = Account(cash=1_000_000.0)
    model = CommissionModel.zero()
    calendar = _calendar()
    account.execute_buy(
        Order("1000", "buy", 100, "2026-01-04"), price=1000.0, date="2026-01-05",
        calendar=calendar, commission_model=model,
    )
    cash_after_buy = account.cash

    result = account.execute_sell(
        Order("1000", "sell", 100, "2026-01-06"), price=1200.0, date="2026-01-07",
        calendar=calendar, commission_model=model,
    )

    assert result.ok is True
    assert result.fill is not None
    assert result.fill.settlement_date == "2026-01-09"  # T+2 from 2026-01-07
    # pnl = (1200-1000)*100 - 0 commission = 20,000; tax withheld = round(20000*0.20315)=4063
    assert account.realized_pnl == pytest.approx(20_000.0)
    expected_tax = account.tax_ledger.cumulative_tax_withheld
    assert expected_tax == 4063
    assert account.cash == pytest.approx(cash_after_buy + 120_000.0 - expected_tax)
    assert "1000" not in account.positions  # fully closed


def test_execute_sell_settlement_overrun_leaves_account_unchanged() -> None:
    account = Account(cash=1_000_000.0)
    model = CommissionModel.zero()
    calendar = TradingCalendar(["2026-01-05", "2026-01-06", "2026-01-07"])
    account.execute_buy(
        Order("1000", "buy", 100, "2026-01-04"), price=1000.0, date="2026-01-05",
        calendar=calendar, commission_model=model,
    )
    cash_before = account.cash
    positions_before = dict(account.positions)
    pnl_before = account.tax_ledger.cumulative_pnl
    tax_before = account.tax_ledger.cumulative_tax_withheld

    with pytest.raises(ValueError, match="settlement date"):
        account.execute_sell(
            Order("1000", "sell", 100, "2026-01-06"), price=1200.0, date="2026-01-06",
            calendar=calendar, commission_model=model,
        )

    assert account.tax_ledger.cumulative_pnl == pnl_before
    assert account.tax_ledger.cumulative_tax_withheld == tax_before
    assert account.cash == cash_before
    assert account.positions == positions_before


def test_execute_sell_partial_keeps_remaining_position_at_same_avg_cost() -> None:
    account = Account(cash=1_000_000.0)
    model = CommissionModel.zero()
    calendar = _calendar()
    account.execute_buy(
        Order("1000", "buy", 200, "2026-01-04"), price=1000.0, date="2026-01-05",
        calendar=calendar, commission_model=model,
    )
    account.execute_sell(
        Order("1000", "sell", 100, "2026-01-06"), price=1100.0, date="2026-01-07",
        calendar=calendar, commission_model=model,
    )
    remaining = account.positions["1000"]
    assert remaining.shares == 100
    assert remaining.avg_cost == pytest.approx(1000.0)  # avg cost unaffected by a sell


def test_execute_sell_rejects_oversell() -> None:
    account = Account(cash=1_000_000.0)
    model = CommissionModel.zero()
    calendar = _calendar()
    account.execute_buy(
        Order("1000", "buy", 100, "2026-01-04"), price=1000.0, date="2026-01-05",
        calendar=calendar, commission_model=model,
    )
    result = account.execute_sell(
        Order("1000", "sell", 200, "2026-01-06"), price=1000.0, date="2026-01-07",
        calendar=calendar, commission_model=model,
    )
    assert result.ok is False
    assert result.reason == "oversell"
    assert account.positions["1000"].shares == 100  # unchanged


def test_execute_sell_rejects_when_no_position_held() -> None:
    account = Account(cash=1_000_000.0)
    result = account.execute_sell(
        Order("9999", "sell", 100, "2026-01-06"), price=1000.0, date="2026-01-07",
        calendar=_calendar(), commission_model=CommissionModel.zero(),
    )
    assert result.ok is False
    assert result.reason == "oversell"


def test_execute_sell_rejects_odd_lot() -> None:
    account = Account(cash=1_000_000.0)
    with pytest.raises(ValueError):
        account.execute_sell(
            Order("1000", "sell", 30, "2026-01-06"), price=1000.0, date="2026-01-07",
            calendar=_calendar(), commission_model=CommissionModel.zero(),
        )


def test_no_shorting_enforced() -> None:
    """Selling anything without a large enough existing position is always rejected."""

    account = Account(cash=1_000_000.0)
    result = account.execute_sell(
        Order("1000", "sell", 100, "2026-01-06"), price=1000.0, date="2026-01-07",
        calendar=_calendar(), commission_model=CommissionModel.zero(),
    )
    assert result.ok is False
    assert account.cash == 1_000_000.0


def test_equity_marks_positions_and_falls_back_to_avg_cost() -> None:
    account = Account(cash=500_000.0)
    account.execute_buy(
        Order("1000", "buy", 100, "2026-01-04"), price=1000.0, date="2026-01-05",
        calendar=_calendar(), commission_model=CommissionModel.zero(),
    )
    equity_marked = account.equity({"1000": 1200.0})
    assert equity_marked == pytest.approx(account.cash + 100 * 1200.0)

    equity_unpriced = account.equity({})
    assert equity_unpriced == pytest.approx(account.cash + 100 * 1000.0)  # falls back to avg_cost


def test_missing_prices_reports_held_tickers_absent_from_mapping() -> None:
    account = Account(cash=1_000_000.0)
    calendar = _calendar()
    model = CommissionModel.zero()
    account.execute_buy(
        Order("1000", "buy", 100, "2026-01-04"), price=1000.0, date="2026-01-05",
        calendar=calendar, commission_model=model,
    )
    account.execute_buy(
        Order("2000", "buy", 100, "2026-01-04"), price=2000.0, date="2026-01-05",
        calendar=calendar, commission_model=model,
    )

    assert account.missing_prices({"1000": 1100.0, "9999": 1.0}) == ("2000",)
    assert account.missing_prices({"1000": 1100.0, "2000": 2100.0}) == ()


def test_snapshot_is_plain_dict() -> None:
    account = Account(cash=500_000.0, tax_ledger=TaxLedger())
    account.execute_buy(
        Order("1000", "buy", 100, "2026-01-04"), price=1000.0, date="2026-01-05",
        calendar=_calendar(), commission_model=CommissionModel.zero(),
    )
    snapshot = account.snapshot()
    assert snapshot["cash"] == account.cash
    assert snapshot["positions"]["1000"] == {"shares": 100, "avg_cost": 1000.0}
    assert snapshot["realized_pnl"] == 0.0
    assert snapshot["tax_ledger"]["nisa"] is False
