from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from investment_assistant import cli
from investment_assistant.portfolio._market_common import DEFAULT_YAHOO_RATE_LIMIT_POLICY

_FAST = DEFAULT_YAHOO_RATE_LIMIT_POLICY.with_sleeper(lambda _s: None)


def _epoch_midday(date_str: str) -> int:
    return int(datetime.fromisoformat(date_str + "T12:00:00+00:00").timestamp())


def _ohlcv(dates: list[str]) -> str:
    n = len(dates)
    quote = {
        "open": [100.0 + i for i in range(n)],
        "high": [110.0 + i for i in range(n)],
        "low": [90.0 + i for i in range(n)],
        "close": [105.0 + i for i in range(n)],
        "volume": [1000 + i for i in range(n)],
    }
    return json.dumps(
        {"chart": {"result": [{"meta": {"gmtoffset": 0},
                               "timestamp": [_epoch_midday(d) for d in dates],
                               "indicators": {"quote": [quote]}}], "error": None}}
    )


def test_run_market_bars_flattens_universe_without_saving_by_default() -> None:
    result = cli.run_market_bars(
        tickers=["8306", "7203"],
        fetch=lambda u: _ohlcv(["2026-06-12", "2026-06-15"]),
        rate_limit_policy=_FAST,
    )
    assert result["selected"] == 2 and result["matched_tickers"] == 2
    assert result["rows"] == 4 and result["saved"] is False


def test_run_market_bars_saves_single_daily_bars_csv(tmp_path: Path) -> None:
    out = tmp_path / "daily_bars.csv"
    result = cli.run_market_bars(
        tickers=["8306", "7203", "9432"],
        max_count=2,
        save=True,
        output_path=out,
        fetch=lambda u: _ohlcv(["2026-06-15"]),
        rate_limit_policy=_FAST,
    )
    assert result["selected"] == 2 and result["rows"] == 2 and result["saved"] is True
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ticker,date,open,high,low,close,volume"
    assert any(line.startswith("8306,2026-06-15,") for line in lines[1:])


def test_market_bars_api_route_empty_universe() -> None:
    from investment_assistant.webapi.service import handle_api

    status, payload = handle_api("POST", "/api/market/bars", {"tickers": []})
    assert status == 200
    assert payload["selected"] == 0 and payload["rows"] == 0 and payload["saved"] is False
