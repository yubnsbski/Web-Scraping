from __future__ import annotations

import json

from investment_assistant import cli
from investment_assistant.portfolio.yahoo_financials import (
    fetch_yahoo_financials,
    parse_yahoo_quote,
)


def _quote(*results: dict[str, object]) -> str:
    return json.dumps({"quoteResponse": {"result": list(results), "error": None}})


def _row(symbol: str, **fields: object) -> dict[str, object]:
    return {"symbol": symbol, **fields}


def test_parse_yahoo_quote_maps_metrics_and_strips_suffix() -> None:
    text = _quote(
        _row(
            "8306.T", shortName="MUFG", regularMarketPrice=1825.0, trailingPE=11.2,
            priceToBook=0.85, trailingAnnualDividendRate=50.0,
            trailingAnnualDividendYield=0.027, epsTrailingTwelveMonths=162.0,
            marketCap=2.2e13,
        )
    )
    parsed = parse_yahoo_quote(text)
    assert set(parsed) == {"8306"}
    m = parsed["8306"]
    assert m["name"] == "MUFG"
    assert m["price"] == 1825.0 and m["per"] == 11.2 and m["pbr"] == 0.85
    assert m["dps"] == 50.0 and m["dividend_yield"] == 0.027
    assert m["eps"] == 162.0 and m["market_cap"] == 2.2e13


def test_parse_yahoo_quote_skips_missing_fields_and_bad_payloads() -> None:
    parsed = parse_yahoo_quote(_quote(_row("7203.T", regularMarketPrice=3000.0)))
    assert parsed == {"7203": {"price": 3000.0}}  # only present fields included
    assert parse_yahoo_quote("not json") == {}
    assert parse_yahoo_quote(json.dumps({"quoteResponse": {"result": None}})) == {}


def test_fetch_yahoo_financials_batches_symbols_in_one_request() -> None:
    seen: list[str] = []

    def fetch(url: str) -> str:
        seen.append(url)
        return _quote(
            _row("8306.T", regularMarketPrice=1825.0, trailingPE=11.2),
            _row("7203.T", regularMarketPrice=3000.0, trailingPE=10.0),
        )

    result = fetch_yahoo_financials(["8306", "7203"], fetch=fetch)

    assert result["provider_id"] == "yfinance"
    assert set(result["financials"]) == {"8306", "7203"}  # type: ignore[arg-type]
    # Both symbols fetched in a single batched v7 quote request.
    assert len(seen) == 1
    assert "symbols=8306.T,7203.T" in seen[0]


def test_fetch_yahoo_financials_marks_missing_tickers() -> None:
    result = fetch_yahoo_financials(
        ["8306", "9999"], fetch=lambda u: _quote(_row("8306.T", regularMarketPrice=1.0))
    )
    assert "8306" in result["financials"]  # type: ignore[operator]
    assert result["notes"] == {"9999": "not_found"}


def test_market_financials_cli_and_api(tmp_path) -> None:
    from investment_assistant.webapi.service import handle_api

    payload = _quote(_row("8306.T", regularMarketPrice=1825.0, trailingPE=11.2))

    # CLI runner (stubbed fetch).
    cli_result = cli.run_market_financials(tickers=["8306"], fetch=lambda u: payload)
    assert cli_result["financials"]["8306"]["per"] == 11.2  # type: ignore[index]

    # API validates empty tickers.
    status, body = handle_api("POST", "/api/market/financials", {"tickers": []})
    assert status == 400 and "non-empty" in body["error"]
