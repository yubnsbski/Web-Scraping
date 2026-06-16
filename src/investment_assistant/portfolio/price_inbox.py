"""File-drop inbox for manually exported market prices (no scraping).

A safe alternative to live scraping (and its 429 risk): the operator exports a
personal-use CSV from Yahoo!ファイナンス etc. and drops it at the inbox path; the
app — and the daily scheduled check — import it from there.

The parser is intentionally forgiving about headers (English or Japanese, with
or without a BOM) and reads the latest close per ticker. No network I/O.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

DEFAULT_INBOX_PATH = Path("local_docs/market/yahoo_prices_inbox.csv")

# Header aliases (lower-cased) for the ticker and close/price columns.
_TICKER_KEYS = ("ticker", "symbol", "code", "コード", "銘柄", "銘柄コード")
_PRICE_KEYS = ("close", "adj close", "終値", "price", "株価", "現在値")


def _pick(header: list[str], keys: tuple[str, ...]) -> int | None:
    lowered = [cell.strip().lower() for cell in header]
    for key in keys:
        if key in lowered:
            return lowered.index(key)
    return None


def _to_price(value: str) -> float | None:
    text = value.strip().replace(",", "")
    if not text:
        return None
    try:
        price = float(text)
    except ValueError:
        return None
    return price if price > 0 else None


def parse_price_inbox(text: str) -> dict[str, float]:
    """Parse inbox CSV text into ``{ticker: latest_close}`` (later rows win)."""

    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        return {}
    header = rows[0]
    ticker_idx = _pick(header, _TICKER_KEYS)
    price_idx = _pick(header, _PRICE_KEYS)
    if ticker_idx is None or price_idx is None:
        return {}
    prices: dict[str, float] = {}
    for row in rows[1:]:
        if ticker_idx >= len(row) or price_idx >= len(row):
            continue
        ticker = row[ticker_idx].strip()
        price = _to_price(row[price_idx])
        if ticker and price is not None:
            prices[ticker] = price  # later row (more recent) overrides
    return prices


def read_price_inbox(path: str | Path = DEFAULT_INBOX_PATH) -> dict[str, float]:
    """Read and parse the inbox CSV, or ``{}`` if it is missing/empty."""

    file = Path(path)
    if not file.is_file():
        return {}
    return parse_price_inbox(file.read_text(encoding="utf-8", errors="replace"))


def inbox_status(path: str | Path = DEFAULT_INBOX_PATH) -> dict[str, object]:
    """Report whether the inbox file is present and how many tickers it yields."""

    file = Path(path)
    if not file.is_file():
        return {"path": str(file), "status": "missing", "tickers": 0, "prices": {}}
    prices = read_price_inbox(file)
    return {
        "path": str(file),
        "status": "present",
        "tickers": len(prices),
        "prices": prices,
    }
