"""Yahoo! Finance market-fundamental fetcher.

Complements EDINET-derived accounting data with market metrics from Yahoo's
quote endpoint: price, PER, PBR, dividend yield, DPS, EPS, and market cap.
Personal-use, on-demand only; the shared market fetcher honors robots.txt by
default and only skips that gate when ``MARKET_ALLOW_ROBOTS_BYPASS=1`` is set.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from html import unescape

from investment_assistant.observability import get_logger
from investment_assistant.portfolio._market_common import (
    MarketFetchPolicy,
    MarketFetchRunner,
    default_fetch,
    normalize_tickers,
    render_csv,
)

_logger = get_logger("portfolio.yahoo_financials")

YAHOO_QUOTE_URL_TEMPLATE = (
    "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
)
YAHOO_JAPAN_QUOTE_URL_TEMPLATE = "https://finance.yahoo.co.jp/quote/{ticker}.T"
DEFAULT_BATCH_SYMBOLS = 40
_CSV_FIELDS = (
    "ticker",
    "name",
    "price",
    "per",
    "pbr",
    "dps",
    "dividend_yield",
    "dividend_yield_percent",
    "eps",
    "market_cap",
)
_HTML_METRIC_LABELS: tuple[tuple[str, str], ...] = (
    ("PER", "per"),
    ("PBR", "pbr"),
    ("1株配当", "dps"),
    ("EPS", "eps"),
)
_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("regularMarketPrice", "price"),
    ("trailingPE", "per"),
    ("priceToBook", "pbr"),
    ("trailingAnnualDividendRate", "dps"),
    ("trailingAnnualDividendYield", "dividend_yield"),
    ("epsTrailingTwelveMonths", "eps"),
    ("marketCap", "market_cap"),
)


def parse_yahoo_quote(json_text: str) -> dict[str, dict[str, object]]:
    """Parse Yahoo v7 quote JSON into ``{ticker: metrics}`` with ``.T`` stripped."""

    out: dict[str, dict[str, object]] = {}
    try:
        results = json.loads(json_text)["quoteResponse"]["result"]
    except (ValueError, KeyError, TypeError):
        return out
    if not isinstance(results, list):
        return out

    for item in results:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        ticker = symbol[:-2] if symbol.upper().endswith(".T") else symbol
        if not ticker:
            continue

        metrics: dict[str, object] = {}
        name = item.get("longName") or item.get("shortName")
        if isinstance(name, str) and name:
            metrics["name"] = name
        for source_key, target_key in _FIELD_MAP:
            value = _num(item.get(source_key))
            if value is not None:
                metrics[target_key] = value
        dividend_yield = _num(metrics.get("dividend_yield"))
        if dividend_yield is not None:
            metrics["dividend_yield_percent"] = dividend_yield * 100.0
        out[ticker] = metrics
    return out


def parse_yahoo_japan_quote_html(html_text: str) -> dict[str, object]:
    """Parse Yahoo Japan quote HTML into normalized market fundamentals."""

    metrics: dict[str, object] = {}
    title_match = re.search(r"<title>(.*?)【", html_text, flags=re.DOTALL)
    if title_match:
        name = _clean_text(title_match.group(1))
        if name:
            metrics["name"] = name

    full_text = _clean_text(html_text)
    price_match = re.search(
        r"ポートフォリオに追加\s*([0-9][0-9,]*(?:\.\d+)?)\s*前日比",
        full_text,
    )
    if price_match:
        metrics["price"] = _parse_number(price_match.group(1))

    for block in re.findall(r"<dl\b[^>]*>.*?</dl>", html_text, flags=re.DOTALL):
        text = _clean_text(block)
        value_text = _dl_value_text(block) or text
        for label, key in _HTML_METRIC_LABELS:
            if text.startswith(label):
                value = _first_value_number(value_text)
                if value is not None and _valid_metric_value(key, value):
                    metrics[key] = value
        if text.startswith("配当利回り"):
            value = _first_value_number(value_text)
            if value is not None:
                metrics["dividend_yield_percent"] = value
                metrics["dividend_yield"] = value / 100.0
        if text.startswith("時価総額"):
            value = _first_value_number(value_text)
            if value is not None:
                metrics["market_cap"] = value * 1_000_000 if "百万円" in text else value
    return {key: value for key, value in metrics.items() if value is not None}


def fetch_yahoo_financials(
    tickers: Iterable[str],
    *,
    fetch: Callable[[str], str] | None = None,
    rate_limit: MarketFetchPolicy | None = None,
    batch_symbols: int = DEFAULT_BATCH_SYMBOLS,
) -> dict[str, object]:
    """Fetch market fundamentals for ``tickers`` in batched Yahoo quote requests."""

    fetcher = fetch or default_fetch
    runner = MarketFetchRunner(fetcher, policy=rate_limit, logger=_logger)
    resolved = normalize_tickers(tickers)
    size = max(int(batch_symbols), 1)
    financials: dict[str, dict[str, object]] = {}
    notes: dict[str, str] = {}
    sources: dict[str, str] = {}

    for index in range(0, len(resolved), size):
        batch = resolved[index : index + size]
        symbols = ",".join(f"{ticker}.T" for ticker in batch)
        url = YAHOO_QUOTE_URL_TEMPLATE.format(symbols=symbols)
        try:
            parsed = parse_yahoo_quote(runner.fetch_once(url, ticker=",".join(batch)))
        except Exception as exc:  # noqa: BLE001 - one bad batch must not abort the rest
            _logger.warning(
                "market financials fetch failed batch=%s error=%s",
                index // size,
                type(exc).__name__,
            )
            for ticker in batch:
                notes[ticker] = type(exc).__name__
            parsed = {}
        for ticker in batch:
            if ticker in parsed:
                financials[ticker] = parsed[ticker]
                sources[ticker] = "yahoo_v7_quote"
            elif ticker not in notes:
                html_url = YAHOO_JAPAN_QUOTE_URL_TEMPLATE.format(ticker=ticker)
                try:
                    metrics = parse_yahoo_japan_quote_html(
                        runner.fetch_once(html_url, ticker=ticker)
                    )
                except Exception as exc:  # noqa: BLE001 - keep the batch best-effort
                    _logger.warning(
                        "market financials html fallback failed ticker=%s error=%s",
                        ticker,
                        type(exc).__name__,
                    )
                    notes[ticker] = type(exc).__name__
                    metrics = {}
                if metrics:
                    financials[ticker] = metrics
                    sources[ticker] = "yahoo_japan_html"
                else:
                    notes[ticker] = "not_found"

    result: dict[str, object] = {
        "provider_id": "yfinance",
        "financials": financials,
        "counts": {ticker: len(metrics) for ticker, metrics in financials.items()},
        "notes": notes,
        "sources": sources,
        "tickers_count": len(resolved),
        "matched_tickers": len(financials),
        "batch_symbols": size,
    }
    if rate_limit is not None:
        result["rate_limit"] = runner.summary()
    return result


def yahoo_financials_csv_text(financials: dict[str, dict[str, object]]) -> str:
    """Render Yahoo market fundamentals as a stable CSV."""

    rows = [{"ticker": ticker, **metrics} for ticker, metrics in financials.items()]
    return render_csv(_CSV_FIELDS, rows)


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _clean_text(value: str) -> str:
    without_comments = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", "", without_comments)
    return re.sub(r"\s+", "", unescape(without_tags))


def _dl_value_text(block: str) -> str:
    match = re.search(r"<dd\b[^>]*>(.*?)</dd>", block, flags=re.DOTALL)
    return _clean_text(match.group(1)) if match else ""


def _first_value_number(text: str) -> float | None:
    without_parentheses = re.sub(r"\([^)]*\)", "", text)
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", without_parentheses)
    return _parse_number(match.group(0)) if match else None


def _parse_number(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _valid_metric_value(key: str, value: float) -> bool:
    if key in {"per", "pbr", "eps"}:
        return value > 0
    return True
