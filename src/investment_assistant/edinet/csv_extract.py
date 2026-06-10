"""Extract financial line-items from EDINET CSV (type=5) archives.

The EDINET "CSV" acquisition returns a ZIP of tab-separated, UTF-16 encoded
files whose columns are::

    要素ID  項目名  コンテキストID  相対年度  連結・個別  期間・時点  ユニットID  単位  値

This module parses those rows into typed values and selects the metrics the RAG
store is currently missing (営業CF / 自己資本比率 / 配当性向 …), then renders them
as a compact text document. Feeding that text through the existing RAG indexer
is what turns today's DOE=0 / 営業CF=0 into non-zero, grounded answers.

No network I/O: input is raw archive bytes the caller already downloaded.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from investment_assistant.edinet.models import EdinetDocument

# Display label -> substrings to look for in the CSV 項目名 column. Order is the
# display order in the rendered RAG text.
DEFAULT_METRIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "営業活動によるキャッシュ・フロー": ("営業活動によるキャッシュ",),
    "投資活動によるキャッシュ・フロー": ("投資活動によるキャッシュ",),
    "財務活動によるキャッシュ・フロー": ("財務活動によるキャッシュ",),
    "自己資本比率": ("自己資本比率",),
    "自己資本利益率": ("自己資本利益率", "ＲＯＥ"),
    "配当性向": ("配当性向",),
    "純資産": ("純資産額", "純資産"),
    "１株当たり配当": ("１株当たり配当", "1株当たり配当"),
}

_HEADER_ITEM_NAME = "項目名"
_HEADER_VALUE = "値"
_HEADER_CONTEXT = "コンテキストID"
_HEADER_UNIT = "単位"
_HEADER_CONSOLIDATED = "連結・個別"
_HEADER_PERIOD = "期間・時点"
_HEADER_ELEMENT = "要素ID"

# Canonical EDINET taxonomy element for the *annual* dividend per share in the
# "主要な経営指標等" summary table. Preferring this element avoids latching onto
# interim / quarter-end / forecast per-share rows that share the "１株当たり配当"
# item-name substring.
DIVIDEND_ANNUAL_ELEMENT = "DividendPaidPerShareSummaryOfBusinessResults"
# Item-name tokens that mark a NON-annual or NON-actual per-share dividend row.
_DIVIDEND_NOISE_TOKENS: tuple[str, ...] = (
    "中間",  # 1株当たり中間配当額
    "期末",  # 1株当たり期末配当額
    "四半期",  # 第N四半期
    "予想",  # forecast (次期予想)
)
# Context-id tokens that mark a forecast / prior-period context.
_FORECAST_CONTEXT_TOKENS: tuple[str, ...] = ("Forecast", "Prior")

# The "主要な経営指標等" (summary of business results) table restates the last five
# fiscal years on a single, consistent (split-adjusted) basis within one filing.
# Relative-year contexts identify each column: ``CurrentYear`` and ``PriorNYear``.
_RELATIVE_YEAR_RE = re.compile(r"(?:Current|Prior(\d+))Year")


@dataclass(frozen=True)
class FinancialValue:
    """One financial line-item extracted from an EDINET CSV."""

    item_name: str
    value: str
    context_id: str
    unit: str
    consolidated: str
    period: str
    element_id: str


def parse_csv_archive(data: bytes) -> list[FinancialValue]:
    """Parse all CSV members of an EDINET type=5 ZIP into financial values."""

    values: list[FinancialValue] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".csv"):
                continue
            text = _decode_edinet_csv(archive.read(name))
            values.extend(_parse_csv_text(text))
    return values


def select_metrics(
    values: Iterable[FinancialValue],
    keyword_map: Mapping[str, Sequence[str]] = DEFAULT_METRIC_KEYWORDS,
) -> dict[str, list[FinancialValue]]:
    """Group values by display label using substring matches on the item name.

    Consolidated (``連結``) rows are preferred and sorted first within each label
    so callers can take the first match as the headline number.
    """

    grouped: dict[str, list[FinancialValue]] = {label: [] for label in keyword_map}
    for value in values:
        for label, keywords in keyword_map.items():
            if any(keyword in value.item_name for keyword in keywords):
                grouped[label].append(value)
    for matches in grouped.values():
        matches.sort(key=lambda item: (0 if "連結" in item.consolidated else 1))
    return {label: matches for label, matches in grouped.items() if matches}


def select_dividend_per_share(
    values: Iterable[FinancialValue],
) -> FinancialValue | None:
    """Pick the *annual, actual* per-share dividend from a filing's values.

    EDINET filings carry several rows whose item name contains the substring
    "１株当たり配当": the annual figure, interim / period-end splits, quarterly
    breakdowns, and next-period forecasts. Taking the first substring match (the
    old behaviour) could latch onto an interim-only or forecast value, producing
    a wrong annual dividend (e.g. SMC's interim-only figure).

    Selection order, most authoritative first:

    1. The canonical ``DividendPaidPerShareSummaryOfBusinessResults`` element on a
       non-forecast context — this is the annual summary-table value.
    2. Any ``１株当たり配当`` item-name match that is not an interim / period-end /
       quarterly / forecast row, on a non-forecast context.

    Within each tier, consolidated (``連結``) rows win. Returns ``None`` when no
    usable annual dividend is present.
    """

    candidates = [
        value
        for value in values
        if DIVIDEND_ANNUAL_ELEMENT in value.element_id
        or "１株当たり配当" in value.item_name
        or "1株当たり配当" in value.item_name
    ]
    if not candidates:
        return None

    def rank(value: FinancialValue) -> tuple[int, int, int]:
        is_summary = DIVIDEND_ANNUAL_ELEMENT in value.element_id
        is_noise = any(token in value.item_name for token in _DIVIDEND_NOISE_TOKENS)
        is_forecast = any(token in value.context_id for token in _FORECAST_CONTEXT_TOKENS)
        is_consolidated = "連結" in value.consolidated
        # Lower tuples sort first: prefer summary element, then non-noise,
        # non-forecast, consolidated rows.
        return (
            0 if is_summary else 1,
            0 if not (is_noise or is_forecast) else 1,
            0 if is_consolidated else 1,
        )

    best = min(candidates, key=rank)
    # Reject a best candidate that is still interim/forecast-only: better to
    # report no annual dividend than a misleading partial one.
    if DIVIDEND_ANNUAL_ELEMENT not in best.element_id and (
        any(token in best.item_name for token in _DIVIDEND_NOISE_TOKENS)
        or any(token in best.context_id for token in _FORECAST_CONTEXT_TOKENS)
    ):
        return None
    return best


def _safe_float(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _context_year_offset(context_id: str) -> int | None:
    """Map a relative-year context to a backward offset (0=current, 1..N=prior)."""

    match = _RELATIVE_YEAR_RE.search(context_id)
    if match is None:
        return None
    prior = match.group(1)
    return int(prior) if prior is not None else 0


def summary_series_offsets(
    values: Iterable[FinancialValue], element_substring: str
) -> dict[int, float]:
    """Extract a summary-table metric as ``{year_offset: value}``.

    Reads every value whose ``element_id`` contains ``element_substring`` (a
    ``...SummaryOfBusinessResults`` element) and keys it by the relative-year
    offset parsed from its context (0 = current fiscal year, 1..N = prior years).
    Consolidated (``連結``) rows win when both bases report the same offset. The
    five years come from one filing, so the series is internally consistent —
    e.g. already split-adjusted for per-share figures.
    """

    chosen: dict[int, tuple[bool, float]] = {}
    for value in values:
        if element_substring not in value.element_id:
            continue
        offset = _context_year_offset(value.context_id)
        if offset is None:
            continue
        number = _safe_float(value.value)
        if number is None:
            continue
        is_consolidated = "連結" in value.consolidated
        existing = chosen.get(offset)
        if existing is None or (is_consolidated and not existing[0]):
            chosen[offset] = (is_consolidated, number)
    return {offset: number for offset, (_, number) in chosen.items()}


def to_rag_text(
    document: EdinetDocument,
    values: Iterable[FinancialValue],
    *,
    company: str | None = None,
    keyword_map: Mapping[str, Sequence[str]] = DEFAULT_METRIC_KEYWORDS,
) -> str:
    """Render selected metrics as a compact text document for RAG indexing."""

    grouped = select_metrics(values, keyword_map)
    title_company = company or document.filer_name or document.ticker or "company"
    header_bits = [str(title_company)]
    if document.ticker:
        header_bits.append(document.ticker)
    if document.period_end:
        header_bits.append(f"{document.period_end} 期")
    header_bits.append(document.doc_type_label)

    lines = [" ".join(header_bits), ""]
    if not grouped:
        lines.append("（対象の財務指標は抽出されませんでした）")
    for label, matches in grouped.items():
        headline = matches[0]
        unit = f" {headline.unit}" if headline.unit and headline.unit != "－" else ""
        scope = headline.consolidated or ""
        lines.append(f"{label}: {headline.value}{unit}（{scope}）".rstrip())
    lines.append("")
    lines.append(f"出典: EDINET docID={document.doc_id}")
    return "\n".join(lines).strip() + "\n"


def _decode_edinet_csv(raw: bytes) -> str:
    """Decode EDINET CSV bytes, which are UTF-16 (with BOM) in practice."""

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-16")
    except UnicodeError:
        return raw.decode("utf-8-sig", errors="replace")


def _parse_csv_text(text: str) -> list[FinancialValue]:
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    index = {name: position for position, name in enumerate(header)}
    if _HEADER_ITEM_NAME not in index or _HEADER_VALUE not in index:
        return []

    values: list[FinancialValue] = []
    for row in rows[1:]:
        item_name = _cell(row, index, _HEADER_ITEM_NAME)
        value = _cell(row, index, _HEADER_VALUE)
        if not item_name or not value:
            continue
        values.append(
            FinancialValue(
                item_name=item_name,
                value=value,
                context_id=_cell(row, index, _HEADER_CONTEXT),
                unit=_cell(row, index, _HEADER_UNIT),
                consolidated=_cell(row, index, _HEADER_CONSOLIDATED),
                period=_cell(row, index, _HEADER_PERIOD),
                element_id=_cell(row, index, _HEADER_ELEMENT),
            )
        )
    return values


def _cell(row: Sequence[str], index: Mapping[str, int], name: str) -> str:
    position = index.get(name)
    if position is None or position >= len(row):
        return ""
    return row[position].strip()
