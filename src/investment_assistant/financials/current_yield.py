"""Current dividend/yield reconciliation for portfolio income estimates.

EDINET dividend facts are historical filing values. They are useful evidence,
but they are not always on the same basis as a current market price because
stock splits and forecast dividend revisions can happen after the filing. This
module keeps that boundary explicit: current income uses a current/forecast
dividend fact when available, while EDINET remains the fallback and evidence.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

CURRENT_YIELD_COLUMNS: tuple[str, ...] = (
    "ticker",
    "name",
    "current_dividend_per_share",
    "current_price",
    "yield_pct",
    "as_of",
    "source_ref",
    "provider_id",
    "note",
)

DEFAULT_CURRENT_YIELDS_CSV = Path("local_docs/market/current_yields.csv")
CURRENT_YIELD_REVIEW_THRESHOLD_PCT = 5.0


@dataclass(frozen=True)
class CurrentYieldFact:
    ticker: str
    name: str = ""
    current_dividend_per_share: float | None = None
    current_price: float | None = None
    yield_pct: float | None = None
    as_of: str = ""
    source_ref: str = ""
    provider_id: str = "user_csv"
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "")}


@dataclass(frozen=True)
class CurrentYieldReconciliation:
    ticker: str
    name: str = ""
    status: str = "not_available"
    income_source: str = "not_available"
    current_dividend_per_share: float | None = None
    current_price: float | None = None
    income_yield_pct: float | None = None
    edinet_dividend_per_share: float | None = None
    edinet_implied_yield_pct: float | None = None
    correction_factor: float | None = None
    source_ref: str = ""
    provider_id: str = ""
    warnings: tuple[str, ...] = ()
    formula: str = ""

    def to_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "", ())}


def load_current_yields(
    path: str | Path | None = DEFAULT_CURRENT_YIELDS_CSV,
) -> dict[str, CurrentYieldFact]:
    """Load current dividend/yield facts from CSV.

    Missing files are treated as an empty overlay so local production/dev flows
    can opt in without forcing sample data.
    """

    if path is None:
        return {}
    csv_path = Path(path)
    if not csv_path.is_file():
        return {}
    return parse_current_yields_csv(csv_path.read_text(encoding="utf-8-sig"))


def parse_current_yields_csv(text: str) -> dict[str, CurrentYieldFact]:
    """Parse current dividend/yield facts keyed by ticker."""

    reader = csv.DictReader(io.StringIO(text))
    facts: dict[str, CurrentYieldFact] = {}
    for row in reader:
        fact = current_yield_fact_from_row(row)
        if fact is not None:
            facts[fact.ticker] = fact
    return facts


def current_yield_fact_from_row(row: Mapping[str, object]) -> CurrentYieldFact | None:
    ticker = _text(row.get("ticker") or row.get("code") or row.get("security_code"))
    if not ticker:
        return None
    current_price = _optional_float(
        row.get("current_price") or row.get("price") or row.get("market_price")
    )
    yield_pct = _optional_float(row.get("yield_pct") or row.get("current_yield_pct"))
    dividend = _optional_float(
        row.get("current_dividend_per_share")
        or row.get("forecast_dividend_per_share")
        or row.get("dividend_per_share")
    )
    if dividend is None and current_price is not None and yield_pct is not None:
        dividend = current_price * yield_pct / 100.0
    if yield_pct is None and dividend is not None and current_price is not None:
        yield_pct = dividend / current_price * 100.0
    return CurrentYieldFact(
        ticker=ticker,
        name=_text(row.get("name")),
        current_dividend_per_share=_positive_or_none(dividend),
        current_price=_positive_or_none(current_price),
        yield_pct=_positive_or_none(yield_pct),
        as_of=_text(row.get("as_of") or row.get("date") or row.get("last_updated")),
        source_ref=_text(row.get("source_ref") or row.get("source") or row.get("url")),
        provider_id=_text(row.get("provider_id") or row.get("provider")) or "user_csv",
        note=_text(row.get("note")),
    )


def reconcile_current_yield(
    *,
    ticker: str,
    name: str = "",
    edinet_dividend_per_share: float | None = None,
    current_price: float | None = None,
    fact: CurrentYieldFact | None = None,
    review_threshold_pct: float = CURRENT_YIELD_REVIEW_THRESHOLD_PCT,
) -> CurrentYieldReconciliation:
    """Reconcile EDINET historical DPS with current dividend facts.

    A current/forecast dividend fact wins because it is price-date compatible.
    EDINET is still returned as a fallback and as an audit comparison.
    """

    price = _positive_or_none(current_price)
    if price is None and fact is not None:
        price = fact.current_price
    edinet_dps = _positive_or_none(edinet_dividend_per_share)
    edinet_yield = _yield_pct(edinet_dps, price)
    warnings: list[str] = []

    if fact is not None and fact.current_dividend_per_share is not None:
        dividend = fact.current_dividend_per_share
        income_yield = _yield_pct(dividend, price) or fact.yield_pct
        correction_factor = None
        if edinet_dps is not None and dividend > 0 and not _close(edinet_dps, dividend):
            correction_factor = round(edinet_dps / dividend, 6)
        if (
            edinet_yield is not None
            and income_yield is not None
            and abs(edinet_yield - income_yield) >= max(1.0, income_yield * 0.25)
        ):
            warnings.append("edinet_current_basis_mismatch_adjusted")
        return CurrentYieldReconciliation(
            ticker=ticker,
            name=fact.name or name,
            status="current_fact",
            income_source="current_dividend_per_share",
            current_dividend_per_share=round(dividend, 6),
            current_price=round(price, 6) if price is not None else None,
            income_yield_pct=round(income_yield, 6) if income_yield is not None else None,
            edinet_dividend_per_share=edinet_dps,
            edinet_implied_yield_pct=edinet_yield,
            correction_factor=correction_factor,
            source_ref=fact.source_ref,
            provider_id=fact.provider_id,
            warnings=tuple(warnings),
            formula="current_dividend_per_share / current_price * 100",
        )

    if edinet_dps is None:
        return CurrentYieldReconciliation(
            ticker=ticker,
            name=name,
            status="not_available",
            income_source="not_available",
            current_price=round(price, 6) if price is not None else None,
            warnings=("current_dividend_missing",),
            formula="current dividend fact or EDINET dividend per share required",
        )

    if edinet_yield is not None and edinet_yield >= review_threshold_pct:
        warnings.append("edinet_current_basis_review")
    return CurrentYieldReconciliation(
        ticker=ticker,
        name=name,
        status="edinet_fallback_review" if warnings else "edinet_fallback",
        income_source="edinet_latest_dividend_per_share",
        current_dividend_per_share=round(edinet_dps, 6),
        current_price=round(price, 6) if price is not None else None,
        income_yield_pct=edinet_yield,
        edinet_dividend_per_share=edinet_dps,
        edinet_implied_yield_pct=edinet_yield,
        warnings=tuple(warnings),
        formula="edinet_latest_dividend_per_share / current_price * 100",
    )


def current_yields_to_csv_text(facts: Sequence[CurrentYieldFact]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(CURRENT_YIELD_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for fact in facts:
        writer.writerow(
            {
                "ticker": fact.ticker,
                "name": fact.name,
                "current_dividend_per_share": _format_number(fact.current_dividend_per_share),
                "current_price": _format_number(fact.current_price),
                "yield_pct": _format_number(fact.yield_pct),
                "as_of": fact.as_of,
                "source_ref": fact.source_ref,
                "provider_id": fact.provider_id,
                "note": fact.note,
            }
        )
    return output.getvalue()


def merge_current_yield_facts(
    existing: Iterable[CurrentYieldFact],
    incoming: Iterable[CurrentYieldFact],
) -> list[CurrentYieldFact]:
    facts = {fact.ticker: fact for fact in existing}
    facts.update({fact.ticker: fact for fact in incoming})
    return [facts[ticker] for ticker in sorted(facts)]


def _yield_pct(dividend_per_share: float | None, price: float | None) -> float | None:
    dividend = _positive_or_none(dividend_per_share)
    market_price = _positive_or_none(price)
    if dividend is None or market_price is None:
        return None
    return round(dividend / market_price * 100.0, 6)


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _positive_or_none(value: float | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _text(value: object) -> str:
    return str(value or "").strip()


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if value == int(value) else str(round(value, 6))


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(0.01, abs(right) * 0.01)
