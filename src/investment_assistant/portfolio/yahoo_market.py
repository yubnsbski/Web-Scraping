"""Yahoo! Finance market-data acquisition for the local single-user app."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Protocol

from investment_assistant.ingestion.fetcher import SafeFetcher, reject_path_traversal
from investment_assistant.portfolio.bar_store import (
    DEFAULT_DAILY_BARS_CSV,
    DailyBarFact,
    latest_price_facts_from_bars,
    load_daily_bars,
    merge_daily_bars,
    save_daily_bars,
    summarize_daily_bars,
)
from investment_assistant.portfolio.price_store import (
    DEFAULT_CURRENT_PRICES_CSV,
    load_current_prices,
    merge_market_price_facts,
    save_current_prices,
)

YAHOO_CHART_URL_TEMPLATE = (
    "https://query1.finance.yahoo.com/v8/finance/chart/"
    "{ticker}.T?range={range_}&interval={interval}"
)
YAHOO_QUOTE_URL_TEMPLATE = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
YAHOO_JAPAN_QUOTE_URL_TEMPLATE = "https://finance.yahoo.co.jp/quote/{ticker}.T"
DEFAULT_YAHOO_FUNDAMENTALS_CSV = Path("local_docs/market/yahoo_financials.csv")
ALLOWED_RANGES = frozenset({"5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"})
ALLOWED_INTERVALS = frozenset({"1d", "1wk", "1mo"})
FUNDAMENTAL_COLUMNS = (
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
    "as_of",
    "provider_id",
    "source_ref",
)
_NUMERIC_FIELDS = {
    "price",
    "per",
    "pbr",
    "dps",
    "dividend_yield",
    "dividend_yield_percent",
    "eps",
    "market_cap",
}
_QUOTE_FIELDS = {
    "regularMarketPrice": "price",
    "trailingPE": "per",
    "priceToBook": "pbr",
    "trailingAnnualDividendRate": "dps",
    "trailingAnnualDividendYield": "dividend_yield",
    "epsTrailingTwelveMonths": "eps",
    "marketCap": "market_cap",
}
_HTML_FIELDS = {"PER": "per", "PBR": "pbr", "1株配当": "dps", "EPS": "eps"}
_PRICE_PATTERNS = (
    r"ポートフォリオに追加([0-9][0-9,]*(?:\.\d+)?)前日比",
    r"([0-9][0-9,]*(?:\.\d+)?)前日比",
    r"現在値([0-9][0-9,]*(?:\.\d+)?)",
)


class YahooMarketError(RuntimeError):
    """Raised when a Yahoo response cannot provide usable data."""


class _Document(Protocol):
    allowed_by_robots: bool
    status_code: int | None
    html: str
    source: str


class _Fetcher(Protocol):
    def fetch_document(self, url: str) -> _Document: ...


def normalize_tickers(tickers: Iterable[object]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        ticker = ticker[:-2] if ticker.endswith(".T") else ticker
        if ticker and ticker not in seen:
            seen.add(ticker)
            resolved.append(ticker)
    return resolved


def parse_yahoo_chart(json_text: str, *, ticker: str, source_ref: str) -> list[DailyBarFact]:
    root = _json_dict(json_text)
    chart = _dict_value(root, "chart")
    result = _first_dict(_list_value(chart, "result"))
    timestamps = _list_value(result, "timestamp")
    indicators = _dict_value(result, "indicators")
    quote = _first_dict(_list_value(indicators, "quote"))
    adjclose = _first_dict(_list_value(indicators, "adjclose"))
    meta = _dict_value(result, "meta")
    offset = _number(meta.get("gmtoffset")) or 0.0
    if not timestamps or not quote:
        return []

    bars: list[DailyBarFact] = []
    for index, raw_timestamp in enumerate(timestamps):
        timestamp = _number(raw_timestamp)
        if timestamp is None:
            continue
        open_value = _indexed_number(quote.get("open"), index)
        high_value = _indexed_number(quote.get("high"), index)
        low_value = _indexed_number(quote.get("low"), index)
        close_value = _indexed_number(quote.get("close"), index)
        if all(value is None for value in (open_value, high_value, low_value, close_value)):
            continue
        bars.append(
            DailyBarFact(
                ticker=ticker,
                date=datetime.fromtimestamp(int(timestamp + offset), tz=UTC).date().isoformat(),
                open=open_value,
                high=high_value,
                low=low_value,
                close=close_value,
                volume=_indexed_number(quote.get("volume"), index),
                adjusted_close=_indexed_number(adjclose.get("adjclose"), index),
                provider_id="yahoo_finance",
                source_ref=source_ref,
            )
        )
    return bars


def parse_yahoo_quote(json_text: str) -> dict[str, dict[str, object]]:
    root = _json_dict(json_text)
    response = _dict_value(root, "quoteResponse")
    results = _list_value(response, "result")
    parsed: dict[str, dict[str, object]] = {}
    for raw_item in results:
        item = _as_dict(raw_item)
        ticker = str(item.get("symbol") or "").strip().upper()
        ticker = ticker[:-2] if ticker.endswith(".T") else ticker
        if not ticker:
            continue
        row: dict[str, object] = {
            "ticker": ticker,
            "provider_id": "yahoo_finance",
            "source_ref": "yahoo_v7_quote",
        }
        name = item.get("longName") or item.get("shortName")
        if isinstance(name, str) and name.strip():
            row["name"] = name.strip()
        for source_key, target_key in _QUOTE_FIELDS.items():
            value = _number(item.get(source_key))
            if value is not None:
                row[target_key] = value
        dividend_yield = _number(row.get("dividend_yield"))
        if dividend_yield is not None:
            row["dividend_yield_percent"] = dividend_yield * 100.0
        parsed[ticker] = row
    return parsed


def parse_yahoo_japan_html(html_text: str, *, ticker: str) -> dict[str, object]:
    text = _clean_html(html_text)
    row: dict[str, object] = {
        "ticker": ticker,
        "provider_id": "yahoo_finance",
        "source_ref": YAHOO_JAPAN_QUOTE_URL_TEMPLATE.format(ticker=ticker),
    }
    title = re.search(r"<title>(.*?)【", html_text, flags=re.DOTALL)
    if title and (name := _clean_html(title.group(1))):
        row["name"] = name
    if (price := _extract_price(text)) is not None:
        row["price"] = price
    for block in re.findall(r"<dl\b[^>]*>.*?</dl>", html_text, flags=re.DOTALL):
        block_text = _clean_html(block)
        value_text = _dl_value(block) or block_text
        for label, key in _HTML_FIELDS.items():
            if block_text.startswith(label) and (value := _first_number(value_text)) is not None:
                if key not in {"per", "pbr", "eps"} or value > 0:
                    row[key] = value
        if block_text.startswith("配当利回り") and (value := _first_number(value_text)) is not None:
            row["dividend_yield_percent"] = value
            row["dividend_yield"] = value / 100.0
        if block_text.startswith("時価総額") and (value := _first_number(value_text)) is not None:
            row["market_cap"] = _scale_market_cap(value, block_text)
    return row


def load_yahoo_fundamentals(
    path: str | Path = DEFAULT_YAHOO_FUNDAMENTALS_CSV,
) -> dict[str, dict[str, object]]:
    csv_path = Path(path)
    if not csv_path.is_file():
        return {}
    output: dict[str, dict[str, object]] = {}
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            ticker = str(raw.get("ticker") or "").strip()
            if not ticker:
                continue
            row: dict[str, object] = {"ticker": ticker}
            for key, value in raw.items():
                if key and value and key != "ticker":
                    row[key] = _number(value) if key in _NUMERIC_FIELDS else value
            output[ticker] = row
    return output


def save_yahoo_fundamentals(
    rows: Mapping[str, Mapping[str, object]],
    path: str | Path = DEFAULT_YAHOO_FUNDAMENTALS_CSV,
) -> str:
    target = reject_path_traversal(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(FUNDAMENTAL_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for ticker in sorted(rows):
        writer.writerow(
            {
                column: _csv_value(ticker if column == "ticker" else rows[ticker].get(column))
                for column in FUNDAMENTAL_COLUMNS
            }
        )
    target.write_text(output.getvalue(), encoding="utf-8-sig")
    return str(target)


def refresh_yahoo_market(
    tickers: Iterable[object],
    *,
    range_: str = "1mo",
    interval: str = "1d",
    fetch_ohlcv: bool = True,
    fetch_fundamentals: bool = True,
    daily_bars_path: str | Path = DEFAULT_DAILY_BARS_CSV,
    current_prices_path: str | Path = DEFAULT_CURRENT_PRICES_CSV,
    fundamentals_path: str | Path = DEFAULT_YAHOO_FUNDAMENTALS_CSV,
    fetcher: _Fetcher | None = None,
) -> dict[str, object]:
    resolved = normalize_tickers(tickers)
    if not resolved:
        raise ValueError("at least one ticker is required")
    if range_ not in ALLOWED_RANGES or interval not in ALLOWED_INTERVALS:
        raise ValueError("unsupported Yahoo range or interval")
    if not fetch_ohlcv and not fetch_fundamentals:
        raise ValueError("enable fetch_ohlcv and/or fetch_fundamentals")

    market_fetcher: _Fetcher = fetcher or SafeFetcher(timeout_seconds=20.0)
    failures: dict[str, list[str]] = {ticker: [] for ticker in resolved}
    fetched_bars: dict[str, list[DailyBarFact]] = {}
    fetch_sources: dict[str, str] = {}

    if fetch_ohlcv:
        for ticker in resolved:
            url = YAHOO_CHART_URL_TEMPLATE.format(
                ticker=ticker.lower(), range_=range_, interval=interval
            )
            try:
                body, source = _fetch_text(market_fetcher, url)
                bars = parse_yahoo_chart(body, ticker=ticker, source_ref=url)
                if bars:
                    fetched_bars[ticker] = bars
                    fetch_sources[ticker] = source
                else:
                    failures[ticker].append("ohlcv_empty")
            except YahooMarketError as exc:
                failures[ticker].append(f"ohlcv:{exc}")

    incoming_bars = [bar for ticker_bars in fetched_bars.values() for bar in ticker_bars]
    saved_bars = str(daily_bars_path)
    saved_prices = str(current_prices_path)
    if incoming_bars:
        saved_bars = save_daily_bars(
            merge_daily_bars(load_daily_bars(daily_bars_path), incoming_bars), daily_bars_path
        )
        price_facts = latest_price_facts_from_bars(incoming_bars, source_ref=saved_bars)
        saved_prices = save_current_prices(
            merge_market_price_facts(load_current_prices(current_prices_path).values(), price_facts),
            current_prices_path,
        )

    latest_close = {
        ticker: close
        for ticker, ticker_bars in fetched_bars.items()
        if (close := _latest_close(ticker_bars)) is not None
    }
    fundamentals: dict[str, dict[str, object]] = {}
    if fetch_fundamentals:
        fundamentals.update(_fetch_quote_batches(market_fetcher, resolved))
        for ticker in resolved:
            resolved_row: dict[str, object] | None = fundamentals.get(ticker)
            needs_html = resolved_row is None or not any(
                key in resolved_row
                for key in ("per", "pbr", "dps", "dividend_yield", "eps", "market_cap")
            )
            if needs_html:
                url = YAHOO_JAPAN_QUOTE_URL_TEMPLATE.format(ticker=ticker)
                try:
                    html, _ = _fetch_text(market_fetcher, url)
                    html_row = parse_yahoo_japan_html(html, ticker=ticker)
                    if len(html_row) > 3:
                        resolved_row = _merge_missing(resolved_row, html_row)
                        fundamentals[ticker] = resolved_row
                    else:
                        failures[ticker].append("fundamentals_empty")
                except YahooMarketError as exc:
                    failures[ticker].append(f"fundamentals:{exc}")
            if resolved_row is not None:
                if "price" not in resolved_row and ticker in latest_close:
                    resolved_row["price"] = latest_close[ticker]
                    resolved_row["source_ref"] = (
                        f"{resolved_row.get('source_ref', '')}+chart_close"
                    )
                resolved_row["as_of"] = datetime.now(UTC).date().isoformat()

    saved_fundamentals = str(fundamentals_path)
    if fundamentals:
        merged = load_yahoo_fundamentals(fundamentals_path)
        merged.update(fundamentals)
        saved_fundamentals = save_yahoo_fundamentals(merged, fundamentals_path)

    errors = {ticker: messages for ticker, messages in failures.items() if messages}
    completed = max(len(fetched_bars), len(fundamentals))
    status = "blocked" if completed == 0 else "partial" if errors else "completed"
    return {
        "status": status,
        "provider_id": "yahoo_finance",
        "requested_count": len(resolved),
        "tickers": resolved,
        "ohlcv_ticker_count": len(fetched_bars),
        "ohlcv_row_count": len(incoming_bars),
        "fundamentals_ticker_count": len(fundamentals),
        "latest_bars": [
            _bar_summary(ticker, ticker_bars)
            for ticker, ticker_bars in sorted(fetched_bars.items())
        ],
        "fundamentals": [fundamentals[ticker] for ticker in sorted(fundamentals)],
        "errors": errors,
        "fetch_sources": fetch_sources,
        "saved": {
            "daily_bars_path": saved_bars,
            "current_prices_path": saved_prices,
            "fundamentals_path": saved_fundamentals,
        },
        "ohlcv_summary": summarize_daily_bars(incoming_bars),
        "policy": {
            "personal_use_only": True,
            "robots_checked": True,
            "rate_limited": True,
            "redistribution": False,
            "auto_trading": False,
        },
        "auto_trading": False,
        "call_real_api": True,
    }


def _fetch_quote_batches(fetcher: _Fetcher, tickers: Sequence[str]) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for start in range(0, len(tickers), 40):
        batch = tickers[start : start + 40]
        url = YAHOO_QUOTE_URL_TEMPLATE.format(symbols=",".join(f"{ticker}.T" for ticker in batch))
        try:
            body, _ = _fetch_text(fetcher, url)
        except YahooMarketError:
            continue
        parsed = parse_yahoo_quote(body)
        for parsed_row in parsed.values():
            parsed_row["source_ref"] = url
        output.update(parsed)
    return output


def _fetch_text(fetcher: _Fetcher, url: str) -> tuple[str, str]:
    document = fetcher.fetch_document(url)
    if not document.allowed_by_robots:
        raise YahooMarketError(document.source or "robots_blocked")
    if document.status_code is not None and document.status_code >= 400:
        raise YahooMarketError(f"http_{document.status_code}")
    if not document.html.strip():
        raise YahooMarketError("empty_response")
    return document.html, document.source


def _merge_missing(
    existing: dict[str, object] | None, incoming: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(existing or {})
    source = str(merged.get("source_ref") or "")
    for key, value in incoming.items():
        if key not in merged or merged[key] in (None, ""):
            merged[key] = value
    incoming_source = str(incoming.get("source_ref") or "")
    merged["source_ref"] = "+".join(item for item in (source, incoming_source) if item)
    return merged


def _bar_summary(ticker: str, bars: Sequence[DailyBarFact]) -> dict[str, object]:
    latest = max(bars, key=lambda bar: bar.date)
    return {
        "ticker": ticker,
        "date": latest.date,
        "open": latest.open,
        "high": latest.high,
        "low": latest.low,
        "close": latest.close,
        "adjusted_close": latest.adjusted_close,
        "volume": latest.volume,
        "bar_count": len(bars),
        "provider_id": latest.provider_id,
        "source_ref": latest.source_ref,
    }


def _latest_close(bars: Sequence[DailyBarFact]) -> float | None:
    for bar in sorted(bars, key=lambda item: item.date, reverse=True):
        value = bar.adjusted_close or bar.close
        if value is not None and value > 0:
            return float(value)
    return None


def _json_dict(text: str) -> dict[str, object]:
    try:
        return _as_dict(json.loads(text))
    except (TypeError, ValueError):
        return {}


def _as_dict(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _dict_value(mapping: Mapping[str, object], key: str) -> dict[str, object]:
    return _as_dict(mapping.get(key))


def _list_value(mapping: Mapping[str, object], key: str) -> list[object]:
    value = mapping.get(key)
    return list(value) if isinstance(value, list) else []


def _first_dict(values: Sequence[object]) -> dict[str, object]:
    return _as_dict(values[0]) if values else {}


def _indexed_number(value: object, index: int) -> float | None:
    return _number(value[index]) if isinstance(value, list) and index < len(value) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _clean_html(value: str) -> str:
    no_comments = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    return re.sub(r"\s+", "", unescape(re.sub(r"<[^>]+>", "", no_comments)))


def _dl_value(block: str) -> str:
    match = re.search(r"<dd\b[^>]*>(.*?)</dd>", block, flags=re.DOTALL)
    return _clean_html(match.group(1)) if match else ""


def _first_number(text: str) -> float | None:
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", re.sub(r"\([^)]*\)", "", text))
    return _number(match.group(0)) if match else None


def _extract_price(text: str) -> float | None:
    for pattern in _PRICE_PATTERNS:
        if match := re.search(pattern, text):
            value = _number(match.group(1))
            if value is not None and value > 0:
                return value
    return None


def _scale_market_cap(value: float, text: str) -> float:
    if "百万円" in text:
        return value * 1_000_000
    if "億円" in text:
        return value * 100_000_000
    if "兆円" in text:
        return value * 1_000_000_000_000
    return value


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(round(value, 8))
    return str(value)
