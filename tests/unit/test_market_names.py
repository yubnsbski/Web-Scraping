"""Watch-list name picker endpoint."""

from __future__ import annotations

from investment_assistant.webapi.market import market_names


def test_market_names_includes_builtin_majors() -> None:
    result = market_names({})
    by_ticker = {item["ticker"]: item["name"] for item in result["names"]}
    assert by_ticker["6758"] == "ソニーグループ"
    assert by_ticker["7203"] == "トヨタ自動車"
    assert result["count"] >= 80
    # sorted by ticker
    tickers = [item["ticker"] for item in result["names"]]
    assert tickers == sorted(tickers)
