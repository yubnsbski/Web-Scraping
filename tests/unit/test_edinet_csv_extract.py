from __future__ import annotations

import io
import zipfile

from investment_assistant.edinet.csv_extract import (
    parse_csv_archive,
    select_metrics,
    to_rag_text,
)
from investment_assistant.edinet.models import EdinetDocument

_HEADER = "要素ID\t項目名\tコンテキストID\t相対年度\t連結・個別\t期間・時点\tユニットID\t単位\t値"
_ROWS = [
    "jpcrp_cor:NetCashProvidedByUsedInOperatingActivities\t"
    "営業活動によるキャッシュ・フロー\tCurrentYearDuration\t当期\t連結\t期間\tJPY\t百万円\t1234567",
    "jpcrp_cor:EquityToAssetRatio\t自己資本比率\tCurrentYearInstant\t当期\t連結\t時点\tPure\t％\t9.8",
    "jpcrp_cor:PayoutRatio\t配当性向\tCurrentYearDuration\t当期\t連結\t期間\tPure\t％\t40.1",
    "jpcrp_cor:Sundry\tその他の項目\tCurrentYearDuration\t当期\t個別\t期間\tJPY\t百万円\t999",
]


def _build_csv_zip() -> bytes:
    text = "\r\n".join([_HEADER, *_ROWS]) + "\r\n"
    # EDINET CSVs are UTF-16 with a BOM.
    csv_bytes = text.encode("utf-16")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("XBRL_TO_CSV/jpcrp030000-asr-001.csv", csv_bytes)
        archive.writestr("XBRL_TO_CSV/manifest.txt", b"not a csv")
    return buffer.getvalue()


def _document() -> EdinetDocument:
    return EdinetDocument(
        doc_id="S100AAA1",
        edinet_code="E00001",
        sec_code="83060",
        filer_name="三菱UFJフィナンシャル・グループ",
        doc_type_code="120",
        doc_description="有価証券報告書",
        period_start="2023-04-01",
        period_end="2024-03-31",
        submit_datetime="2024-06-21 09:00",
        has_xbrl=True,
        has_csv=True,
        has_pdf=True,
    )


def test_parse_csv_archive_reads_utf16_tab_rows() -> None:
    values = parse_csv_archive(_build_csv_zip())
    by_name = {value.item_name: value for value in values}

    assert "営業活動によるキャッシュ・フロー" in by_name
    assert by_name["営業活動によるキャッシュ・フロー"].value == "1234567"
    assert by_name["自己資本比率"].value == "9.8"
    assert by_name["配当性向"].unit == "％"


def test_select_metrics_groups_target_items() -> None:
    values = parse_csv_archive(_build_csv_zip())
    grouped = select_metrics(values)

    assert "営業活動によるキャッシュ・フロー" in grouped
    assert "自己資本比率" in grouped
    assert "配当性向" in grouped
    # The unrelated row is not selected.
    assert "その他の項目" not in grouped


def test_to_rag_text_contains_metrics_and_source() -> None:
    values = parse_csv_archive(_build_csv_zip())
    text = to_rag_text(_document(), values, company="MUFG")

    assert "MUFG" in text
    assert "8306" in text
    assert "営業活動によるキャッシュ・フロー: 1234567" in text
    assert "自己資本比率: 9.8" in text
    assert "配当性向: 40.1" in text
    assert "EDINET docID=S100AAA1" in text


def test_to_rag_text_handles_no_matches() -> None:
    empty_zip = io.BytesIO()
    with zipfile.ZipFile(empty_zip, "w") as archive:
        archive.writestr("note.txt", b"no csv here")
    text = to_rag_text(_document(), parse_csv_archive(empty_zip.getvalue()))
    assert "抽出されませんでした" in text
