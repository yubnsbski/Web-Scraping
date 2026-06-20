"""Deterministic price heat-map from the scraped daily-bars CSV.

Builds an at-a-glance "watch" grid: for each ticker, the latest close and its
day-over-day percentage change (from the two most recent closes in
``daily_bars.csv``). Colouring is left to the UI; this module only computes the
numbers. This is mechanical aggregation of collected data, not investment
advice.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from investment_assistant.portfolio.jp_company_names import builtin_company_name

JsonDict = dict[str, Any]

_TICKER_KEYS = ("ticker", "code")


def build_market_heatmap(
    daily_bars_csv: str | Path,
    *,
    tickers: list[str] | None = None,
    names: dict[str, str] | None = None,
    current_prices: dict[str, float] | None = None,
    sort_by: str = "change",
    limit: int = 0,
) -> JsonDict:
    """Compute per-ticker display price and percentage change.

    When ``current_prices`` has a fresh intraday price for a code, it is shown
    as the price and the change is measured against the latest daily close
    (i.e. today's move). Otherwise the latest daily close is shown and the
    change is the prior day-over-day move. ``tickers`` filters to a watch list
    (bare Tokyo codes); ``names`` maps a code to a display name. ``sort_by`` is
    ``"change"`` / ``"gain"`` / ``"loss"`` / ``"ticker"``; ``limit`` caps cells.
    """

    wanted = {_normalize(t) for t in tickers} if tickers else None
    series: dict[str, list[tuple[str, float]]] = {}
    for row in _read_rows(daily_bars_csv):
        code = _normalize(_ticker_of(row))
        if not code or (wanted is not None and code not in wanted):
            continue
        date = str(row.get("date") or "").strip()
        close = _number(row.get("close"))
        if not date or close is None or close <= 0:
            continue
        series.setdefault(code, []).append((date, close))

    cells: list[JsonDict] = []
    for code, points in series.items():
        points.sort(key=lambda item: item[0])
        last_date, last_daily_close = points[-1]
        prev_daily_close = points[-2][1] if len(points) >= 2 else None
        current = (current_prices or {}).get(code)
        price: float
        reference: float | None
        if current is not None and current > 0:
            # Intraday price available: today's move vs the latest daily close.
            price = current
            reference = last_daily_close
            price_source = "intraday"
        else:
            price = last_daily_close
            reference = prev_daily_close
            price_source = "daily_close"
        change_pct = (
            round((price - reference) / reference * 100.0, 2) if reference else None
        )
        cells.append(
            {
                "ticker": code,
                "name": _display_name(code, names),
                "last_close": round(price, 2),
                "prev_close": round(reference, 2) if reference is not None else None,
                "change_pct": change_pct,
                "price_source": price_source,
                "as_of": last_date,
            }
        )

    cells.sort(key=_sort_key(sort_by))
    if limit and limit > 0:
        cells = cells[:limit]
    as_of = max((str(cell["as_of"]) for cell in cells), default=None)
    return {
        "cells": cells,
        "count": len(cells),
        "as_of": as_of,
        "sort_by": sort_by,
        "auto_trading": False,
        "call_real_api": False,
    }


def _display_name(code: str, names: dict[str, str] | None) -> str:
    """Best display name for a code: a real CSV name, else the built-in, else code.

    A CSV "name" that is just the ticker code (some scraped rows store the code
    when the real name was unavailable) is treated as missing so the built-in
    dictionary can supply the company name instead.
    """

    provided = (names or {}).get(code)
    if provided and provided.strip() and provided.strip() != code:
        return provided
    return builtin_company_name(code) or code


def _sort_key(sort_by: str) -> Any:
    if sort_by == "ticker":
        return lambda cell: (0, str(cell["ticker"]))
    if sort_by == "gain":
        return lambda cell: _present(cell, lambda change: -change)
    if sort_by == "loss":
        return lambda cell: _present(cell, lambda change: change)
    # default "change": largest absolute move first; cells with no change last.
    return lambda cell: _present(cell, lambda change: -abs(change))


def _present(cell: JsonDict, score: Any) -> tuple[int, float]:
    """Sort key that always pushes cells without a % change to the end.

    The leading ``0``/``1`` flag groups present-change cells before missing ones
    regardless of the per-mode score, so a single-bar ticker never floats up.
    """

    value = cell.get("change_pct")
    if isinstance(value, int | float):
        return (0, float(score(float(value))))
    return (1, 0.0)


def _read_rows(path: str | Path) -> list[dict[str, str]]:
    raw = Path(path).read_bytes()
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


def _ticker_of(row: dict[str, str]) -> str:
    for key in _TICKER_KEYS:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize(value: str) -> str:
    text = value.strip().upper()
    return text[:-2] if text.endswith(".T") else text


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None
