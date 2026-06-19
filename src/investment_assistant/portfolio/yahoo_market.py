"""Yahoo! Finance market-data acquisition for the local single-user app.

The module fetches daily OHLCV bars and market fundamentals for Japanese stocks,
normalises them into the existing local CSV stores, and returns a compact result
that can be rendered directly by the frontend. Fetches use the project's
robots-aware, rate-limited, cached ``SafeFetcher``. No trading or redistribution
behaviour is provided.
"""

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
from typing import Any

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
YAHOO_QUOTE_URL_TEMPLATE = (
    "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
)
YAHOO_JAPAN_QUOTE_URL_TEMPLATE = "https://finance.yahoo.co.jp/quote/{ticker}.T"
DEFAULT_YAHOO_FUNDAMENTALS_CSV = Path("local_docs/market/yahoo_financials.csv")

ALLOWED_RANGES = frozenset({"5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"})
ALLOWED_INTERVALS = frozenset({"1d", "1wk", "1mo"})
FUNDAMENTAL_COLUMNS: tuple[str, ...] = (
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
_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("regularMarketPrice", "price"),
    ("trailingPE", "per"),
    ("priceToBook", "pbr"),
    ("trailingAnnualDividendRate", "dps"),
    ("trailingAnnualDividendYield", "dividend_yield"),
    ("epsTrailingTwelveMonths", "eps"),
    ("marketCap", "market_cap"),
)
_HTML_METRIC_LABELS: tuple[tuple[str, str], ...] = (
    ("PER", "per"),
    ("PBR", "pbr"),
    ("1株配当", "dps"),
    ("EPS", "eps"),
)


class YahooMarketError(RuntimeError):
    """Raised when a Yahoo request cannot provide usable market data."""


def normalize_tickers(tickers: Iterable[object]) -> list[str]:
    """Return de-duplicated Japanese security codes with an optional ``.T`` removed."""

    resolved: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        if ticker.endswith(".T"):
            ticker = ticker[:-2]
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        resolved.append(ticker)
    return resolved


def parse_yahoo_chart(json_text: str, *, ticker: str, source_ref: str) -> list[DailyBarFact]:
    """Parse Yahoo v8 chart JSON into local ``DailyBarFact`` rows."""

    try:
        result = json.loads(json_text)["chart"]["result"][0]
    except (ValueError, KeyError, TypeError, IndexError):
        return []
    if not isinstance(result, dict):
        return []
    timestamps = result.get("timestamp")
    if not isinstance(timestamps, list):
        return []
    try:
        quote = result["indicators"]["quote"][0]
    except (KeyError, TypeError, IndexError):
        return []
    if not isinstance(quote, dict):
        return []
    indicators = result.get("indicators")
    adjclose: object = None
    if isinstance(indicators, dict):
        raw_adj = indicators.get("adjclose")
        if isinstance(raw_adj, list) and raw_adj and isinstance(raw_adj[0], dict):
            adjclose = raw_adj[0].get("adjclose")
    meta = result.get("meta")
    raw_offset = meta.get("gmtoffset") if isinstance(meta, dict) else 0
    gmtoffset = int(raw_offset) if isinstance(raw_offset, int | float) else 0

    bars: list[DailyBarFact] = []
    for index, timestamp in enumerate(timestamps):
        if not isinstance(timestamp, int | float):
            continue
        open_value = _sequence_number(quote.get("open"), index)
        high_value = _sequence_number(quote.get("high"), index)
        low_value = _sequence_number(quote.get("low"), index)
        close_value = _sequence_number(quote.get("close"), index)
        volume_value = _sequence_number(quote.get("volume"), index)
        adjusted_close = _sequence_number(adjclose, index)
        if all(value is None for value in (open_value, high_value, low_value, close_value)):
            continue
        date = datetime.fromtimestamp(int(timestamp) + gmtoffset, tz=UTC).date().isoformat()
        bars.append(
            DailyBarFact(
                ticker=ticker,
                date=date,
                open=open_value,
                high=high_value,
                low=low_value,
                close=close_value,
                volume=volume_value,
                adjusted_close=adjusted_close,
                provider_id="yahoo_finance",
                source_ref=source_ref,
            )
        )
    return bars


