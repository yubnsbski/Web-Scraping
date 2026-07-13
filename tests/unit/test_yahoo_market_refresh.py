from __future__ import annotations

import json
from pathlib import Path

from investment_assistant.portfolio.yahoo_market import (
    parse_yahoo_chart,
    parse_yahoo_japan_html,
    refresh_yahoo_market,
)
from investment_assistant.webapi import available_routes
from investment_assistant.webapi import yahoo_market as yahoo_api


class _Document:
    allowed_by_robots = True
    status_code = 200
    source = "network"

    def __init__(self, html: str) -> None:
        self.html = html


class _Fetcher:
    def fetch_document(self, url: str) -> _Document:
        if "/v8/finance/chart/" in url:
            return _Document(
                json.dumps(
                    {
                        "chart": {
                            "result": [
                                {
                                    "timestamp": [1718409600],
                                    "meta": {"gmtoffset": 32400},
                                    "indicators": {
                                        "quote": [
                                            {
                                                "open": [100.0],
                                                "high": [110.0],
                                                "low": [90.0],
                                                "close": [105.0],
                                                "volume": [1234],
                                            }
                                        ],
                                        "adjclose": [{"adjclose": [104.0]}],
                                    },
                                }
                            ]
                        }
                    }
                )
            )
        if "/v7/finance/quote" in url:
            return _Document(
                json.dumps(
                    {
                        "quoteResponse": {
                            "result": [
                                {
                                    "symbol": "7203.T",
                                    "longName": "Toyota",
                                    "regularMarketPrice": 105.0,
                                    "trailingPE": 10.0,
                                    "priceToBook": 1.2,
                                    "trailingAnnualDividendYield": 0.03,
                                }
                            ]
                        }
                    }
                )
            )
        return _Document(
            "<html><title>MUFG【8306】</title>"
            "<dl><dt>PER</dt><dd>12.3倍</dd></dl>"
            "<dl><dt>PBR</dt><dd>1.1倍</dd></dl>"
            "<dl><dt>配当利回り</dt><dd>3.5%</dd></dl>"
            "<dl><dt>時価総額</dt><dd>10兆円</dd></dl>"
            "現在値1234前日比</html>"
        )


def test_parse_yahoo_chart_normalizes_daily_bar() -> None:
    payload = json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [1718409600],
                        "meta": {"gmtoffset": 32400},
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100],
                                    "high": [110],
                                    "low": [90],
                                    "close": [105],
                                    "volume": [0],
                                }
                            ],
                            "adjclose": [{"adjclose": [104]}],
                        },
                    }
                ]
            }
        }
    )

    bars = parse_yahoo_chart(payload, ticker="7203", source_ref="chart")

    assert len(bars) == 1
    assert bars[0].ticker == "7203"
    assert bars[0].date == "2024-06-15"
    assert bars[0].adjusted_close == 104.0
    assert bars[0].volume == 0.0
    assert bars[0].provider_id == "yahoo_finance"


def test_parse_yahoo_japan_html_extracts_market_metrics() -> None:
    html = (
        "<html><title>Sample【9999】</title>"
        "<dl><dt>PER</dt><dd>12.3倍</dd></dl>"
        "<dl><dt>PBR</dt><dd>1.1倍</dd></dl>"
        "<dl><dt>配当利回り</dt><dd>3.5%</dd></dl>"
        "<dl><dt>時価総額</dt><dd>10兆円</dd></dl>"
        "現在値1234前日比</html>"
    )

    row = parse_yahoo_japan_html(html, ticker="9999")

    assert row["name"] == "Sample"
    assert row["price"] == 1234.0
    assert row["per"] == 12.3
    assert row["pbr"] == 1.1
    assert row["dividend_yield"] == 0.035
    assert row["market_cap"] == 10_000_000_000_000.0


