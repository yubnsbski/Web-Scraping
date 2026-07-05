"""Yahoo! Finance OHLCV and market-fundamental acquisition."""

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
    "ticker", "name", "price", "per", "pbr", "dps", "dividend_yield",
    "dividend_yield_percent", "eps", "market_cap", "as_of", "provider_id", "source_ref",
)
_NUMERIC_FIELDS = frozenset(FUNDAMENTAL_COLUMNS[2:10])
_QUOTE_FIELDS = {
    "regularMarketPrice": "price", "trailingPE": "per", "priceToBook": "pbr",
    "trailingAnnualDividendRate": "dps",
    "trailingAnnualDividendYield": "dividend_yield",
    "epsTrailingTwelveMonths": "eps", "marketCap": "market_cap",
}
_HTML_FIELDS = {"PER": "per", "PBR": "pbr", "1株配当": "dps", "EPS": "eps"}
_PRICE_PATTERNS = (
    r"ポートフォリオに追加([0-9][0-9,]*(?:\.\d+)?)前日比",
    r"([0-9][0-9,]*(?:\.\d+)?)前日比",
    r"現在値([0-9][0-9,]*(?:\.\d+)?)",
)


class YahooMarketError(RuntimeError):
    """Yahoo returned no usable, policy-allowed response."""


class _Document(Protocol):
    allowed_by_robots: bool
    status_code: int | None
    html: str
    source: str


class _Fetcher(Protocol):
    def fetch_document(self, url: str) -> _Document: ...


