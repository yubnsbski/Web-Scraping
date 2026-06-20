"""Detect which watch-list tickers are missing market data.

Compares a requested ticker list against the scraped ``yahoo_financials.csv``
(price) and ``daily_bars.csv`` (>=2 closes are needed for a day-over-day
change), so the UI can show "what's missing" and backfill only the gaps. This
is a read-only inventory check, not investment advice.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

# A heat-map cell needs the two most recent closes to show a day-over-day move.
_MIN_BARS_FOR_CHANGE = 2


def find_market_gaps(
    tickers: list[str],
    *,
    daily_bars_csv: str | Path,
    financials_csv: str | Path,
) -> JsonDict:
    """Report which ``tickers`` lack a price and/or enough daily bars."""

    wanted = _dedupe(_normalize(t) for t in tickers if str(t).strip())
    priced = _tickers_with_price(financials_csv)
    bar_counts = _bar_counts(daily_bars_csv)

    missing_price = [t for t in wanted if t not in priced]
    missing_bars = [t for t in wanted if bar_counts.get(t, 0) < _MIN_BARS_FOR_CHANGE]
    missing_any = _dedupe([*missing_price, *missing_bars])
    complete = [t for t in wanted if t not in missing_price and t not in missing_bars]
    return {
        "requested": wanted,
        "missing_price": missing_price,
        "missing_bars": missing_bars,
        "missing_any": missing_any,
        "complete": complete,
        "counts": {
            "requested": len(wanted),
            "missing_price": len(missing_price),
            "missing_bars": len(missing_bars),
            "missing_any": len(missing_any),
            "complete": len(complete),
        },
        "auto_trading": False,
        "call_real_api": False,
    }


def _tickers_with_price(financials_csv: str | Path) -> set[str]:
    out: set[str] = set()
    for row in _read_rows(financials_csv):
        ticker = _normalize(str(row.get("ticker") or row.get("code") or ""))
        price = str(row.get("price") or "").strip()
        if ticker and price:
            out.add(ticker)
    return out


def _bar_counts(daily_bars_csv: str | Path) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in _read_rows(daily_bars_csv):
        ticker = _normalize(str(row.get("ticker") or row.get("code") or ""))
        close = str(row.get("close") or "").strip()
        if ticker and close:
            counts[ticker] += 1
    return dict(counts)


def _read_rows(path: str | Path) -> list[dict[str, str]]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    raw = file_path.read_bytes()
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿"), newline=""))
    return [dict(row) for row in reader]


def _normalize(value: str) -> str:
    text = value.strip().upper()
    return text[:-2] if text.endswith(".T") else text


def _dedupe(values: Any) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return list(seen)
