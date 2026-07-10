"""Unit tests for :mod:`investment_assistant.papertrade.store` (SQLite roundtrip).

All tests use ``tmp_path`` -- never the default ``data/runtime`` location.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.papertrade.store import PaperTradeStore


def _store(tmp_path: Path) -> PaperTradeStore:
    return PaperTradeStore(tmp_path / "papertrade.sqlite")


def test_create_tables_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_tables()  # should not raise on an existing schema
    store.create_tables()


def test_run_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.insert_run(
        run_id="run-a",
        kind="adaptive",
        strategy="yield",
        params={"n_positions": 10},
        started_at="2026-07-10T00:00:00Z",
        config={"initial_cash": 5_000_000},
    )
    run = store.get_run("run-a")
    assert run is not None
    assert run["kind"] == "adaptive"
    assert run["strategy"] == "yield"
    assert run["params"] == {"n_positions": 10}
    assert run["config"] == {"initial_cash": 5_000_000}
    assert store.get_run("missing") is None


def test_run_upsert_overwrites(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.insert_run(
        run_id="run-a", kind="adaptive", strategy="yield", params={},
        started_at="t0", config={},
    )
    store.insert_run(
        run_id="run-a", kind="control", strategy="momentum", params={"x": 1},
        started_at="t1", config={"y": 2},
    )
    run = store.get_run("run-a")
    assert run is not None
    assert run["kind"] == "control"
    assert run["strategy"] == "momentum"


def test_cycle_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.insert_cycle(
        run_id="run-a", cycle_index=0, decision_date="2026-01-05",
        start_date="2026-01-06", end_date="2026-01-12",
        policy={"n_positions": 10, "sector_cap": 0.3},
    )
    store.insert_cycle(
        run_id="run-a", cycle_index=1, decision_date="2026-01-12",
        start_date="2026-01-13", end_date="2026-01-19",
        policy={"n_positions": 12, "sector_cap": 0.3},
    )
    cycles = store.list_cycles("run-a")
    assert len(cycles) == 2
    assert cycles[0]["cycle_index"] == 0
    assert cycles[0]["policy"]["n_positions"] == 10
    assert cycles[1]["decision_date"] == "2026-01-12"


def test_order_and_fill_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    order_id = store.insert_order(
        run_id="run-a", cycle_index=0, ticker="1000", side="buy", shares=100,
        decision_date="2026-01-05",
    )
    assert order_id > 0

    fill_id = store.insert_fill(
        run_id="run-a", cycle_index=0, order_id=order_id, ticker="1000", side="buy",
        date="2026-01-06", price=1010.0, shares=100, commission=0.0, clamped=False,
        settlement_date="2026-01-08",
    )
    assert fill_id > 0

    orders = store.list_orders("run-a")
    assert len(orders) == 1
    assert orders[0]["ticker"] == "1000"

    fills = store.list_fills("run-a", cycle_index=0)
    assert len(fills) == 1
    assert fills[0]["price"] == 1010.0
    assert fills[0]["clamped"] is False

    assert store.list_orders("run-a", cycle_index=99) == []


def test_positions_eod_roundtrip_and_upsert(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.insert_positions_eod(
        run_id="run-a", date="2026-01-06", ticker="1000", shares=100, close=1010.0,
        value=101_000.0,
    )
    store.insert_positions_eod(
        run_id="run-a", date="2026-01-06", ticker="1000", shares=100, close=1020.0,
        value=102_000.0,
    )
    rows = store.list_positions_eod("run-a", date="2026-01-06")
    assert len(rows) == 1  # upserted, not duplicated
    assert rows[0]["close"] == 1020.0


def test_cycle_metrics_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.insert_cycle_metrics(
        run_id="run-a", cycle_index=0,
        metrics={"period_return": 0.02, "sharpe": 1.1},
    )
    metrics = store.list_cycle_metrics("run-a")
    assert len(metrics) == 1
    assert metrics[0]["metrics"]["period_return"] == 0.02


def test_memo_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memo_id = store.insert_memo(
        run_id="run-a", cycle_index=0, path="local_docs/papertrade/run-a/memo_cycle_00.md",
        body="サイクル0の実績メモ",
    )
    assert memo_id > 0
    memos = store.list_memos("run-a")
    assert len(memos) == 1
    assert memos[0]["body"] == "サイクル0の実績メモ"


def test_policy_history_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.insert_policy_history(
        run_id="run-a", cycle_index=1,
        old={"n_positions": 10}, new={"n_positions": 12},
        reason="過去2サイクルの超過リターンが低いため銘柄数を増やす",
    )
    history = store.list_policy_history("run-a")
    assert len(history) == 1
    assert history[0]["old"] == {"n_positions": 10}
    assert history[0]["new"] == {"n_positions": 12}


def test_store_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "papertrade.sqlite"
    store1 = PaperTradeStore(path)
    store1.insert_run(
        run_id="run-a", kind="adaptive", strategy="yield", params={}, started_at="t0",
        config={},
    )
    store2 = PaperTradeStore(path)  # re-open the same file
    run = store2.get_run("run-a")
    assert run is not None
    assert run["kind"] == "adaptive"
