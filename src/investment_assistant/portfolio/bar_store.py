"""Local OHLCV snapshot store for daily market bars.

Daily bars are useful for deterministic analysis such as volatility, recent
range, liquidity checks, and price freshness. They are not trading signals by
themselves, and this module deliberately stores only a small normalized local
snapshot for the single-user app.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from investment_assistant.portfolio.price_store import MarketPriceFact

DAILY_BAR_COLUMNS: tuple[str, ...] = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
    "adjustment_factor",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "adjusted_volume",
    "upper_limit_hit",
    "lower_limit_hit",
    "provider_id",
    "source_ref",
)

DEFAULT_DAILY_BARS_CSV = Path("local_docs/market/daily_bars.csv")


@dataclass(frozen=True)
class DailyBarFact:
    ticker: str
    date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    trading_value: float | None = None
    adjustment_factor: float | None = None
    adjusted_open: float | None = None
    adjusted_high: float | None = None
    adjusted_low: float | None = None
    adjusted_close: float | None = None
    adjusted_volume: float | None = None
    upper_limit_hit: str = ""
    lower_limit_hit: str = ""
    provider_id: str = "user_csv"
    source_ref: str = ""

    def to_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value not in ("", None)}


def load_daily_bars(path: str | Path | None = DEFAULT_DAILY_BARS_CSV) -> list[DailyBarFact]:
    if path is None:
        return []
    csv_path = Path(path)
    if not csv_path.is_file():
        return []
    return parse_daily_bars_csv(csv_path.read_text(encoding="utf-8-sig"))


def parse_daily_bars_csv(text: str) -> list[DailyBarFact]:
    reader = csv.DictReader(io.StringIO(text))
    facts: list[DailyBarFact] = []
    for row in reader:
        fact = daily_bar_fact_from_row(row)
        if fact is not None:
            facts.append(fact)
    return facts


def daily_bar_fact_from_row(row: Mapping[str, object]) -> DailyBarFact | None:
    ticker = _text(row.get("ticker") or row.get("code") or row.get("security_code"))
    date = _text(row.get("date") or row.get("Date"))
    if not ticker or not date:
        return None
    return DailyBarFact(
        ticker=ticker,
        date=date,
        open=_optional_float(row.get("open") or row.get("O")),
        high=_optional_float(row.get("high") or row.get("H")),
        low=_optional_float(row.get("low") or row.get("L")),
        close=_optional_float(row.get("close") or row.get("C")),
        volume=_optional_float(row.get("volume") or row.get("Vo")),
        trading_value=_optional_float(row.get("trading_value") or row.get("Va")),
        adjustment_factor=_optional_float(row.get("adjustment_factor") or row.get("AdjFactor")),
        adjusted_open=_optional_float(row.get("adjusted_open") or row.get("AdjO")),
        adjusted_high=_optional_float(row.get("adjusted_high") or row.get("AdjH")),
        adjusted_low=_optional_float(row.get("adjusted_low") or row.get("AdjL")),
        adjusted_close=_optional_float(row.get("adjusted_close") or row.get("AdjC")),
        adjusted_volume=_optional_float(row.get("adjusted_volume") or row.get("AdjVo")),
        upper_limit_hit=_text(row.get("upper_limit_hit") or row.get("UL")),
        lower_limit_hit=_text(row.get("lower_limit_hit") or row.get("LL")),
        provider_id=_text(row.get("provider_id") or row.get("provider")) or "user_csv",
        source_ref=_text(row.get("source_ref") or row.get("source") or row.get("url")),
    )


def daily_bar_from_jquants_row(
    row: Mapping[str, Any],
    *,
    fallback_ticker: str,
    provider_id: str = "jquants",
    source_ref: str = "https://api.jquants.com/v2/equities/bars/daily",
) -> DailyBarFact | None:
    ticker = _text(row.get("Code") or row.get("code") or fallback_ticker)
    date = _text(row.get("Date") or row.get("date"))
    if not ticker or not date:
        return None
    return DailyBarFact(
        ticker=visible_ticker(ticker),
        date=date,
        open=_optional_float(row.get("O") or row.get("Open") or row.get("open")),
        high=_optional_float(row.get("H") or row.get("High") or row.get("high")),
        low=_optional_float(row.get("L") or row.get("Low") or row.get("low")),
        close=_optional_float(row.get("C") or row.get("Close") or row.get("close")),
        volume=_optional_float(row.get("Vo") or row.get("Volume") or row.get("volume")),
        trading_value=_optional_float(row.get("Va") or row.get("TradingValue")),
        adjustment_factor=_optional_float(row.get("AdjFactor") or row.get("AdjustmentFactor")),
        adjusted_open=_optional_float(row.get("AdjO") or row.get("AdjustmentOpen")),
        adjusted_high=_optional_float(row.get("AdjH") or row.get("AdjustmentHigh")),
        adjusted_low=_optional_float(row.get("AdjL") or row.get("AdjustmentLow")),
        adjusted_close=_optional_float(row.get("AdjC") or row.get("AdjustmentClose")),
        adjusted_volume=_optional_float(row.get("AdjVo") or row.get("AdjustmentVolume")),
        upper_limit_hit=_text(row.get("UL")),
        lower_limit_hit=_text(row.get("LL")),
        provider_id=provider_id,
        source_ref=source_ref,
    )


def merge_daily_bars(
    existing: Iterable[DailyBarFact],
    incoming: Iterable[DailyBarFact],
) -> list[DailyBarFact]:
    facts = {(fact.ticker, fact.date): fact for fact in existing}
    facts.update({(fact.ticker, fact.date): fact for fact in incoming})
    return [facts[key] for key in sorted(facts)]


def filter_daily_bars(
    facts: Iterable[DailyBarFact],
    *,
    tickers: Iterable[str],
    limit_per_ticker: int,
) -> list[DailyBarFact]:
    wanted = {visible_ticker(ticker) for ticker in tickers if str(ticker or "").strip()}
    grouped: dict[str, list[DailyBarFact]] = {}
    for fact in facts:
        if wanted and fact.ticker not in wanted:
            continue
        grouped.setdefault(fact.ticker, []).append(fact)
    out: list[DailyBarFact] = []
    for ticker in sorted(grouped):
        rows = sorted(grouped[ticker], key=lambda fact: fact.date)[-max(limit_per_ticker, 1) :]
        out.extend(rows)
    return out


def daily_bars_to_csv_text(facts: Sequence[DailyBarFact]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(DAILY_BAR_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for fact in facts:
        writer.writerow({column: _csv_value(getattr(fact, column)) for column in DAILY_BAR_COLUMNS})
    return output.getvalue()


def save_daily_bars(
    facts: Sequence[DailyBarFact],
    path: str | Path = DEFAULT_DAILY_BARS_CSV,
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(daily_bars_to_csv_text(facts), encoding="utf-8")
    return str(target)


def summarize_daily_bars(facts: Iterable[DailyBarFact]) -> dict[str, object]:
    grouped: dict[str, list[DailyBarFact]] = {}
    for fact in facts:
        grouped.setdefault(fact.ticker, []).append(fact)
    summaries: dict[str, dict[str, object]] = {}
    for ticker, rows in grouped.items():
        ordered = sorted(rows, key=lambda fact: fact.date)
        closes = [value for row in ordered if (value := _price_value(row)) is not None]
        volumes = [row.volume for row in ordered if row.volume is not None]
        latest = ordered[-1] if ordered else None
        summaries[ticker] = {
            "ticker": ticker,
            "bar_count": len(ordered),
            "latest_date": latest.date if latest else "",
            "latest_close": _price_value(latest) if latest else None,
            "latest_volume": latest.volume if latest else None,
            "range_high": max((row.high for row in ordered if row.high is not None), default=None),
            "range_low": min((row.low for row in ordered if row.low is not None), default=None),
            "return_pct": _return_pct(closes),
            "average_volume": round(sum(volumes) / len(volumes), 6) if volumes else None,
            "formula": "return_pct = latest adjusted_close / first adjusted_close - 1",
        }
    return {
        "available": bool(summaries),
        "tickers": summaries,
        "auto_trading": False,
    }


def latest_price_facts_from_bars(
    facts: Iterable[DailyBarFact],
    *,
    source_ref: str = str(DEFAULT_DAILY_BARS_CSV),
) -> list[MarketPriceFact]:
    """Convert the latest bar close per ticker into current price facts."""

    from investment_assistant.portfolio.price_store import MarketPriceFact

    latest_by_ticker: dict[str, DailyBarFact] = {}
    for fact in facts:
        price = _price_value(fact)
        if price is None or price <= 0:
            continue
        current = latest_by_ticker.get(fact.ticker)
        if current is None or fact.date > current.date:
            latest_by_ticker[fact.ticker] = fact

    price_facts: list[MarketPriceFact] = []
    for ticker in sorted(latest_by_ticker):
        fact = latest_by_ticker[ticker]
        price = _price_value(fact)
        if price is None or price <= 0:
            continue
        price_facts.append(
            MarketPriceFact(
                ticker=ticker,
                price=price,
                as_of=fact.date,
                provider_id=fact.provider_id,
                source_ref=source_ref or fact.source_ref,
                note="synced_from_daily_bars",
            )
        )
    return price_facts


def visible_ticker(value: object) -> str:
    text = str(value or "").strip().upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 5 and digits.endswith("0"):
        return digits[:4]
    return digits or text


def _price_value(row: DailyBarFact | None) -> float | None:
    if row is None:
        return None
    return row.adjusted_close or row.close


def _return_pct(values: Sequence[float]) -> float | None:
    if len(values) < 2 or values[0] <= 0:
        return None
    return round((values[-1] / values[0] - 1.0) * 100.0, 6)


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _text(value: object) -> str:
    return str(value or "").strip()


def _csv_value(value: object) -> object:
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else str(round(value, 6))
    return "" if value is None else value
