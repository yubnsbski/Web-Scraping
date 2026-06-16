from __future__ import annotations

from pathlib import Path

from investment_assistant import cli
from investment_assistant.portfolio.price_inbox import (
    inbox_status,
    parse_price_inbox,
    read_price_inbox,
)


def test_parse_price_inbox_reads_ticker_and_close_english() -> None:
    text = "Ticker,Date,Close,Volume\n8306,2026-06-15,1500,100\n7203,2026-06-15,3000,50\n"
    assert parse_price_inbox(text) == {"8306": 1500.0, "7203": 3000.0}


def test_parse_price_inbox_japanese_headers_bom_and_latest_wins() -> None:
    text = "﻿銘柄コード,日付,終値\n8306,2026-06-12,1480\n8306,2026-06-15,1520\n"
    # Later (more recent) row overrides; BOM and Japanese headers handled.
    assert parse_price_inbox(text) == {"8306": 1520.0}


def test_parse_price_inbox_skips_bad_rows_and_unknown_headers() -> None:
    assert parse_price_inbox("foo,bar\n1,2\n") == {}  # no ticker/price columns
    text = "symbol,price\n,100\n9999,abc\n8306,2500\n"
    assert parse_price_inbox(text) == {"8306": 2500.0}


def test_inbox_status_missing_then_present(tmp_path: Path) -> None:
    path = tmp_path / "yahoo_prices_inbox.csv"
    missing = inbox_status(path)
    assert missing["status"] == "missing" and missing["tickers"] == 0

    path.write_text("symbol,close\n8306,1500\n", encoding="utf-8")
    present = inbox_status(path)
    assert present["status"] == "present"
    assert present["tickers"] == 1
    assert present["prices"] == {"8306": 1500.0}


def test_read_price_inbox_missing_returns_empty(tmp_path: Path) -> None:
    assert read_price_inbox(tmp_path / "nope.csv") == {}


def test_market_inbox_cli_reports_status(tmp_path: Path) -> None:
    path = tmp_path / "inbox.csv"
    assert cli.run_market_inbox(path=path)["status"] == "missing"
    path.write_text("ticker,close\n7203,3000\n", encoding="utf-8")
    result = cli.run_market_inbox(path=path)
    assert result["status"] == "present" and result["prices"] == {"7203": 3000.0}


def test_market_inbox_api_route(tmp_path: Path) -> None:
    from investment_assistant.webapi.service import handle_api

    path = tmp_path / "inbox.csv"
    path.write_text("symbol,close\n8306,1500\n", encoding="utf-8")
    status, payload = handle_api("POST", "/api/market/inbox", {"path": str(path)})
    assert status == 200
    assert payload["status"] == "present"
    assert payload["prices"] == {"8306": 1500.0}