def normalize_tickers(tickers: Iterable[object]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        ticker = ticker[:-2] if ticker.endswith(".T") else ticker
        if ticker and ticker not in seen:
            seen.add(ticker)
            output.append(ticker)
    return output


def parse_yahoo_chart(json_text: str, *, ticker: str, source_ref: str) -> list[DailyBarFact]:
    root = _json_dict(json_text)
    result = _first_dict(_list(_dict(root.get("chart")).get("result")))
    timestamps = _list(result.get("timestamp"))
    indicators = _dict(result.get("indicators"))
    quote = _first_dict(_list(indicators.get("quote")))
    adjusted = _first_dict(_list(indicators.get("adjclose")))
    offset = _number(_dict(result.get("meta")).get("gmtoffset")) or 0.0
    if not timestamps or not quote:
        return []
    bars: list[DailyBarFact] = []
    for index, raw_timestamp in enumerate(timestamps):
        timestamp = _number(raw_timestamp)
        values = tuple(_at(quote.get(key), index) for key in ("open", "high", "low", "close"))
        if timestamp is None or all(value is None for value in values):
            continue
        bars.append(
            DailyBarFact(
                ticker=ticker,
                date=datetime.fromtimestamp(int(timestamp + offset), tz=UTC).date().isoformat(),
                open=values[0], high=values[1], low=values[2], close=values[3],
                volume=_at(quote.get("volume"), index),
                adjusted_close=_at(adjusted.get("adjclose"), index),
                provider_id="yahoo_finance", source_ref=source_ref,
            )
        )
    return bars


def parse_yahoo_quote(json_text: str) -> dict[str, dict[str, object]]:
    root = _json_dict(json_text)
    items = _list(_dict(root.get("quoteResponse")).get("result"))
    output: dict[str, dict[str, object]] = {}
    for raw_item in items:
        item = _dict(raw_item)
        ticker = str(item.get("symbol") or "").strip().upper()
        ticker = ticker[:-2] if ticker.endswith(".T") else ticker
        if not ticker:
            continue
        row: dict[str, object] = {
            "ticker": ticker, "provider_id": "yahoo_finance", "source_ref": "yahoo_v7_quote"
        }
        name = item.get("longName") or item.get("shortName")
        if isinstance(name, str) and name.strip():
            row["name"] = name.strip()
        for source, target in _QUOTE_FIELDS.items():
            if (value := _number(item.get(source))) is not None:
                row[target] = value
        if (yield_value := _number(row.get("dividend_yield"))) is not None:
            row["dividend_yield_percent"] = yield_value * 100.0
        output[ticker] = row
    return output


def parse_yahoo_japan_html(html_text: str, *, ticker: str) -> dict[str, object]:
    plain = _clean_html(html_text)
    row: dict[str, object] = {
        "ticker": ticker,
        "provider_id": "yahoo_finance",
        "source_ref": YAHOO_JAPAN_QUOTE_URL_TEMPLATE.format(ticker=ticker),
    }
    title = re.search(r"<title>(.*?)【", html_text, flags=re.DOTALL)
    if title and (name := _clean_html(title.group(1))):
        row["name"] = name
    if (price := _extract_price(plain)) is not None:
        row["price"] = price
    for block in re.findall(r"<dl\b[^>]*>.*?</dl>", html_text, flags=re.DOTALL):
        block_text = _clean_html(block)
        value_text = _dl_value(block) or block_text
        for label, key in _HTML_FIELDS.items():
            value = _first_number(value_text)
            if (
                block_text.startswith(label)
                and value is not None
                and (key not in {"per", "pbr", "eps"} or value > 0)
            ):
                row[key] = value
        if block_text.startswith("配当利回り") and (value := _first_number(value_text)) is not None:
            row.update(dividend_yield_percent=value, dividend_yield=value / 100.0)
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
        writer.writerow({key: _csv(ticker if key == "ticker" else rows[ticker].get(key))
                         for key in FUNDAMENTAL_COLUMNS})
    target.write_text(output.getvalue(), encoding="utf-8-sig")
    return str(target)


def refresh_yahoo_market(
    tickers: Iterable[object], *, range_: str = "1mo", interval: str = "1d",
    fetch_ohlcv: bool = True, fetch_fundamentals: bool = True,
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
    client: _Fetcher = fetcher or SafeFetcher(timeout_seconds=20.0)
    failures: dict[str, list[str]] = {ticker: [] for ticker in resolved}
    fetched: dict[str, list[DailyBarFact]] = {}
    sources: dict[str, str] = {}

    if fetch_ohlcv:
        for ticker in resolved:
            url = YAHOO_CHART_URL_TEMPLATE.format(
                ticker=ticker.lower(), range_=range_, interval=interval
            )
            try:
                body, source = _fetch(client, url)
                bars = parse_yahoo_chart(body, ticker=ticker, source_ref=url)
                if bars:
                    fetched[ticker], sources[ticker] = bars, source
                else:
                    failures[ticker].append("ohlcv_empty")
            except YahooMarketError as exc:
                failures[ticker].append(f"ohlcv:{exc}")

    all_bars = [bar for ticker_bars in fetched.values() for bar in ticker_bars]
    bars_path, prices_path = str(daily_bars_path), str(current_prices_path)
    if all_bars:
        bars_path = save_daily_bars(
            merge_daily_bars(load_daily_bars(daily_bars_path), all_bars), daily_bars_path
        )
        price_facts = latest_price_facts_from_bars(all_bars, source_ref=bars_path)
        stored = load_current_prices(current_prices_path)
        prices_path = save_current_prices(
            merge_market_price_facts(stored.values(), price_facts), current_prices_path
        )

    latest = {ticker: value for ticker, bars in fetched.items()
              if (value := _latest_close(bars)) is not None}
    fundamentals = (
        _fetch_fundamentals(client, resolved, latest, failures)
        if fetch_fundamentals
        else {}
    )
    fundamentals_path_text = str(fundamentals_path)
    if fundamentals:
        merged = load_yahoo_fundamentals(fundamentals_path)
        merged.update(fundamentals)
        fundamentals_path_text = save_yahoo_fundamentals(merged, fundamentals_path)

    errors = {ticker: messages for ticker, messages in failures.items() if messages}
    completed = max(len(fetched), len(fundamentals))
    status = "blocked" if completed == 0 else "partial" if errors else "completed"
    return {
        "status": status, "provider_id": "yahoo_finance", "requested_count": len(resolved),
        "tickers": resolved, "ohlcv_ticker_count": len(fetched), "ohlcv_row_count": len(all_bars),
        "fundamentals_ticker_count": len(fundamentals),
        "latest_bars": [_summary(ticker, bars) for ticker, bars in sorted(fetched.items())],
        "fundamentals": [fundamentals[ticker] for ticker in sorted(fundamentals)],
        "errors": errors, "fetch_sources": sources,
        "saved": {"daily_bars_path": bars_path, "current_prices_path": prices_path,
                  "fundamentals_path": fundamentals_path_text},
        "ohlcv_summary": summarize_daily_bars(all_bars),
        "policy": {"personal_use_only": True, "robots_checked": True, "rate_limited": True,
                   "redistribution": False, "auto_trading": False},
        "auto_trading": False, "call_real_api": True,
    }


def _fetch_fundamentals(
    client: _Fetcher, tickers: Sequence[str], latest: Mapping[str, float],
    failures: dict[str, list[str]],
) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for start in range(0, len(tickers), 40):
        batch = tickers[start:start + 40]
        url = YAHOO_QUOTE_URL_TEMPLATE.format(symbols=",".join(f"{ticker}.T" for ticker in batch))
        try:
            body, _ = _fetch(client, url)
            parsed = parse_yahoo_quote(body)
            for parsed_row in parsed.values():
                parsed_row["source_ref"] = url
            output.update(parsed)
        except YahooMarketError:
            pass
    for ticker in tickers:
        row = output.get(ticker)
        if row is None or not any(key in row for key in ("per", "pbr", "dps", "eps", "market_cap")):
            url = YAHOO_JAPAN_QUOTE_URL_TEMPLATE.format(ticker=ticker)
            try:
                html, _ = _fetch(client, url)
                html_row = parse_yahoo_japan_html(html, ticker=ticker)
                if len(html_row) > 3:
                    row = _merge(row, html_row)
                    output[ticker] = row
                else:
                    failures[ticker].append("fundamentals_empty")
            except YahooMarketError as exc:
                failures[ticker].append(f"fundamentals:{exc}")
        if row is not None:
            if "price" not in row and ticker in latest:
                row["price"] = latest[ticker]
                row["source_ref"] = f"{row.get('source_ref', '')}+chart_close"
            row["as_of"] = datetime.now(UTC).date().isoformat()
    return output


def _fetch(client: _Fetcher, url: str) -> tuple[str, str]:
    document = client.fetch_document(url)
    if not document.allowed_by_robots:
        raise YahooMarketError(document.source or "robots_blocked")
    if document.status_code is not None and document.status_code >= 400:
        raise YahooMarketError(f"http_{document.status_code}")
    if not document.html.strip():
        raise YahooMarketError("empty_response")
    return document.html, document.source


def _merge(current: dict[str, object] | None, incoming: Mapping[str, object]) -> dict[str, object]:
    output = dict(current or {})
    prior = str(output.get("source_ref") or "")
    for key, value in incoming.items():
        if key not in output or output[key] in (None, ""):
            output[key] = value
    source = str(incoming.get("source_ref") or "")
    output["source_ref"] = "+".join(value for value in (prior, source) if value)
    return output


def _summary(ticker: str, bars: Sequence[DailyBarFact]) -> dict[str, object]:
    bar = max(bars, key=lambda item: item.date)
    return {"ticker": ticker, "date": bar.date, "open": bar.open, "high": bar.high,
            "low": bar.low, "close": bar.close, "adjusted_close": bar.adjusted_close,
            "volume": bar.volume, "bar_count": len(bars), "provider_id": bar.provider_id,
            "source_ref": bar.source_ref}


def _latest_close(bars: Sequence[DailyBarFact]) -> float | None:
    for bar in sorted(bars, key=lambda item: item.date, reverse=True):
        value = bar.adjusted_close or bar.close
        if value is not None and value > 0:
            return float(value)
    return None


def _json_dict(text: str) -> dict[str, object]:
    try:
        return _dict(json.loads(text))
    except (TypeError, ValueError):
        return {}


def _dict(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _first_dict(values: Sequence[object]) -> dict[str, object]:
    return _dict(values[0]) if values else {}


def _at(value: object, index: int) -> float | None:
    return _number(value[index]) if isinstance(value, list) and index < len(value) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _clean_html(value: str) -> str:
    value = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    return re.sub(r"\s+", "", unescape(re.sub(r"<[^>]+>", "", value)))


def _dl_value(block: str) -> str:
    match = re.search(r"<dd\b[^>]*>(.*?)</dd>", block, flags=re.DOTALL)
    return _clean_html(match.group(1)) if match else ""


def _first_number(text: str) -> float | None:
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", re.sub(r"\([^)]*\)", "", text))
    return _number(match.group(0)) if match else None


def _extract_price(text: str) -> float | None:
    for pattern in _PRICE_PATTERNS:
        match = re.search(pattern, text)
        if match and (value := _number(match.group(1))) is not None and value > 0:
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


def _csv(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(round(value, 8))
    return str(value)
