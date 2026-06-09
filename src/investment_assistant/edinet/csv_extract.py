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
