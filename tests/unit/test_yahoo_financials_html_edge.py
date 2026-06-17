"""Edge-case coverage for the fragile Yahoo Japan HTML fundamentals parser.

Kept in a separate file from the main yahoo_financials tests so these regression
locks are additive and conflict-light.
"""

from __future__ import annotations

from investment_assistant.portfolio.yahoo_financials import parse_yahoo_japan_quote_html


def _dl(label: str, value: str) -> str:
    return f"<dl><dt><span>{label}</span></dt><dd>{value}</dd></dl>"


def test_market_cap_scales_by_unit() -> None:
    # 百万円 -> x1e6 (existing behavior), 億円 -> x1e8 (fixed), bare -> raw yen.
    assert parse_yahoo_japan_quote_html(_dl("時価総額", "10,236,789百万円")) == {
        "market_cap": 10_236_789_000_000.0
    }
    assert parse_yahoo_japan_quote_html(_dl("時価総額", "12,345億円")) == {
        "market_cap": 1_234_500_000_000.0
    }
    assert parse_yahoo_japan_quote_html(_dl("時価総額", "5000000000")) == {
        "market_cap": 5_000_000_000.0
    }


def test_empty_and_garbage_html_yield_no_metrics() -> None:
    assert parse_yahoo_japan_quote_html("") == {}
    assert parse_yahoo_japan_quote_html("<html><body>no data here</body></html>") == {}


def test_negative_and_zero_per_pbr_eps_are_dropped() -> None:
    # Negative/zero PER/PBR/EPS are meaningless or garbage -> dropped.
    assert parse_yahoo_japan_quote_html(_dl("PER", "(連)-3.00倍")) == {}
    assert parse_yahoo_japan_quote_html(_dl("PBR", "0.00倍")) == {}
    assert parse_yahoo_japan_quote_html(_dl("EPS", "(会社予想)0.00")) == {}


def test_name_extracted_from_bracketed_title() -> None:
    html = "<html><head><title>トヨタ自動車(株)【7203】：株価</title></head><body></body></html>"
    assert parse_yahoo_japan_quote_html(html)["name"] == "トヨタ自動車(株)"


def test_dividend_yield_percent_and_fraction_are_both_set() -> None:
    parsed = parse_yahoo_japan_quote_html(_dl("配当利回り", "（会社予想）3.20%"))
    assert parsed["dividend_yield_percent"] == 3.2
    assert parsed["dividend_yield"] == 0.032


def test_price_extracted_with_portfolio_prefix() -> None:
    html = "<section>ＫＤＤＩ(株)9433情報・通信ポートフォリオに追加5,018前日比+11(+0.22%)</section>"
    assert parse_yahoo_japan_quote_html(html)["price"] == 5018.0


def test_price_extracted_without_portfolio_prefix() -> None:
    # Layouts that lack 'ポートフォリオに追加' previously dropped the price even
    # though the number sits right before 前日比.
    html = "<section>タマホーム(株)1419：株価情報2,887前日比-13(-0.45%)</section>"
    assert parse_yahoo_japan_quote_html(html)["price"] == 2887.0


def test_price_extracted_from_genzaine_label() -> None:
    html = "<section>現在値412前日比+2</section>"
    assert parse_yahoo_japan_quote_html(html)["price"] == 412.0


def test_no_price_when_no_price_context() -> None:
    assert "price" not in parse_yahoo_japan_quote_html(_dl("PER", "(連)14.12倍"))
