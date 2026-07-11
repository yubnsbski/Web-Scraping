"""Unit tests for :mod:`investment_assistant.papertrade.autopilot`.

Every store lives under ``tmp_path``; bars/sectors are synthetic in-memory
fixtures -- never the real ``local_docs`` data (offline-first, per
``AGENTS.md``).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from investment_assistant.papertrade.autopilot import (
    BALANCED,
    DEFENSIVE,
    MOMENTUM,
    PRESETS,
    AutopilotPreset,
    catch_up,
    run_cycle,
)
from investment_assistant.papertrade.universe import Bar, SectorInfo
from investment_assistant.papertrade.virtual import OrderRequest, VirtualBroker, VirtualTradingStore


def _dates(start: str, n: int) -> list[str]:
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _flat_series(ticker: str, dates: list[str], close: float, volume: int = 100_000) -> list[Bar]:
    return [Bar(ticker, d, close, close, close, close, volume) for d in dates]


def _trend_series(
    ticker: str, dates: list[str], start: float, end: float, volume: int = 100_000
) -> list[Bar]:
    n = len(dates)
    if n == 1:
        prices = [start]
    else:
        step = (end - start) / (n - 1)
        prices = [start + step * i for i in range(n)]
    return [Bar(ticker, d, p, p, p, p, volume) for d, p in zip(dates, prices, strict=True)]


# --- presets ------------------------------------------------------------


def test_presets_registry_has_the_three_named_presets() -> None:
    assert set(PRESETS) == {"balanced", "defensive", "momentum"}
    assert PRESETS["balanced"] is BALANCED
    assert PRESETS["defensive"] is DEFENSIVE
    assert PRESETS["momentum"] is MOMENTUM

    assert BALANCED.target_positions == 8
    assert BALANCED.max_per_sector == 2
    assert BALANCED.defensive_only is False
    assert BALANCED.ranking == "momentum"

    assert DEFENSIVE.target_positions == 6
    assert DEFENSIVE.defensive_only is True
    assert DEFENSIVE.ranking == "low_vol"

    assert MOMENTUM.stop_loss_pct == -0.10
    assert MOMENTUM.take_profit_pct == 0.20


# --- run_cycle: deterministic buys, sector cap, equal-notional lots --------


def test_run_cycle_buys_ranked_candidates_respecting_sector_cap(tmp_path: Path) -> None:
    dates = _dates("2026-01-01", 60)
    d = dates[-1]

    # Momentum ranking: total return over the trailing window. Descending order:
    # 1000 (+30%) > 1001 (+20%) > 1002 (+10%) > 1003 (+5%) > 1004 (+1%).
    bars = {
        "1000": _trend_series("1000", dates, 1000.0, 1300.0),
        "1001": _trend_series("1001", dates, 1000.0, 1200.0),
        "1002": _trend_series("1002", dates, 1000.0, 1100.0),
        "1003": _trend_series("1003", dates, 1000.0, 1050.0),
        "1004": _trend_series("1004", dates, 1000.0, 1010.0),
    }
    sectors = {
        "1000": SectorInfo("1000", "Co1000", "セクターA", "プライム（内国株式）"),
        "1001": SectorInfo("1001", "Co1001", "セクターA", "プライム（内国株式）"),
        "1002": SectorInfo("1002", "Co1002", "セクターB", "プライム（内国株式）"),
        "1003": SectorInfo("1003", "Co1003", "セクターB", "プライム（内国株式）"),
        "1004": SectorInfo("1004", "Co1004", "セクターC", "プライム（内国株式）"),
    }
    preset = AutopilotPreset(
        name="test",
        target_positions=3,
        max_per_sector=1,
        defensive_only=False,
        ranking="momentum",
        stop_loss_pct=-0.5,
        take_profit_pct=0.5,
    )

    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    summary = run_cycle(store, bars, sectors, preset, d)

    # 1001 is skipped: same sector as 1000, which already ranked higher and filled the cap.
    # 1003 is skipped for the same reason relative to 1002.
    assert [fill.ticker for fill in summary.buys] == ["1000", "1002", "1004"]
    assert summary.sells == ()
    assert summary.rejected == ()

    shares_by_ticker = {fill.ticker: fill.shares for fill in summary.buys}
    # slot notional = 10,000,000 / 3 = 3,333,333.33; shares = floor(slot/close) to a 100-lot.
    assert shares_by_ticker == {"1000": 2500, "1002": 3000, "1004": 3300}
    assert all(shares % 100 == 0 for shares in shares_by_ticker.values())


def test_run_cycle_skips_zero_share_and_too_many_positions(tmp_path: Path) -> None:
    dates = _dates("2026-01-01", 60)
    d = dates[-1]
    bars = {"1000": _trend_series("1000", dates, 1000.0, 1300.0)}
    sectors = {"1000": SectorInfo("1000", "Co1000", "セクターA", "プライム（内国株式）")}
    preset = AutopilotPreset(
        name="test",
        target_positions=8,
        max_per_sector=2,
        defensive_only=False,
        ranking="momentum",
        stop_loss_pct=-0.5,
        take_profit_pct=0.5,
    )

    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    summary = run_cycle(store, bars, sectors, preset, d)

    assert [fill.ticker for fill in summary.buys] == ["1000"]


# --- run_cycle: stop-loss / take-profit / no-longer-candidate sells --------


def _seed_ai_position(
    store_path: Path, ticker: str, dates: list[str], close: float, shares: int = 100
) -> None:
    seed_bars = {ticker: _flat_series(ticker, dates, close)}
    broker = VirtualBroker(store_path, bars=seed_bars)
    report = broker.submit_order(
        OrderRequest(
            ticker=ticker, side="buy", shares=shares, account="ai", trade_date=dates[-1]
        )
    )
    assert report.ok


def test_run_cycle_sells_on_stop_loss(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"
    dates = _dates("2026-01-01", 60)
    _seed_ai_position(store_path, "3000", dates, close=1000.0)

    d1 = _dates("2026-01-01", 61)[-1]
    bars = {
        "3000": _flat_series("3000", dates, 1000.0)
        + [Bar("3000", d1, 900.0, 900.0, 900.0, 900.0, 100_000)]
    }
    sectors = {"3000": SectorInfo("3000", "Co3000", "セクターA", "プライム（内国株式）")}
    preset = AutopilotPreset(
        name="test", target_positions=1, max_per_sector=1, defensive_only=False,
        ranking="momentum", stop_loss_pct=-0.08, take_profit_pct=0.15,
    )

    store = VirtualTradingStore(store_path)
    summary = run_cycle(store, bars, sectors, preset, d1)

    assert [fill.ticker for fill in summary.sells] == ["3000"]
    assert summary.sells[0].shares == 100


def test_run_cycle_sells_on_take_profit(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"
    dates = _dates("2026-01-01", 60)
    _seed_ai_position(store_path, "3000", dates, close=1000.0)

    d1 = _dates("2026-01-01", 61)[-1]
    bars = {
        "3000": _flat_series("3000", dates, 1000.0)
        + [Bar("3000", d1, 1200.0, 1200.0, 1200.0, 1200.0, 100_000)]
    }
    sectors = {"3000": SectorInfo("3000", "Co3000", "セクターA", "プライム（内国株式）")}
    preset = AutopilotPreset(
        name="test", target_positions=1, max_per_sector=1, defensive_only=False,
        ranking="momentum", stop_loss_pct=-0.08, take_profit_pct=0.15,
    )

    store = VirtualTradingStore(store_path)
    summary = run_cycle(store, bars, sectors, preset, d1)

    assert [fill.ticker for fill in summary.sells] == ["3000"]


def test_run_cycle_never_rebuys_a_ticker_sold_this_cycle(tmp_path: Path) -> None:
    """Regression: a take-profit sell must not be immediately re-bought.

    Ticker 3000 hits take-profit at d1 but still qualifies as a (top-ranked)
    candidate there; before the ``sold_tickers`` guard the buy phase would
    round-trip it at the same close -- realizing the gain, prepaying tax, and
    re-entering for nothing but the tick spread.
    """

    store_path = tmp_path / "vt.sqlite"
    dates = _dates("2026-01-01", 60)
    _seed_ai_position(store_path, "3000", dates, close=1000.0)

    d1 = _dates("2026-01-01", 61)[-1]
    bars = {
        "3000": _flat_series("3000", dates, 1000.0)
        + [Bar("3000", d1, 1200.0, 1200.0, 1200.0, 1200.0, 100_000)]
    }
    sectors = {"3000": SectorInfo("3000", "Co3000", "セクターA", "プライム（内国株式）")}
    preset = AutopilotPreset(
        name="test", target_positions=1, max_per_sector=1, defensive_only=False,
        ranking="momentum", stop_loss_pct=-0.08, take_profit_pct=0.15,
    )

    store = VirtualTradingStore(store_path)
    summary = run_cycle(store, bars, sectors, preset, d1)

    assert [fill.ticker for fill in summary.sells] == ["3000"]
    assert summary.buys == ()
    broker = VirtualBroker(store_path, bars=bars)
    assert "3000" not in broker.account_as_of("ai", d1).positions


def test_run_cycle_sells_when_no_longer_a_candidate(tmp_path: Path) -> None:
    store_path = tmp_path / "vt.sqlite"
    dates = _dates("2026-01-01", 60)
    _seed_ai_position(store_path, "3000", dates, close=1000.0)

    d1 = _dates("2026-01-01", 61)[-1]
    # Liquidity collapses for the trailing 20-bar window -> median turnover drops below the
    # floor and the ticker is dropped from candidates, even though price barely moved (well
    # inside the stop/take band).
    history = _flat_series("3000", dates[:40], 1000.0, volume=100_000) + _flat_series(
        "3000", dates[40:], 1000.0, volume=10
    )
    bars = {"3000": history + [Bar("3000", d1, 1005.0, 1005.0, 1005.0, 1005.0, 10)]}
    sectors = {"3000": SectorInfo("3000", "Co3000", "セクターA", "プライム（内国株式）")}
    preset = AutopilotPreset(
        name="test", target_positions=1, max_per_sector=1, defensive_only=False,
        ranking="momentum", stop_loss_pct=-0.5, take_profit_pct=0.5,
    )

    store = VirtualTradingStore(store_path)
    summary = run_cycle(store, bars, sectors, preset, d1)

    assert [fill.ticker for fill in summary.sells] == ["3000"]


def test_run_cycle_defensive_only_filters_non_defensive_sectors(tmp_path: Path) -> None:
    dates = _dates("2026-01-01", 60)
    d = dates[-1]
    bars = {
        "1000": _flat_series("1000", dates, 1000.0),  # defensive sector
        "2000": _flat_series("2000", dates, 1000.0),  # non-defensive sector
    }
    sectors = {
        "1000": SectorInfo("1000", "Co1000", "食料品", "プライム（内国株式）"),
        "2000": SectorInfo("2000", "Co2000", "鉄鋼", "プライム（内国株式）"),
    }
    preset = AutopilotPreset(
        name="test", target_positions=8, max_per_sector=2, defensive_only=True,
        ranking="low_vol", stop_loss_pct=-0.5, take_profit_pct=0.5,
    )

    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    summary = run_cycle(store, bars, sectors, preset, d)

    assert [fill.ticker for fill in summary.buys] == ["1000"]


# --- catch_up -----------------------------------------------------------


def test_catch_up_first_activation_runs_only_the_latest_date(tmp_path: Path) -> None:
    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    dates = _dates("2026-01-01", 35)
    bars = {"9000": _flat_series("9000", dates, 100.0)}

    summaries = catch_up(store, bars, sectors={})

    assert [s.date for s in summaries] == [dates[-1]]
    assert store.autopilot_last_run_date() == dates[-1]


def test_catch_up_runs_missed_dates_in_order(tmp_path: Path) -> None:
    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    dates = _dates("2026-01-01", 35)
    bars = {"9000": _flat_series("9000", dates, 100.0)}
    catch_up(store, bars, sectors={})  # first activation consumes dates[-1]

    more_dates = _dates("2026-01-01", 37)
    bars2 = {"9000": _flat_series("9000", more_dates, 100.0)}
    summaries = catch_up(store, bars2, sectors={})

    assert [s.date for s in summaries] == more_dates[-2:]
    assert store.autopilot_last_run_date() == more_dates[-1]


def test_catch_up_is_noop_when_auto_is_off(tmp_path: Path) -> None:
    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    store.set_autopilot_auto(False)
    dates = _dates("2026-01-01", 35)
    bars = {"9000": _flat_series("9000", dates, 100.0)}

    summaries = catch_up(store, bars, sectors={})

    assert summaries == []
    assert store.autopilot_last_run_date() is None


def test_catch_up_force_runs_even_when_auto_is_off(tmp_path: Path) -> None:
    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    store.set_autopilot_auto(False)
    dates = _dates("2026-01-01", 35)
    bars = {"9000": _flat_series("9000", dates, 100.0)}

    summaries = catch_up(store, bars, sectors={}, force=True)

    assert [s.date for s in summaries] == [dates[-1]]
    assert store.autopilot_last_run_date() == dates[-1]


def test_catch_up_returns_empty_when_no_bars(tmp_path: Path) -> None:
    store = VirtualTradingStore(tmp_path / "vt.sqlite")
    assert catch_up(store, {}, sectors={}) == []
    assert store.autopilot_last_run_date() is None
