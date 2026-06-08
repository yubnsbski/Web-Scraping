from __future__ import annotations

from pathlib import Path

from investment_assistant.financials.evidence import (
    build_financial_evidence,
    dividend_evidence_text,
    load_comparison,
    ticker_from_source,
)

_CSV = (
    "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
    "8306,MUFG,2023,1100000,9.5,50.0,配当性向 38%\n"
    "8306,MUFG,2024,1200000,9.9,40.0,配当性向 42%\n"
)


def _csv(tmp_path: Path) -> Path:
    path = tmp_path / "financials.csv"
    path.write_text(_CSV, encoding="utf-8")
    return path


def test_ticker_from_source_extracts_four_digit_code() -> None:
    assert ticker_from_source("local_docs/nikkei225/8306/ir.txt") == "8306"
    assert ticker_from_source("") is None
    assert ticker_from_source(None) is None


def test_dividend_evidence_text_reports_cut(tmp_path: Path) -> None:
    comparison = load_comparison(_csv(tmp_path))
    assert comparison is not None
    company = comparison["companies"][0]  # type: ignore[index]
    text = dividend_evidence_text(company)

    assert "8306" in text
    assert "減少傾向" in text
    assert "減配年: 2024" in text
    assert "50.0 → 40.0" in text
    assert "営業CF推移: 増加傾向" in text
    assert "投資助言ではありません" in text


def test_build_financial_evidence_resolves_ticker_from_source(tmp_path: Path) -> None:
    evidence = build_financial_evidence(
        target_source="local_docs/nikkei225/8306/ir.txt",
        csv_path=_csv(tmp_path),
    )
    assert evidence is not None
    assert "減配年: 2024" in evidence


def test_build_financial_evidence_none_when_csv_missing(tmp_path: Path) -> None:
    assert build_financial_evidence(ticker="8306", csv_path=tmp_path / "nope.csv") is None


def test_build_financial_evidence_none_for_unknown_ticker(tmp_path: Path) -> None:
    assert build_financial_evidence(ticker="9999", csv_path=_csv(tmp_path)) is None


def test_single_period_evidence_shows_latest_values_and_note(tmp_path: Path) -> None:
    path = tmp_path / "financials.csv"
    path.write_text(
        "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"
        "9602,東宝,2024,500000,52.0,40.0,配当性向 30%\n",
        encoding="utf-8",
    )
    comparison = load_comparison(path)
    assert comparison is not None
    company = comparison["companies"][0]  # type: ignore[index]
    text = dividend_evidence_text(company)

    # With one period the trend is unavailable, but the latest actuals are shown.
    assert "1株配当=40.0" in text
    assert "自己資本比率=52.0" in text
    assert "現在1期のみ取得" in text
    assert "データ不足" in text
