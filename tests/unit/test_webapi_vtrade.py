"""Unit tests for the ``/api/vtrade/*`` webapi handlers.

Uses small synthetic CSV fixtures written to ``tmp_path`` and
:func:`investment_assistant.webapi.virtual_trade.configure` to point the
module at them -- never the real ``local_docs`` data (offline-first, per
``AGENTS.md``).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

from investment_assistant.webapi import virtual_trade as vtrade_api
from investment_assistant.webapi.service import available_routes, handle_api

_BARS_HEADER = "ticker,date,open,high,low,close,volume\n"
_JPX_HEADER = (
    "日付,コード,銘柄名,市場・商品区分,33業種コード,33業種区分,17業種コード,17業種区分,規模コード,規模区分\n"
)

_DEFAULT_BARS = (
    "1000,2026-01-05,1000,1000,1000,1000,1000\n"
    "1000,2026-01-06,1005,1005,1005,1005,1000\n"
)
_DEFAULT_JPX = "20260531,1000,テスト電力,プライム（内国株式）,50,電気・ガス業,1,X,6,Y\n"


def _rich_bars_csv(ticker: str, n: int, start_price: float, end_price: float) -> str:
    """A qualifying autopilot candidate: >=30 bars, strong liquidity, positive momentum."""

    start = date(2026, 1, 1)
    step = (end_price - start_price) / (n - 1) if n > 1 else 0.0
    lines = []
    for i in range(n):
        price = start_price + step * i
        d = (start + timedelta(days=i)).isoformat()
        lines.append(f"{ticker},{d},{price},{price},{price},{price},200000\n")
    return "".join(lines)


_RICH_BARS = _rich_bars_csv("1000", 40, 1000.0, 1200.0)
_RICH_JPX = _DEFAULT_JPX


@pytest.fixture(autouse=True)
def _reset_vtrade_data_source() -> Iterator[None]:
    yield
    vtrade_api.reset_data_source()


def _configure(tmp_path: Path, *, bars_rows: str, jpx_rows: str) -> None:
    bars_path = tmp_path / "daily_bars.csv"
    bars_path.write_text(_BARS_HEADER + bars_rows, encoding="utf-8")
    jpx_path = tmp_path / "jpx.csv"
    jpx_path.write_text(_JPX_HEADER + jpx_rows, encoding="utf-8")
    store_path = tmp_path / "vtrade.sqlite"
    vtrade_api.configure(
        daily_bars_path=bars_path, jpx_master_path=jpx_path, store_path=store_path
    )


# --- route registration -----------------------------------------------------


def test_all_vtrade_routes_are_registered() -> None:
    routes = available_routes()
    expected = [
        "POST /api/vtrade/quote",
        "GET /api/vtrade/portfolio",
        "POST /api/vtrade/order",
        "GET /api/vtrade/history",
        "GET /api/vtrade/performance",
        "POST /api/vtrade/reset",
        "POST /api/vtrade/bars",
        "GET /api/vtrade/ai/portfolio",
        "GET /api/vtrade/ai/performance",
        "POST /api/vtrade/autopilot/run",
        "POST /api/vtrade/autopilot/config",
    ]
    for route in expected:
        assert route in routes


# --- quote -------------------------------------------------------------


def test_quote_happy_path(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, payload = handle_api("POST", "/api/vtrade/quote", {"ticker": "1000"})

    assert status == 200
    assert payload["ok"] is True
    assert payload["ticker"] == "1000"
    assert payload["name"] == "テスト電力"
    assert payload["sector"] == "電気・ガス業"
    assert payload["price"] == 1005.0
    assert payload["date"] == "2026-01-06"
    assert payload["lot"] == 100
    assert payload["min_cost"] == pytest.approx(1005.0 * 100)  # tick=1 below 3000


def test_quote_unknown_ticker_rejection_shape(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, payload = handle_api("POST", "/api/vtrade/quote", {"ticker": "9999"})

    assert status == 200
    assert payload == {
        "ok": False,
        "reason": "unknown_ticker",
        "message": "銘柄コードが見つかりません（データ未収録の可能性があります）",
    }


def test_quote_missing_ticker_is_api_error(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, payload = handle_api("POST", "/api/vtrade/quote", {})

    assert status == 400
    assert "error" in payload


# --- portfolio / order ---------------------------------------------------


def test_portfolio_empty_state(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, payload = handle_api("GET", "/api/vtrade/portfolio", {})

    assert status == 200
    assert payload["positions"] == []
    assert payload["trade_count"] == 0
    assert payload["cash"] == payload["initial_cash"]
    assert payload["disclaimer"]


def test_order_buy_then_portfolio_reflects_the_position(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, payload = handle_api(
        "POST", "/api/vtrade/order", {"ticker": "1000", "side": "buy", "shares": 100}
    )

    assert status == 200
    assert payload["ok"] is True
    fill = payload["fill"]
    assert fill["ticker"] == "1000"
    assert fill["name"] == "テスト電力"
    assert fill["side"] == "buy"
    assert fill["shares"] == 100
    assert fill["price"] == 1005.0
    assert payload["cash"] == pytest.approx(10_000_000.0 - 100_500.0)

    status2, portfolio = handle_api("GET", "/api/vtrade/portfolio", {})
    assert status2 == 200
    assert len(portfolio["positions"]) == 1
    position = portfolio["positions"][0]
    assert position["ticker"] == "1000"
    assert position["name"] == "テスト電力"
    assert position["sector"] == "電気・ガス業"
    assert position["shares"] == 100


def test_order_invalid_lot_rejection_shape(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, payload = handle_api(
        "POST", "/api/vtrade/order", {"ticker": "1000", "side": "buy", "shares": 150}
    )

    assert status == 200
    assert payload == {
        "ok": False,
        "reason": "invalid_lot",
        "message": "株数は100株（単元）の倍数で入力してください",
    }


def test_order_oversell_rejection_shape(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, payload = handle_api(
        "POST", "/api/vtrade/order", {"ticker": "1000", "side": "sell", "shares": 100}
    )

    assert status == 200
    assert payload == {
        "ok": False,
        "reason": "oversell",
        "message": "保有株数を超える売り注文はできません",
    }


def test_order_malformed_side_is_api_error(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, _payload = handle_api(
        "POST", "/api/vtrade/order", {"ticker": "1000", "side": "hold", "shares": 100}
    )

    assert status == 400


def test_order_malformed_shares_is_api_error(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, _payload = handle_api(
        "POST", "/api/vtrade/order", {"ticker": "1000", "side": "buy", "shares": "lots"}
    )

    assert status == 400


def test_order_missing_ticker_is_api_error(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, _payload = handle_api("POST", "/api/vtrade/order", {"side": "buy", "shares": 100})

    assert status == 400


# --- history / performance / reset -----------------------------------------


def test_history_merges_both_accounts_newest_first(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_RICH_BARS, jpx_rows=_RICH_JPX)
    handle_api("POST", "/api/vtrade/order", {"ticker": "1000", "side": "buy", "shares": 100})
    handle_api("POST", "/api/vtrade/autopilot/run", {})  # ai buys "1000" too

    status, payload = handle_api("GET", "/api/vtrade/history", {})

    assert status == 200
    assert payload["count"] == 2
    assert payload["count"] == len(payload["trades"])
    assert {trade["account"] for trade in payload["trades"]} == {"user", "ai"}
    assert payload["trades"][0]["id"] > payload["trades"][1]["id"]  # newest first


def test_performance_after_a_trade(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)
    handle_api("POST", "/api/vtrade/order", {"ticker": "1000", "side": "buy", "shares": 100})

    status, payload = handle_api("GET", "/api/vtrade/performance", {})

    assert status == 200
    assert payload["curve"]
    assert payload["as_of"] == "2026-01-06"
    assert payload["disclaimer"]


def test_reset_requires_confirm(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, _payload = handle_api("POST", "/api/vtrade/reset", {})

    assert status == 400


def test_reset_wipes_trades_and_returns_initial_cash(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)
    handle_api("POST", "/api/vtrade/order", {"ticker": "1000", "side": "buy", "shares": 100})

    status, payload = handle_api(
        "POST", "/api/vtrade/reset", {"confirm": True, "initial_cash": 3_000_000}
    )

    assert status == 200
    assert payload == {"ok": True, "initial_cash": 3_000_000.0}

    status2, portfolio = handle_api("GET", "/api/vtrade/portfolio", {})
    assert status2 == 200
    assert portfolio["cash"] == pytest.approx(3_000_000.0)
    assert portfolio["positions"] == []


# --- bars --------------------------------------------------------------


def test_bars_returns_series_and_missing(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, payload = handle_api(
        "POST", "/api/vtrade/bars", {"tickers": ["1000", "9999"], "days": 30}
    )

    assert status == 200
    assert payload["missing"] == ["9999"]
    assert payload["as_of"] == "2026-01-06"
    assert len(payload["series"]) == 1
    series = payload["series"][0]
    assert series["ticker"] == "1000"
    assert series["name"] == "テスト電力"
    assert len(series["bars"]) == 2
    assert series["last_close"] == 1005.0
    assert series["prev_close"] == 1000.0
    assert series["day_change_pct"] == pytest.approx(0.5)
    assert series["period_change_pct"] == pytest.approx(0.5)


def test_bars_caps_ticker_count_to_24(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)
    many_tickers = [f"T{i:03d}" for i in range(30)]

    status, payload = handle_api("POST", "/api/vtrade/bars", {"tickers": many_tickers})

    assert status == 200
    assert len(payload["series"]) + len(payload["missing"]) == 24


def test_bars_requires_a_non_empty_ticker_list(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_DEFAULT_BARS, jpx_rows=_DEFAULT_JPX)

    status, _payload = handle_api("POST", "/api/vtrade/bars", {"tickers": []})

    assert status == 400


# --- AI account / autopilot ------------------------------------------------


def test_ai_portfolio_lazily_ticks_autopilot(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_RICH_BARS, jpx_rows=_RICH_JPX)

    status, payload = handle_api("GET", "/api/vtrade/ai/portfolio", {})

    assert status == 200
    assert payload["preset"] == "balanced"
    assert payload["auto"] is True
    assert payload["last_run_date"] is not None
    assert payload["disclaimer"]
    assert len(payload["positions"]) == 1
    assert payload["positions"][0]["ticker"] == "1000"


def test_ai_performance_after_lazy_tick(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_RICH_BARS, jpx_rows=_RICH_JPX)
    handle_api("GET", "/api/vtrade/ai/portfolio", {})  # triggers the tick

    status, payload = handle_api("GET", "/api/vtrade/ai/performance", {})

    assert status == 200
    assert payload["curve"]
    assert payload["disclaimer"]


def test_autopilot_run_forces_a_cycle_and_reports_it(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_RICH_BARS, jpx_rows=_RICH_JPX)

    status, payload = handle_api("POST", "/api/vtrade/autopilot/run", {})

    assert status == 200
    assert payload["ok"] is True
    assert len(payload["ran"]) == 1
    assert payload["ran"][0]["buys"] == 1
    assert payload["ran"][0]["sells"] == 0
    assert payload["last_run_date"] == payload["ran"][0]["date"]


def test_autopilot_config_updates_preset_and_auto(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_RICH_BARS, jpx_rows=_RICH_JPX)

    status, payload = handle_api(
        "POST", "/api/vtrade/autopilot/config", {"preset": "momentum", "auto": False}
    )

    assert status == 200
    assert payload == {"ok": True, "preset": "momentum", "auto": False}

    status2, payload2 = handle_api("GET", "/api/vtrade/ai/portfolio", {})
    assert status2 == 200
    assert payload2["preset"] == "momentum"
    assert payload2["auto"] is False
    assert payload2["last_run_date"] is None  # auto off -> lazy tick is a no-op
    assert payload2["positions"] == []


def test_autopilot_config_rejects_unknown_preset(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_RICH_BARS, jpx_rows=_RICH_JPX)

    status, _payload = handle_api(
        "POST", "/api/vtrade/autopilot/config", {"preset": "aggressive"}
    )

    assert status == 400


def test_autopilot_config_rejects_non_bool_auto(tmp_path: Path) -> None:
    _configure(tmp_path, bars_rows=_RICH_BARS, jpx_rows=_RICH_JPX)

    status, _payload = handle_api("POST", "/api/vtrade/autopilot/config", {"auto": "yes"})

    assert status == 400
