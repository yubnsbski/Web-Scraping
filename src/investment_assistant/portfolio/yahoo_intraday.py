"""Yahoo Finance Japan intraday (minute-bar) scraper.

finance.yahoo.co.jp embeds the current day's minute-resolution price series in
its quote page as a ``window.__PRELOADED_STATE__ = {...}`` JSON blob; the series
lives at ``mainItemDetailChartSetting -> timeSeriesData -> histories`` as
``{baseDatetime, closePrice}`` entries. One request yields the whole
09:00-15:30 session for a ticker, parsed with the standard library only.

Caveats: this works for the *current* trading day only — the page resets the
embedded series the next day — and the data is personal-use only (no
redistribution or sale). Fetches go through the robots-respecting, rate-limited
:class:`SafeFetcher`; this is a one-shot post/intra-session pull, not a
real-time polling loop.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass

from investment_assistant.observability import get_logger
from investment_assistant.portfolio._market_common import default_fetch, render_csv

_logger = get_logger("portfolio.yahoo_intraday")

INTRADAY_URL_TEMPLATE = "https://finance.yahoo.co.jp/quote/{ticker}.T?term=1d"
_STATE_MARKER = "__PRELOADED_STATE__"
_TIME_RE = re.compile(r"T([0-2]\d:[0-5]\d)")
_INTRADAY_FIELDS = ("time", "datetime", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class IntradayTick:
    """One intraday sample (minute bar) for a ticker."""

    time: str  # "HH:MM" in the exchange's local time
    datetime: str  # raw baseDatetime as provided by Yahoo
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value else None


def extract_preloaded_state(html: str) -> dict[str, object] | None:
    """Return the ``__PRELOADED_STATE__`` JSON object from a quote page, or None.

    Decodes the first JSON object after the marker with ``raw_decode`` so any
    trailing script source is ignored.
    """

    marker = html.find(_STATE_MARKER)
    if marker == -1:
        return None
    brace = html.find("{", marker)
    if brace == -1:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(html[brace:])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _histories(state: dict[str, object]) -> list[object]:
    node: object = state
    for key in ("mainItemDetailChartSetting", "timeSeriesData", "histories"):
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    return node if isinstance(node, list) else []


def parse_yahoo_intraday(html: str) -> list[IntradayTick]:
    """Parse the embedded minute series into ticks (empty list on malformed input).

    Mirrors the documented technique: walk ``histories`` and keep each entry that
    has a usable ``closePrice``, extracting ``HH:MM`` from its ``baseDatetime``.
    Any open/high/low/volume fields present are carried through.
    """

    state = extract_preloaded_state(html)
    if state is None:
        return []
    ticks: list[IntradayTick] = []
    for item in _histories(state):
        if not isinstance(item, dict):
            continue
        base = str(item.get("baseDatetime") or "")
        match = _TIME_RE.search(base)
        if not match:
            continue
        close = _num(item.get("closePrice"))
        if close is None:
            continue
        volume = _num(item.get("volume"))
        ticks.append(
            IntradayTick(
                time=match.group(1),
                datetime=base,
                open=_num(item.get("openPrice")),
                high=_num(item.get("highPrice")),
                low=_num(item.get("lowPrice")),
                close=close,
                volume=int(volume) if volume is not None else None,
            )
        )
    return ticks


def fetch_yahoo_intraday(
    tickers: Iterable[str],
    *,
    fetch: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Scrape today's minute series for each ticker (no implicit count cap).

    A single failing ticker is recorded in ``notes`` and never aborts the batch.
    """

    fetcher = fetch or default_fetch
    series: dict[str, list[dict[str, object]]] = {}
    counts: dict[str, int] = {}
    notes: dict[str, str] = {}
    for raw in tickers:
        ticker = str(raw).strip()
        if not ticker or ticker in series:
            continue
        url = INTRADAY_URL_TEMPLATE.format(ticker=ticker.lower())
        try:
            ticks = parse_yahoo_intraday(fetcher(url))
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the batch
            _logger.warning("intraday fetch failed ticker=%s error=%s", ticker, type(exc).__name__)
            series[ticker] = []
            counts[ticker] = 0
            notes[ticker] = type(exc).__name__
            continue
        series[ticker] = [asdict(tick) for tick in ticks]
        counts[ticker] = len(ticks)
    return {
        "provider_id": "yahoo_jp_intraday",
        "url_template": INTRADAY_URL_TEMPLATE,
        "intraday": series,
        "counts": counts,
        "notes": notes,
    }


def intraday_csv_text(ticks: Iterable[dict[str, object]]) -> str:
    """Render intraday tick dicts as CSV text with a fixed header."""

    return render_csv(_INTRADAY_FIELDS, ticks)
