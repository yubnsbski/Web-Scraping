from __future__ import annotations

import json
from pathlib import Path

from investment_assistant import cli
from investment_assistant.portfolio._market_common import DEFAULT_YAHOO_RATE_LIMIT_POLICY
from investment_assistant.portfolio.yahoo_intraday import (
    extract_preloaded_state,
    fetch_yahoo_intraday,
    parse_yahoo_intraday,
)


def _history(time_hm: str, close: float | None) -> dict[str, object]:
    return {"baseDatetime": f"2026-06-15T{time_hm}:00+09:00", "closePrice": close}


def _page(histories: list[dict[str, object]], *, trailing: str = ";\n</script>") -> str:
    state = {
        "mainItemDetailChartSetting": {"timeSeriesData": {"histories": histories}},
    }
    # Mimic the real page: the JSON is embedded in a <script> with trailing source.
    return (
        "<html><head><script>window.__PRELOADED_STATE__ = "
        + json.dumps(state, ensure_ascii=False)
        + trailing
        + "</head></html>"
    )


def test_extract_preloaded_state_decodes_first_json_object() -> None:
    state = extract_preloaded_state(_page([_history("09:00", 4396)]))
    assert state is not None
    assert "mainItemDetailChartSetting" in state


def test_parse_yahoo_intraday_extracts_minute_closes() -> None:
    page = _page([_history("09:00", 4396), _history("09:01", 4386), _history("09:02", 4393)])
    ticks = parse_yahoo_intraday(page)
    assert [(t.time, t.close) for t in ticks] == [
        ("09:00", 4396.0),
        ("09:01", 4386.0),
        ("09:02", 4393.0),
    ]


def test_parse_yahoo_intraday_skips_null_prices_and_bad_pages() -> None:
    page = _page([_history("09:00", 4396), _history("09:01", None), _history("09:02", 0)])
    ticks = parse_yahoo_intraday(page)
    assert [t.time for t in ticks] == ["09:00"]  # null/zero closes dropped
    assert parse_yahoo_intraday("<html>no state here</html>") == []
    assert parse_yahoo_intraday("__PRELOADED_STATE__ = not-json") == []


def test_fetch_yahoo_intraday_uses_jp_quote_url_for_each_ticker() -> None:
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        return _page([_history("09:00", 100), _history("09:01", 101)])

    result = fetch_yahoo_intraday(["2914", "8306"], fetch=fake_fetch)

    assert result["provider_id"] == "yahoo_jp_intraday"
    assert result["counts"] == {"2914": 2, "8306": 2}
    assert seen == [
        "https://finance.yahoo.co.jp/quote/2914.T?term=1d",
        "https://finance.yahoo.co.jp/quote/8306.T?term=1d",
    ]


def test_run_yahoo_intraday_caps_and_writes_csv(tmp_path: Path) -> None:
    out = tmp_path / "intraday"

    def fake_fetch(url: str) -> str:
        return _page([_history("09:00", 100), _history("09:01", 101)])

    result = cli.run_yahoo_intraday(
        tickers=["2914", "8306", "9934"],
        max_count=2,
        output_dir=out,
        fetch=fake_fetch,
        rate_limit_policy=DEFAULT_YAHOO_RATE_LIMIT_POLICY.with_sleeper(lambda _: None),
    )

    assert result["tickers_count"] == 2
    assert "intraday" not in result  # series persisted to disk, not inlined
    csv_text = (out / "2914.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0] == "time,datetime,open,high,low,close,volume"
    assert csv_text.splitlines()[1].startswith("09:00,2026-06-15T09:00:00+09:00,")
    assert csv_text.splitlines()[1].endswith(",100.0,")
