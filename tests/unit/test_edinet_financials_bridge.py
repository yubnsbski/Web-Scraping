from __future__ import annotations

from pathlib import Path

from investment_assistant.edinet.csv_extract import FinancialValue
from investment_assistant.edinet.financials_bridge import (
    build_financial_point,
    dedupe_points,
    point_from_mapping,
    point_to_row,
    write_financials_csv,
)
from investment_assistant.edinet.models import EdinetDocument
from investment_assistant.financials import load_financials
from investment_assistant.financials.models import FinancialPoint


def _value(item_name: str, value: str, consolidated: str = "連結") -> FinancialValue:
    return FinancialValue(
        item_name=item_name,
        value=value,
        context_id="CurrentYearDuration",
        unit="",
        consolidated=consolidated,
        period="",
        element_id="",
    )


def _document(period_end: str | None = "2024-03-31") -> EdinetDocument:
    return EdinetDocument(
        doc_id="S100AAA1",
        edinet_code="E1",
        sec_code="83060",
        filer_name="三菱UFJ",
        doc_type_code="120",
        doc_description="有価証券報告書",
        period_start="2023-04-01",
        period_end=period_end,
        submit_datetime="2024-06-21 09:00",
        has_xbrl=True,
        has_csv=True,
        has_pdf=True,
    )


def test_build_financial_point_maps_metrics() -> None:
    values = [
        _value("営業活動によるキャッシュ・フロー", "1234567"),
        _value("自己資本比率", "9.8"),
        _value("１株当たり配当", "41.0"),
        _value("配当性向", "40.1"),
    ]
    point = build_financial_point(_document(), values, ticker="8306", company="MUFG")

    assert point is not None
    assert point.ticker == "8306"
    assert point.name == "MUFG"
    assert point.fiscal_year == 2024
    assert point.operating_cf == 1234567.0
    assert point.equity_ratio == 9.8
    assert point.dividend_per_share == 41.0
    assert point.payout_policy == "配当性向 40.1%"


def test_build_financial_point_requires_dividend() -> None:
    values = [_value("営業活動によるキャッシュ・フロー", "100")]
    assert build_financial_point(_document(), values, ticker="8306") is None


def test_build_financial_point_requires_period_end() -> None:
    values = [_value("１株当たり配当", "41.0")]
    assert build_financial_point(_document(period_end=None), values, ticker="8306") is None


def _point(ticker: str, fy: int, dps: float) -> FinancialPoint:
    return FinancialPoint(
        ticker=ticker,
        name="x",
        fiscal_year=fy,
        operating_cf=0.0,
        equity_ratio=0.0,
        dividend_per_share=dps,
        payout_policy="",
    )


def test_dedupe_points_keeps_first_per_ticker_year() -> None:
    points = [
        _point("8306", 2024, 41.0),  # newest first
        _point("8306", 2024, 99.0),  # duplicate period -> dropped
        _point("8306", 2023, 38.0),
    ]
    deduped = dedupe_points(points)
    assert [(p.fiscal_year, p.dividend_per_share) for p in deduped] == [
        (2024, 41.0),
        (2023, 38.0),
    ]


def test_row_roundtrip_and_csv_is_loadable(tmp_path: Path) -> None:
    point = _point("8306", 2024, 41.0)
    restored = point_from_mapping(point_to_row(point))
    assert restored == point

    csv_path = tmp_path / "financials.csv"
    write_financials_csv([_point("8306", 2024, 41.0), _point("8306", 2023, 50.0)], csv_path)
    loaded = load_financials(csv_path)
    assert {p.fiscal_year for p in loaded} == {2023, 2024}
