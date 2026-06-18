"""Unit coverage for market-data -> RAG evidence document generation."""

from __future__ import annotations

from pathlib import Path

from investment_assistant.portfolio.market_rag import (
    build_market_evidence_docs,
    render_market_evidence_markdown,
)

_FIN_CSV = (
    "ticker,name,price,per,pbr,dps,dividend_yield,dividend_yield_percent,eps,market_cap\n"
    "9433,KDDI,2708,13.5,1.2,140,0.032,3.2,200,6300000000000\n"
    "1444,ニッソウ,2874,-,1.9,0,0,0,-,\n"
    "9433,KDDI dup,9999,1,1,1,0,0,1,1\n"  # duplicate ticker -> first wins
)
_BARS_CSV = (
    "ticker,date,open,high,low,close,volume\n"
    "9433,2026-06-16,2700,2720,2690,2708,1000\n"
    "9433,2026-06-17,2710,2740,2705,2730,1200\n"
)


def test_render_includes_metrics_and_drops_dashes() -> None:
    row = {
        "ticker": "1444",
        "name": "ニッソウ",
        "price": "2874",
        "per": "-",
        "pbr": "1.9",
        "eps": "-",
    }
    md = render_market_evidence_markdown(row)
    assert md is not None
    assert "ニッソウ（1444）" in md
    assert "株価: 2874 円" in md
    assert "PBR: 1.9 倍" in md
    # '-' metrics are omitted rather than rendered as a dash.
    assert "PER" not in md
    assert "EPS" not in md


def test_render_includes_latest_close_when_provided() -> None:
    md = render_market_evidence_markdown(
        {"ticker": "9433", "name": "KDDI", "price": "2708"},
        latest_close=("2026-06-17", "2730"),
    )
    assert md is not None
    assert "直近終値: 2730 円（2026-06-17 時点）" in md
    assert 'as_of: "2026-06-17"' in md


def test_render_returns_none_without_ticker() -> None:
    assert render_market_evidence_markdown({"name": "no code"}) is None


def test_market_cap_rendered_as_readable_oku_yen() -> None:
    md = render_market_evidence_markdown(
        {"ticker": "9433", "name": "KDDI", "market_cap": "6300000000000"}
    )
    assert md is not None
    # 6.3e12 yen -> 63,000 億円 (raw digit string is not shown).
    assert "時価総額: 63,000 億円" in md
    assert "6300000000000" not in md


def test_feature_tags_for_value_and_dividend_intent() -> None:
    md = render_market_evidence_markdown(
        {
            "ticker": "1",
            "name": "X",
            "per": "9.5",
            "pbr": "0.9",
            "dividend_yield_percent": "4.2",
            "dps": "140",
        }
    )
    assert md is not None
    assert "高配当" in md
    assert "低PER（割安圏）" in md
    assert "PBR1倍割れ（資産妙味）" in md


def test_no_dividend_tag_for_zero_yield() -> None:
    md = render_market_evidence_markdown(
        {"ticker": "130A", "name": "Growth", "dividend_yield_percent": "0", "dps": "0"}
    )
    assert md is not None
    assert "無配・低配当" in md
    assert "高配当" not in md


def test_build_writes_one_doc_per_ticker_with_latest_close(tmp_path: Path) -> None:
    fin = tmp_path / "fin.csv"
    fin.write_text(_FIN_CSV, encoding="utf-8")
    bars = tmp_path / "bars.csv"
    bars.write_text(_BARS_CSV, encoding="utf-8")
    out = tmp_path / "rag"

    result = build_market_evidence_docs(
        financials_csv=fin, output_dir=out, daily_bars_csv=bars
    )

    # Two distinct tickers (the duplicate 9433 is ignored).
    assert result["documents_written"] == 2
    assert result["with_daily_close"] is True
    assert sorted(p.name for p in out.glob("*.md")) == ["1444.md", "9433.md"]
    # Latest close prefers the newest bar date.
    assert "直近終値: 2730 円" in (out / "9433.md").read_text(encoding="utf-8")


def test_build_works_without_daily_bars(tmp_path: Path) -> None:
    fin = tmp_path / "fin.csv"
    fin.write_text(_FIN_CSV, encoding="utf-8")
    out = tmp_path / "rag"

    result = build_market_evidence_docs(financials_csv=fin, output_dir=out)

    assert result["documents_written"] == 2
    assert result["with_daily_close"] is False
    assert "直近終値" not in (out / "9433.md").read_text(encoding="utf-8")
