"""Local market price snapshot store.

The app fetches prices on demand from an allowed provider, but the UI should not
go blank after a reload or a temporary provider failure. This module keeps the
latest locally observed prices in a small CSV file. It is an audit helper only:
it does not redistribute market data or make trading decisions.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

MARKET_PRICE_COLUMNS: tuple[str, ...] = (
    "ticker",
    "price",
    "as_of",
    "provider_id",
    "source_ref",
    "note",
)

DEFAULT_CURRENT_PRICES_CSV = Path("local_docs/market/current_prices.csv")
DEFAULT_YAHOO_PRICE_INBOX_CSV = Path("local_docs/market/yahoo_prices_inbox.csv")


@dataclass(frozen=True)
class MarketPriceFact:
    ticker: str
    price: float
    as_of: str = ""
    provider_id: str = "user_csv"
    source_ref: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value not in ("", None)}


def load_current_prices(
    path: str | Path | None = DEFAULT_CURRENT_PRICES_CSV,
) -> dict[str, MarketPriceFact]:
    """Load the local current price overlay keyed by ticker."""

    if path is None:
        return {}
    csv_path = Path(path)
    if not csv_path.is_file():
        return {}
    return parse_current_prices_csv(csv_path.read_text(encoding="utf-8-sig"))


def parse_current_prices_csv(text: str) -> dict[str, MarketPriceFact]:
    facts: dict[str, MarketPriceFact] = {}
    for row in _dict_rows(text):
        fact = market_price_fact_from_row(row)
        if fact is not None:
            facts[fact.ticker] = fact
    return facts


def market_price_fact_from_row(row: Mapping[str, object]) -> MarketPriceFact | None:
    ticker = normalize_ticker(
        row.get("ticker")
        or row.get("code")
        or row.get("security_code")
        or row.get("symbol")
        or row.get("Symbol")
        or row.get("銘柄コード")
        or row.get("コード")
    )
    price = _positive_float(
        row.get("price")
        or row.get("current_price")
        or row.get("regularMarketPrice")
        or row.get("Regular Market Price")
        or row.get("last_price")
        or row.get("Last Price")
        or row.get("close")
        or row.get("Close")
        or row.get("現在値")
        or row.get("終値")
    )
    if not ticker or price is None:
        return None
    return MarketPriceFact(
        ticker=ticker,
        price=price,
        as_of=_text(
            row.get("as_of")
            or row.get("date")
            or row.get("Date")
            or row.get("price_as_of")
            or row.get("timestamp")
        ),
        provider_id=_text(row.get("provider_id") or row.get("provider")) or "user_csv",
        source_ref=_text(row.get("source_ref") or row.get("source") or row.get("url")),
        note=_text(row.get("note")),
    )


def merge_market_price_facts(
    existing: Iterable[MarketPriceFact],
    incoming: Iterable[MarketPriceFact],
) -> list[MarketPriceFact]:
    facts = {fact.ticker: fact for fact in existing}
    facts.update({fact.ticker: fact for fact in incoming})
    return [facts[ticker] for ticker in sorted(facts)]


def current_prices_to_csv_text(facts: Sequence[MarketPriceFact]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(MARKET_PRICE_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for fact in facts:
        writer.writerow(
            {
                "ticker": fact.ticker,
                "price": _format_number(fact.price),
                "as_of": fact.as_of,
                "provider_id": fact.provider_id,
                "source_ref": fact.source_ref,
                "note": fact.note,
            }
        )
    return output.getvalue()


def save_current_prices(
    facts: Sequence[MarketPriceFact],
    path: str | Path = DEFAULT_CURRENT_PRICES_CSV,
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(current_prices_to_csv_text(facts), encoding="utf-8")
    return str(target)


def facts_from_price_response(
    tickers: Iterable[str],
    *,
    prices: Mapping[str, object],
    as_of: Mapping[str, object] | None = None,
    provider_id: str = "unknown",
    source_ref: str = "",
    notes: Mapping[str, object] | None = None,
) -> list[MarketPriceFact]:
    """Build storable facts from a provider response."""

    facts: list[MarketPriceFact] = []
    seen: set[str] = set()
    for raw in tickers:
        ticker = normalize_ticker(raw)
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        price = _positive_float(prices.get(ticker))
        if price is None:
            continue
        facts.append(
            MarketPriceFact(
                ticker=ticker,
                price=price,
                as_of=_text((as_of or {}).get(ticker)),
                provider_id=provider_id,
                source_ref=source_ref,
                note=_text((notes or {}).get(ticker)),
            )
        )
    return facts


def normalize_ticker(value: object) -> str:
    text = str(value or "").strip().upper()
    if text.endswith(".T"):
        return text[:-2]
    return text


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def _text(value: object) -> str:
    return str(value or "").strip()


def _format_number(value: float) -> str:
    return str(int(value)) if value == int(value) else str(round(value, 6))


def _dict_rows(text: str) -> list[dict[str, str]]:
    cleaned = text.strip()
    if not cleaned:
        return []
    sample = cleaned[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    return list(csv.DictReader(io.StringIO(cleaned), dialect=dialect))