def test_refresh_yahoo_market_saves_bars_prices_and_fundamentals(tmp_path: Path) -> None:
    bars_path = tmp_path / "daily_bars.csv"
    prices_path = tmp_path / "current_prices.csv"
    fundamentals_path = tmp_path / "yahoo_financials.csv"

    result = refresh_yahoo_market(
        ["7203", "8306.T"],
        daily_bars_path=bars_path,
        current_prices_path=prices_path,
        fundamentals_path=fundamentals_path,
        fetcher=_Fetcher(),
    )

    assert result["status"] == "completed"
    assert result["ohlcv_ticker_count"] == 2
    assert result["fundamentals_ticker_count"] == 2
    assert bars_path.is_file()
    assert prices_path.is_file()
    assert fundamentals_path.is_file()
    assert "yahoo_finance" in bars_path.read_text(encoding="utf-8")
    assert "Toyota" in fundamentals_path.read_text(encoding="utf-8-sig")


def test_refresh_yahoo_market_uses_default_fetcher(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "investment_assistant.portfolio.yahoo_market.SafeFetcher",
        lambda **_kwargs: _Fetcher(),
    )

    result = refresh_yahoo_market(
        ["7203"],
        fetch_fundamentals=False,
        daily_bars_path=tmp_path / "daily_bars.csv",
        current_prices_path=tmp_path / "current_prices.csv",
    )

    assert result["status"] == "completed"
    assert result["ohlcv_ticker_count"] == 1


def test_yahoo_routes_are_registered() -> None:
    routes = available_routes()

    assert "POST /api/market/yahoo/refresh" in routes
    assert "GET /api/market/yahoo/status" in routes


def test_yahoo_custom_refresh_routes_configuration(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_refresh(tickers: object, **kwargs: object) -> dict[str, object]:
        captured["tickers"] = tickers
        captured.update(kwargs)
        return {"status": "completed", "requested_count": 2}

    monkeypatch.setattr(yahoo_api, "refresh_yahoo_market", fake_refresh)

    status, payload = yahoo_api.handle_yahoo_market_api(
        "POST",
        "/api/market/yahoo/refresh",
        {
            "mode": "custom",
            "tickers": "7203, 8306.T",
            "range": "3mo",
            "interval": "1wk",
            "fetch_ohlcv": True,
            "fetch_fundamentals": False,
            "daily_bars_path": str(tmp_path / "bars.csv"),
        },
    ) or (0, {})

    assert status == 200
    assert payload["mode"] == "custom"
    assert captured["tickers"] == ["7203", "8306"]
    assert captured["range_"] == "3mo"
    assert captured["interval"] == "1wk"
    assert captured["fetch_fundamentals"] is False


def test_yahoo_auto_refresh_resolves_market_universe(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_universe(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "securities": [{"ticker": "9432"}, {"ticker": "7203"}],
            "total_count": 225,
            "nikkei225_count": 225,
        }

    def fake_refresh(tickers: object, **kwargs: object) -> dict[str, object]:
        return {"status": "completed", "tickers": tickers, **kwargs}

    monkeypatch.setattr(yahoo_api, "build_market_universe", fake_universe)
    monkeypatch.setattr(yahoo_api, "refresh_yahoo_market", fake_refresh)

    status, payload = yahoo_api.handle_yahoo_market_api(
        "POST",
        "/api/market/yahoo/refresh",
        {"mode": "auto", "scope": "nikkei225", "max_tickers": 20},
    ) or (0, {})

    assert status == 200
    assert payload["tickers"] == ["9432", "7203"]
    assert payload["selection"]["scope"] == "nikkei225"
    assert captured["limit"] == 20


def test_yahoo_custom_refresh_rejects_empty_tickers() -> None:
    status, payload = yahoo_api.handle_yahoo_market_api(
        "POST",
        "/api/market/yahoo/refresh",
        {"mode": "custom", "tickers": []},
    ) or (0, {})

    assert status == 400
    assert "requires tickers" in str(payload["error"])