def parse_yahoo_quote(json_text: str) -> dict[str, dict[str, object]]:
    """Parse Yahoo quote JSON into ``ticker -> market fundamental metrics``."""

    try:
        results = json.loads(json_text)["quoteResponse"]["result"]
    except (ValueError, KeyError, TypeError):
        return {}
    if not isinstance(results, list):
        return {}
    out: dict[str, dict[str, object]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("symbol") or "").strip().upper()
        if ticker.endswith(".T"):
            ticker = ticker[:-2]
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
        for source_key, target_key in _FIELD_MAP:
            value = _optional_number(item.get(source_key))
            if value is not None:
                row[target_key] = value
        yield_value = _optional_number(row.get("dividend_yield"))
        if yield_value is not None:
            row["dividend_yield_percent"] = yield_value * 100.0
        out[ticker] = row
    return out


def parse_yahoo_japan_html(html_text: str, *, ticker: str) -> dict[str, object]:
    """Parse the stable labels exposed in Yahoo!ファイナンス Japan quote HTML."""

    full_text = _clean_html_text(html_text)
    row: dict[str, object] = {
        "ticker": ticker,
        "provider_id": "yahoo_finance",
        "source_ref": YAHOO_JAPAN_QUOTE_URL_TEMPLATE.format(ticker=ticker),
    }
    title_match = re.search(r"<title>(.*?)【", html_text, flags=re.DOTALL)
    if title_match:
        name = _clean_html_text(title_match.group(1))
        if name:
            row["name"] = name
    price = _extract_price(full_text)
    if price is not None:
        row["price"] = price
    for block in re.findall(r"<dl\b[^>]*>.*?</dl>", html_text, flags=re.DOTALL):
        text = _clean_html_text(block)
        value_text = _dl_value_text(block) or text
        for label, key in _HTML_METRIC_LABELS:
            if text.startswith(label):
                value = _first_number(value_text)
                if value is not None and _valid_metric(key, value):
                    row[key] = value
        if text.startswith("配当利回り"):
            value = _first_number(value_text)
            if value is not None:
                row["dividend_yield_percent"] = value
                row["dividend_yield"] = value / 100.0
        if text.startswith("時価総額"):
            value = _first_number(value_text)
            if value is not None:
                row["market_cap"] = _scale_market_cap(value, text)
    return row


