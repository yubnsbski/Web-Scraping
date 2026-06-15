from __future__ import annotations

import json

import pytest

from investment_assistant.portfolio.prices import (
    PRICE_PROVIDER_ENV,
    fetch_prices,
    parse_yahoo_close,
)


def _yahoo_payload(*, regular: float | None, closes: list[float | None]) -> str:
    meta: dict[str, object] = {}
    if regular is not None:
        meta["regularMarketPrice"] = regular
    return json.dumps(
        {"chart": {"result": [{"meta": meta, "indicators": {"quote": [{"close": closes}]}}],
                   "error": None}}
    )


def test_parse_yahoo_close_prefers_regular_market_price() -> None:
    assert parse_yahoo_close(_yahoo_payload(regular=1234.5, closes=[1, 2, 3])) == 1234.5


def test_parse_yahoo_close_falls_back_to_last_non_null_close() -> None:
    assert parse_yahoo_close(_yahoo_payload(regular=None, closes=[100.0, 200.0, None])) == 200.0


def test_parse_yahoo_close_rejects_malformed_or_nonpositive() -> None:
    assert parse_yahoo_close("not json") is None
    assert parse_yahoo_close(json.dumps({"chart": {"result": []}})) is None
    assert parse_yahoo_close(_yahoo_payload(regular=0.0, closes=[0.0, None])) is None


def test_fetch_prices_yfinance_uses_yahoo_url_and_parser() -> None:
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        return _yahoo_payload(regular=3010.0, closes=[3000.0])

    result = fetch_prices(["8306"], provider_id="yfinance", fetch=fake_fetch)

    assert result["provider_id"] == "yfinance"
    assert result["prices"] == {"8306": 3010.0}
    # Routed to the Yahoo chart endpoint with a Tokyo (.T) symbol.
    assert seen == ["https://query1.finance.yahoo.com/v8/finance/chart/8306.T?range=5d&interval=1d"]


def test_fetch_prices_defaults_to_stooq_csv() -> None:
    def fake_fetch(url: str) -> str:
        assert "stooq.com" in url
        return (
            "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "8306.JP,2026-06-15,15:00,1,2,0.5,1500,10\n"
        )

    result = fetch_prices(["8306"], fetch=fake_fetch)

    assert result["provider_id"] == "stooq_public_csv"
    assert result["prices"] == {"8306": 1500.0}


def test_fetch_prices_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PRICE_PROVIDER_ENV, "yahoo")

    def fake_fetch(url: str) -> str:
        assert "finance.yahoo.com" in url
        return _yahoo_payload(regular=42.0, closes=[42.0])

    result = fetch_prices(["7203"], fetch=fake_fetch)

    assert result["provider_id"] == "yfinance"
    assert result["prices"] == {"7203": 42.0}
