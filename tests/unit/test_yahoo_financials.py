from __future__ import annotations

import json
from pathlib import Path

from investment_assistant import cli
from investment_assistant.portfolio._market_common import DEFAULT_YAHOO_RATE_LIMIT_POLICY
from investment_assistant.portfolio.yahoo_financials import (
    fetch_yahoo_financials,
    parse_yahoo_japan_quote_html,
    parse_yahoo_quote,
    yahoo_financials_csv_text,
)


def _quote_payload(*symbols: str) -> str:
    results = []
    for index, symbol in enumerate(symbols):
        results.append(
            {
                "symbol": symbol,
                "longName": f"Company {symbol}",
                "regularMarketPrice": 1000.0 + index,
                "trailingPE": 12.3 + index,
                "priceToBook": 1.1 + index,
                "trailingAnnualDividendRate": 32.0 + index,
                "trailingAnnualDividendYield": 0.032 + (index * 0.001),
                "epsTrailingTwelveMonths": 81.3 + index,
                "marketCap": 1234567890 + index,
            }
        )
    return json.dumps({"quoteResponse": {"result": results}})


def _html_payload() -> str:
    return """
    <html><head><title>ＫＤＤＩ(株)【9433】：株価・株式情報</title></head>
    <body>
      <section>ＫＤＤＩ(株)9433情報・通信ポートフォリオに追加5,018前日比+11(+0.22%)</section>
      <dl><dt><span>配当利回り</span><span>（会社予想）</span></dt><dd>3.20%</dd></dl>
      <dl><dt><span>1株配当</span><span>（会社予想）</span></dt><dd>160.00円</dd></dl>
      <dl><dt><span>PER</span><span>（会社予想）</span></dt><dd>(連)14.12倍</dd></dl>
      <dl><dt><span>PBR</span><span>（実績）</span></dt><dd>(連)1.91倍</dd></dl>
      <dl><dt><span>EPS</span><span>（会社予想）</span></dt><dd>355.38</dd></dl>
      <dl><dt><span>時価総額</span></dt><dd>10,236,789百万円</dd></dl>
    </body></html>
    """


def test_parse_yahoo_quote_normalizes_tokyo_symbol_and_yield_percent() -> None:
    parsed = parse_yahoo_quote(_quote_payload("9432.T"))

    assert set(parsed) == {"9432"}
    assert parsed["9432"]["price"] == 1000.0
    assert parsed["9432"]["per"] == 12.3
    assert parsed["9432"]["pbr"] == 1.1
    assert parsed["9432"]["dps"] == 32.0
    assert parsed["9432"]["dividend_yield"] == 0.032
    assert parsed["9432"]["dividend_yield_percent"] == 3.2
    assert parsed["9432"]["eps"] == 81.3
    assert parsed["9432"]["market_cap"] == 1234567890.0


def test_parse_yahoo_japan_quote_html_extracts_market_fundamentals() -> None:
    parsed = parse_yahoo_japan_quote_html(_html_payload())

    assert parsed["name"] == "ＫＤＤＩ(株)"
    assert parsed["price"] == 5018.0
    assert parsed["dividend_yield"] == 0.032
    assert parsed["dividend_yield_percent"] == 3.2
    assert parsed["dps"] == 160.0
    assert parsed["per"] == 14.12
    assert parsed["pbr"] == 1.91
    assert parsed["eps"] == 355.38
    assert parsed["market_cap"] == 10_236_789_000_000.0


def test_parse_yahoo_japan_quote_html_ignores_dates_when_value_is_missing() -> None:
    parsed = parse_yahoo_japan_quote_html(
        """
        <dl><dt><span>PER</span><span>（会社予想）</span></dt><dd>---(--:--)</dd></dl>
        <dl><dt><span>PER</span><span>（過去3年平均）</span></dt><dd>000.00倍00/00</dd></dl>
        <dl><dt><span>EPS</span><span>（会社予想）</span></dt><dd>---(2027/03)</dd></dl>
        <dl><dt><span>AI値動き解説</span></dt><dd>ROEは8～10%を上回り、EPSも改善。</dd></dl>
        <dl><dt><span>1株配当</span><span>（会社予想）</span></dt><dd>84.00円(2027/03)</dd></dl>
        """
    )

    assert "per" not in parsed
    assert "eps" not in parsed
    assert parsed["dps"] == 84.0


def test_fetch_yahoo_financials_batches_quote_requests() -> None:
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        if "8306.T,7203.T" in url:
            return _quote_payload("8306.T", "7203.T")
        return _quote_payload("9432.T")

    result = fetch_yahoo_financials(
        ["8306", "7203", "9432"],
        fetch=fake_fetch,
        batch_symbols=2,
        rate_limit=DEFAULT_YAHOO_RATE_LIMIT_POLICY.with_sleeper(lambda _: None),
    )

    assert len(seen) == 2
    assert result["matched_tickers"] == 3
    assert result["counts"] == {"8306": 9, "7203": 9, "9432": 9}
    assert result["notes"] == {}


def test_fetch_yahoo_financials_falls_back_to_yahoo_japan_html() -> None:
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        if "query1.finance.yahoo.com" in url:
            return json.dumps({"quoteResponse": {"result": []}})
        return _html_payload()

    result = fetch_yahoo_financials(
        ["9433"],
        fetch=fake_fetch,
        rate_limit=DEFAULT_YAHOO_RATE_LIMIT_POLICY.with_sleeper(lambda _: None),
    )

    assert any("query1.finance.yahoo.com" in url for url in seen)
    assert any("finance.yahoo.co.jp/quote/9433.T" in url for url in seen)
    assert result["matched_tickers"] == 1
    assert result["financials"]["9433"]["dividend_yield_percent"] == 3.2  # type: ignore[index]
    assert result["sources"] == {"9433": "yahoo_japan_html"}
    assert result["notes"] == {}


def test_yahoo_financials_csv_text_uses_stable_header() -> None:
    text = yahoo_financials_csv_text(
        {
            "9432": {
                "name": "KDDI",
                "price": 5000.0,
                "dividend_yield_percent": 3.2,
            }
        }
    )

    assert text.splitlines() == [
        "ticker,name,price,per,pbr,dps,dividend_yield,dividend_yield_percent,eps,market_cap",
        "9432,KDDI,5000.0,,,,,3.2,,",
    ]


def test_run_market_financials_saves_csv_with_registry_expansion(tmp_path: Path) -> None:
    registry = tmp_path / "reg.yaml"
    registry.write_text(
        "sources:\n"
        '  - name: "a"\n    ticker: "8306"\n    source_type: public_api\n'
        "    provider: edinet\n    allowed: true\n    doc_types: \"120\"\n"
        '  - name: "b"\n    ticker: "7203"\n    source_type: public_api\n'
        "    provider: edinet\n    allowed: true\n    doc_types: \"120\"\n",
        encoding="utf-8",
    )
    out = tmp_path / "yahoo_financials.csv"

    result = cli.run_market_financials(
        registry_path=registry,
        max_count=1,
        save=True,
        output_path=out,
        fetch=lambda _url: _quote_payload("8306.T"),
        rate_limit_policy=DEFAULT_YAHOO_RATE_LIMIT_POLICY.with_sleeper(lambda _: None),
    )

    assert result["tickers_count"] == 1
    assert result["matched_tickers"] == 1
    assert result["saved"] is True
    csv_text = out.read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0].startswith("ticker,name,price")
    assert "8306,Company 8306.T,1000.0,12.3" in csv_text