def load_yahoo_fundamentals(
    path: str | Path = DEFAULT_YAHOO_FUNDAMENTALS_CSV,
) -> dict[str, dict[str, object]]:
    csv_path = Path(path)
    if not csv_path.is_file():
        return {}
    rows: dict[str, dict[str, object]] = {}
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            ticker = str(raw.get("ticker") or "").strip()
            if not ticker:
                continue
            row: dict[str, object] = {"ticker": ticker}
            for key, value in raw.items():
                if key is None or value is None or key == "ticker" or not value.strip():
                    continue
                row[key] = _optional_number(value) if key in _NUMERIC_FUNDAMENTAL_FIELDS else value
            rows[ticker] = row
    return rows


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
        row = rows[ticker]
        writer.writerow(
            {
                column: _csv_value(ticker if column == "ticker" else row.get(column))
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
    fetcher: Any | None = None,
) -> dict[str, object]:
    """Fetch, merge and persist Yahoo market data for the requested tickers."""

    resolved = normalize_tickers(tickers)
    if not resolved:
        raise ValueError("at least one ticker is required")
    if range_ not in ALLOWED_RANGES:
        raise ValueError(f"unsupported range: {range_}")
    if interval not in ALLOWED_INTERVALS:
        raise ValueError(f"unsupported interval: {interval}")
    if not fetch_ohlcv and not fetch_fundamentals:
        raise ValueError("enable fetch_ohlcv and/or fetch_fundamentals")

    market_fetcher = fetcher or SafeFetcher(timeout_seconds=20.0)
    errors: dict[str, list[str]] = {ticker: [] for ticker in resolved}
    fetched_bars: dict[str, list[DailyBarFact]] = {}
    source_modes: dict[str, str] = {}

    if fetch_ohlcv:
        for ticker in resolved:
            url = YAHOO_CHART_URL_TEMPLATE.format(
                ticker=ticker.lower(),
                range_=range_,
                interval=interval,
            )
            try:
                text, source = _fetch_text(market_fetcher, url)
                bars = parse_yahoo_chart(text, ticker=ticker, source_ref=url)
                if not bars:
                    errors[ticker].append("ohlcv_empty")
                    continue
                fetched_bars[ticker] = bars
                source_modes[ticker] = source
            except YahooMarketError as exc:
                errors[ticker].append(f"ohlcv:{exc}")

    incoming_bars = [bar for rows in fetched_bars.values() for bar in rows]
    saved_daily_bars_path: str | None = None
    saved_current_prices_path: str | None = None
    if incoming_bars:
        existing_bars = load_daily_bars(daily_bars_path)
        merged_bars = merge_daily_bars(existing_bars, incoming_bars)
        saved_daily_bars_path = save_daily_bars(merged_bars, daily_bars_path)
        new_price_facts = latest_price_facts_from_bars(
            incoming_bars,
            source_ref=str(saved_daily_bars_path),
        )
        current_prices = load_current_prices(current_prices_path)
        merged_prices = merge_market_price_facts(current_prices.values(), new_price_facts)
        saved_current_prices_path = save_current_prices(merged_prices, current_prices_path)

    latest_close: dict[str, float] = {}
    for ticker, rows in fetched_bars.items():
        close = _latest_close(rows)
        if close is not None:
            latest_close[ticker] = close

    fundamentals: dict[str, dict[str, object]] = {}
    if fetch_fundamentals:
        for batch in _chunks(resolved, 40):
            quote_url = YAHOO_QUOTE_URL_TEMPLATE.format(
                symbols=",".join(f"{ticker}.T" for ticker in batch)
            )
            try:
                quote_text, _ = _fetch_text(market_fetcher, quote_url)
                parsed = parse_yahoo_quote(quote_text)
                for row in parsed.values():
                    row["source_ref"] = quote_url
                fundamentals.update(parsed)
            except YahooMarketError:
                continue

        for ticker in resolved:
            row = fundamentals.get(ticker)
            needs_html = row is None or not any(
                key in row
                for key in ("per", "pbr", "dps", "dividend_yield", "eps", "market_cap")
            )
            if needs_html:
                html_url = YAHOO_JAPAN_QUOTE_URL_TEMPLATE.format(ticker=ticker)
                try:
                    html, _ = _fetch_text(market_fetcher, html_url)
                    html_row = parse_yahoo_japan_html(html, ticker=ticker)
                    if len(html_row) > 3:
                        if row is None:
                            row = html_row
                        else:
                            quote_source = str(row.get("source_ref") or "")
                            row.update(
                                {
                                    key: value
                                    for key, value in html_row.items()
                                    if key not in row or row.get(key) in (None, "")
                                }
                            )
                            row["source_ref"] = "+".join(
                                item
                                for item in (quote_source, html_url)
                                if item
                            )
                        fundamentals[ticker] = row
                    else:
                        errors[ticker].append("fundamentals_empty")
                except YahooMarketError as exc:
                    errors[ticker].append(f"fundamentals:{exc}")
            if row is not None:
                if "price" not in row and latest_close.get(ticker) is not None:
                    row["price"] = latest_close[ticker]
                    row["source_ref"] = f"{row.get('source_ref', '')}+chart_close"
                row["as_of"] = datetime.now(UTC).date().isoformat()

    saved_fundamentals_path: str | None = None
    if fundamentals:
        existing_fundamentals = load_yahoo_fundamentals(fundamentals_path)
        existing_fundamentals.update(fundamentals)
        saved_fundamentals_path = save_yahoo_fundamentals(
            existing_fundamentals,
            fundamentals_path,
        )

    latest_bars = [_bar_summary(ticker, rows) for ticker, rows in sorted(fetched_bars.items())]
    errors = {ticker: messages for ticker, messages in errors.items() if messages}
    ohlcv_count = len(fetched_bars)
    fundamental_count = len(fundamentals)
    successful = max(ohlcv_count, fundamental_count)
    status = "completed" if successful == len(resolved) and not errors else "partial"
    if successful == 0:
        status = "blocked"

    return {
        "status": status,
        "provider_id": "yahoo_finance",
        "requested_count": len(resolved),
        "tickers": resolved,
        "ohlcv_ticker_count": ohlcv_count,
        "ohlcv_row_count": len(incoming_bars),
        "fundamentals_ticker_count": fundamental_count,
        "latest_bars": latest_bars,
        "fundamentals": [fundamentals[ticker] for ticker in sorted(fundamentals)],
        "errors": errors,
        "fetch_sources": source_modes,
        "saved": {
            "daily_bars_path": saved_daily_bars_path or str(daily_bars_path),
            "current_prices_path": saved_current_prices_path or str(current_prices_path),
            "fundamentals_path": saved_fundamentals_path or str(fundamentals_path),
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


def _fetch_text(fetcher: Any, url: str) -> tuple[str, str]:
    document = fetcher.fetch_document(url)
    if not bool(getattr(document, "allowed_by_robots", False)):
        raise YahooMarketError(str(getattr(document, "source", "robots_blocked")))
    status_code = getattr(document, "status_code", None)
    if isinstance(status_code, int) and status_code >= 400:
        raise YahooMarketError(f"http_{status_code}")
    text = str(getattr(document, "html", "") or "")
    if not text.strip():
        raise YahooMarketError("empty_response")
    return text, str(getattr(document, "source", "network"))


def _bar_summary(ticker: str, rows: Sequence[DailyBarFact]) -> dict[str, object]:
    latest = max(rows, key=lambda row: row.date)
    return {
        "ticker": ticker,
        "date": latest.date,
        "open": latest.open,
        "high": latest.high,
        "low": latest.low,
        "close": latest.close,
        "adjusted_close": latest.adjusted_close,
        "volume": latest.volume,
        "bar_count": len(rows),
        "provider_id": latest.provider_id,
        "source_ref": latest.source_ref,
    }


def _latest_close(rows: Sequence[DailyBarFact]) -> float | None:
    for row in sorted(rows, key=lambda item: item.date, reverse=True):
        value = row.adjusted_close or row.close
        if value is not None and value > 0:
            return value
    return None


def _sequence_number(values: object, index: int) -> float | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    return _optional_number(values[index])


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none", "null", "-", "---"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _clean_html_text(value: str) -> str:
    without_comments = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", "", without_comments)
    return re.sub(r"\s+", "", unescape(without_tags))


def _dl_value_text(block: str) -> str:
    match = re.search(r"<dd\b[^>]*>(.*?)</dd>", block, flags=re.DOTALL)
    return _clean_html_text(match.group(1)) if match else ""


def _first_number(text: str) -> float | None:
    without_parentheses = re.sub(r"\([^)]*\)", "", text)
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", without_parentheses)
    return _optional_number(match.group(0)) if match else None


_PRICE_PATTERNS: tuple[str, ...] = (
    r"ポートフォリオに追加([0-9][0-9,]*(?:\.\d+)?)前日比",
    r"([0-9][0-9,]*(?:\.\d+)?)前日比",
    r"現在値([0-9][0-9,]*(?:\.\d+)?)",
)
_NUMERIC_FUNDAMENTAL_FIELDS = {
    "price",
    "per",
    "pbr",
    "dps",
    "dividend_yield",
    "dividend_yield_percent",
    "eps",
    "market_cap",
}


def _extract_price(text: str) -> float | None:
    for pattern in _PRICE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            value = _optional_number(match.group(1))
            if value is not None and value > 0:
                return value
    return None


def _valid_metric(key: str, value: float) -> bool:
    return value > 0 if key in {"per", "pbr", "eps"} else True


def _scale_market_cap(value: float, text: str) -> float:
    if "百万円" in text:
        return value * 1_000_000
    if "億円" in text:
        return value * 100_000_000
    if "兆円" in text:
        return value * 1_000_000_000_000
    return value


def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
    width = max(size, 1)
    return [list(values[index : index + width]) for index in range(0, len(values), width)]


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else str(round(value, 8))
    return str(value)
