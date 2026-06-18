"""Unit coverage for the one-shot market daily refresh orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from investment_assistant.cli_market import run_market_daily_refresh
from investment_assistant.portfolio._market_common import DEFAULT_YAHOO_RATE_LIMIT_POLICY


def _chart_payload(base: float) -> str:
    closes = [base + i for i in range(15)]
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [1_700_000_000 + i * 86400 for i in range(15)],
                        "indicators": {
                            "quote": [
                                {
                                    "open": closes,
                                    "high": closes,
                                    "low": closes,
                                    "close": closes,
                                    "volume": [100] * 15,
                                }
                            ]
                        },
                        "meta": {"gmtoffset": 32400},
                    }
                ]
            }
        }
    )


def _quote_payload(symbols: list[str]) -> str:
    results = [
        {
            "symbol": s,
            "longName": f"Company {s}",
            "regularMarketPrice": 1000.0,
            "trailingPE": 12.0,
            "priceToBook": 1.0,
            "trailingAnnualDividendRate": 30.0,
            "trailingAnnualDividendYield": 0.03,
            "epsTrailingTwelveMonths": 80.0,
            "marketCap": 1_000_000_000,
        }
        for s in symbols
    ]
    return json.dumps({"quoteResponse": {"result": results}})


def _fake_fetch(url: str) -> str:
    if "/v8/finance/chart/" in url:
        return _chart_payload(2000.0)
    if "/v7/finance/quote" in url:
        # Echo back the requested symbols so both batch tickers are matched.
        symbols = url.split("symbols=", 1)[1].split(",") if "symbols=" in url else []
        return _quote_payload([s.strip() for s in symbols if s.strip()])
    return ""


def test_daily_refresh_writes_bars_financials_and_builds_rag(tmp_path: Path) -> None:
    result = run_market_daily_refresh(
        tickers=["7203", "8306"],
        range_="1mo",
        daily_bars_path=tmp_path / "daily_bars.csv",
        financials_path=tmp_path / "yahoo_financials.csv",
        rag_dir=tmp_path / "rag",
        rag_db_path=tmp_path / "rag.sqlite",
        fetch=_fake_fetch,
        rate_limit_policy=DEFAULT_YAHOO_RATE_LIMIT_POLICY.with_sleeper(lambda _: None),
    )

    assert result["tickers_count"] == 2
    # daily_bars.csv consolidated for both tickers (15 bars each).
    assert result["daily_bars_count"] == 30
    bars = (tmp_path / "daily_bars.csv").read_text(encoding="utf-8-sig")
    assert bars.startswith("ticker,date,open,high,low,close,volume")
    assert "7203," in bars and "8306," in bars
    # financials saved.
    assert (tmp_path / "yahoo_financials.csv").is_file()
    # RAG evidence built (one note per ticker) and indexed.
    rag = result["rag"]
    assert isinstance(rag, dict) and rag["documents_written"] == 2
    assert (tmp_path / "rag" / "7203.md").is_file()
    assert isinstance(rag["index"], dict) and rag["index"]["files_indexed"] == 2


def test_daily_refresh_can_skip_rag(tmp_path: Path) -> None:
    result = run_market_daily_refresh(
        tickers=["7203"],
        range_="1mo",
        daily_bars_path=tmp_path / "daily_bars.csv",
        financials_path=tmp_path / "fin.csv",
        rag_dir=tmp_path / "rag",
        rag_db_path=tmp_path / "rag.sqlite",
        build_rag=False,
        fetch=_fake_fetch,
        rate_limit_policy=DEFAULT_YAHOO_RATE_LIMIT_POLICY.with_sleeper(lambda _: None),
    )
    assert result["rag"] is None
    assert result["daily_bars_count"] == 15
