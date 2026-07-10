"""Universe selection: daily bars, JPX sector map, and the tradable universe.

Reads the two local, already-fetched CSVs the paper-trading simulation is
allowed to depend on (see ``docs/papertrade-design.md``): ``daily_bars.csv``
(OHLCV) and the JPX listed-issues master (``data_j_converted.csv``, 33業種
sector classification). Both are read read-only here -- this module never
writes them, and the actual data-acquisition pipelines for these files
belong to the parallel session's ``webapi/data_*`` / ``scripts/*`` code,
which this package does not touch.

No per-ticker weighting exists anywhere in this package (owner requirement,
see design doc "オーナー要件" #3) -- the only ticker-shaped output here is
the *set* of eligible tickers (:func:`build_universe`), and the only per-name
signal exposed is the coarse 33業種 sector, used solely for defensive/
cyclical bucketing in later sprints' strategy layer.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# A 内国株式 (domestic common stock) segment always carries this marker in the
# JPX file (プライム/スタンダード/グロース（内国株式）), which excludes
# ETF・ETN, REIT, 出資証券, PRO Market, and 外国株式 rows.
_DOMESTIC_MARKER = "内国株式"

# 33業種区分 names treated as defensive per the design doc's owner requirement
# #3 (sector characteristics are allowed, per-ticker weighting is not).
DEFENSIVE_SECTORS: frozenset[str] = frozenset(
    {"電気・ガス業", "情報・通信業", "食料品", "医薬品", "陸運業"}
)


@dataclass(frozen=True)
class Bar:
    """One daily OHLCV bar for a ticker."""

    ticker: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class SectorInfo:
    """JPX master row for one domestic-equity ticker."""

    ticker: str
    name: str
    sector33: str
    market: str


def is_defensive(sector33: str) -> bool:
    """Whether a 33業種区分 name is classified as defensive."""

    return sector33 in DEFENSIVE_SECTORS


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_daily_bars(path: str | Path) -> dict[str, list[Bar]]:
    """Read ``daily_bars.csv`` into ``{ticker: [Bar, ...]}``, sorted by date.

    Rows with a missing or non-positive close are skipped (the design doc's
    v1 rule -- such rows are unusable for either fills or universe history
    counts). Rows where open/high/low/volume fail to parse are also skipped
    defensively, since a Bar with a garbage OHLC would silently corrupt
    fill-price and history calculations downstream.
    """

    bars: dict[str, list[Bar]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ticker = (row.get("ticker") or "").strip()
            date = (row.get("date") or "").strip()
            if not ticker or not date:
                continue
            close = _parse_float(row.get("close"))
            if close is None or close <= 0:
                continue
            open_ = _parse_float(row.get("open"))
            high = _parse_float(row.get("high"))
            low = _parse_float(row.get("low"))
            volume = _parse_float(row.get("volume"))
            if open_ is None or high is None or low is None or volume is None:
                continue
            bars.setdefault(ticker, []).append(
                Bar(
                    ticker=ticker,
                    date=date,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=int(volume),
                )
            )
    return {ticker: sorted(rows, key=lambda bar: bar.date) for ticker, rows in bars.items()}


def load_sector_map(path: str | Path) -> dict[str, SectorInfo]:
    """Read the JPX master CSV into ``{ticker: SectorInfo}``.

    Keeps only rows whose 市場・商品区分 contains ``内国株式`` (domestic
    common stock listed on プライム/スタンダード/グロース) -- ETFs, REITs,
    and foreign issues are excluded, matching the design doc's universe
    definition.
    """

    sectors: dict[str, SectorInfo] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            market = (row.get("市場・商品区分") or "").strip()
            if _DOMESTIC_MARKER not in market:
                continue
            ticker = (row.get("コード") or "").strip()
            if not ticker:
                continue
            sectors[ticker] = SectorInfo(
                ticker=ticker,
                name=(row.get("銘柄名") or "").strip(),
                sector33=(row.get("33業種区分") or "").strip(),
                market=market,
            )
    return sectors


def build_universe(
    bars: Mapping[str, Sequence[Bar]],
    sectors: Mapping[str, SectorInfo],
    *,
    min_history: int,
    as_of: str,
) -> list[str]:
    """Tickers present in both ``bars`` and ``sectors`` with enough history.

    "Enough history" means at least ``min_history`` bars strictly before
    ``as_of`` (no look-ahead: only data available before the decision date
    counts). ``TradingCalendar.windows(warmup=...)`` counts the decision date
    inclusively, so the P2 engine must pass ``as_of=first_trade_date`` when
    checking cycle-entry history, or add one to ``min_history`` if it passes
    the decision date instead. Returned sorted for determinism -- selection
    here is a pure filter, never a ranking, so there is no ordering signal to
    preserve.
    """

    universe: list[str] = []
    for ticker, ticker_bars in bars.items():
        if ticker not in sectors:
            continue
        history_count = sum(1 for bar in ticker_bars if bar.date < as_of)
        if history_count >= min_history:
            universe.append(ticker)
    return sorted(universe)
