from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from investment_assistant import cli
from investment_assistant.portfolio.ohlcv import (
    fetch_ohlcv,
    ohlcv_csv_text,
    parse_yahoo_ohlcv,
)


def _epoch_midday(date_str: str) -> int:
    return int(datetime.fromisoformat(date_str + "T12:00:00+00:00").timestamp())


def _payload(dates: list[str], *, offset: int = 0, drop_last: bool = False) -> str:
    timestamps = [_epoch_midday(d) - offset for d in dates]
    n = len(dates)
    quote = {
        "open": [100.0 + i for i in range(n)],
        "high": [110.0 + i for i in range(n)],
        "low": [90.0 + i for i in range(n)],
        "close": [105.0 + i for i in range(n)],
        "volume": [1000 + i for i in range(n)],
    }
    if drop_last:  # a non-trading day Yahoo emits as a fully-null row
        for key in quote:
            quote[key][-1] = None
    return json.dumps(
        {"chart": {"result": [{"meta": {"gmtoffset": offset},
                               "timestamp": timestamps,
                               "indicators": {"quote": [quote]}}], "error": None}}
    )


def test_parse_yahoo_ohlcv_maps_bars_with_local_dates() -> None:
    bars = parse_yahoo_ohlcv(_payload(["2026-06-12", "2026-06-15"], offset=32400))
    assert [b.date for b in bars] == ["2026-06-12", "2026-06-15"]
    assert bars[0].open == 100.0 and bars[0].close == 105.0 and bars[0].volume == 1000


def test_parse_yahoo_ohlcv_drops_null_rows_and_rejects_garbage() -> None:
    bars = parse_yahoo_ohlcv(_payload(["2026-06-12", "2026-06-15"], drop_last=True))
    assert [b.date for b in bars] == ["2026-06-12"]
    assert parse_yahoo_ohlcv("not json") == []
    assert parse_yahoo_ohlcv(json.dumps({"chart": {"result": []}})) == []


def test_fetch_ohlcv_scrapes_every_ticker_with_no_hidden_cap() -> None:
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        return _payload(["2026-06-15"])

    result = fetch_ohlcv(["8306", "7203", "9432"], fetch=fake_fetch)

    assert result["provider_id"] == "yfinance"
    assert result["counts"] == {"8306": 1, "7203": 1, "9432": 1}
    # All three are routed to the Yahoo chart endpoint with Tokyo (.T) symbols.
    assert all(".T?range=1mo&interval=1d" in url for url in seen)
    assert len(seen) == 3


def test_run_market_ohlcv_caps_universe_and_writes_csv(tmp_path: Path) -> None:
    out = tmp_path / "ohlcv"

    def fake_fetch(url: str) -> str:
        return _payload(["2026-06-12", "2026-06-15"])

    result = cli.run_market_ohlcv(
        tickers=["8306", "7203", "9432"],
        max_count=2,
        output_dir=out,
        fetch=fake_fetch,
        sleeper=lambda _s: None,
    )

    # max=2 caps the 3 requested tickers down to 2.
    assert result["tickers_count"] == 2
    saved = result["saved_paths"]
    assert isinstance(saved, list) and len(saved) == 2
    # Inline series is omitted when persisting to disk.
    assert "ohlcv" not in result
    csv_text = (out / "8306.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0] == "date,open,high,low,close,volume"
    assert "2026-06-15,101.0,111.0,91.0,106.0,1001" in csv_text


def test_run_market_ohlcv_expands_tickers_from_registry(tmp_path: Path) -> None:
    registry = tmp_path / "reg.yaml"
    registry.write_text(
        "sources:\n"
        '  - name: "a"\n    ticker: "8306"\n    source_type: public_api\n'
        "    provider: edinet\n    allowed: true\n    doc_types: \"120\"\n"
        '  - name: "b"\n    ticker: "7203"\n    source_type: public_api\n'
        "    provider: edinet\n    allowed: true\n    doc_types: \"120\"\n",
        encoding="utf-8",
    )

    result = cli.run_market_ohlcv(
        registry_path=registry, max_count=0, fetch=lambda url: _payload(["2026-06-15"]),
        sleeper=lambda _s: None,
    )

    assert result["tickers_count"] == 2
    assert set(result["counts"]) == {"8306", "7203"}  # type: ignore[arg-type]


def test_ohlcv_csv_text_renders_header_and_blank_nulls() -> None:
    text = ohlcv_csv_text([{"date": "2026-06-15", "open": 1.0, "close": None}])
    lines = text.splitlines()
    assert lines[0] == "date,open,high,low,close,volume"
    # Missing/None fields render as empty cells, not "None".
    assert lines[1] == "2026-06-15,1.0,,,,"
