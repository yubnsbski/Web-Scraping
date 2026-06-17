"""Unit coverage for the JPX domestic-stock universe builder.

New / conflict-light file. Verifies the parser keeps domestic common stock,
drops ETF/REIT/foreign issues, filters by market segment, handles BOM/CP932
and alphanumeric codes, and round-trips through the built universe CSV. Also
checks the webapi wiring prefers the universe file over the financials CSV.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.portfolio import jpx_universe as ju

# Minimal stand-in for JPX's data_j.csv (東証上場銘柄一覧) export.
_JPX_CSV = (
    "日付,コード,銘柄名,市場・商品区分,33業種区分\n"
    "2026-06-16,7203,トヨタ自動車,プライム（内国株式）,輸送用機器\n"
    "2026-06-16,8306,三菱UFJ,プライム（内国株式）,銀行業\n"
    "2026-06-16,2585,ヘリオステクノ,スタンダード（内国株式）,食料品\n"
    "2026-06-16,9468,カドカワ,グロース（内国株式）,情報・通信業\n"
    "2026-06-16,130A,Veritas,グロース（内国株式）,サービス業\n"
    "2026-06-16,1306,TOPIX連動ETF,ETF・ETN,-\n"
    "2026-06-16,8951,日本ビルファンド,REIT・ベンチャーファンド・カントリーファンド・インフラファンド,-\n"
    "2026-06-16,4385,メルカリ外国,外国株式,-\n"
)


def test_domestic_tickers_keeps_only_domestic_common_stock() -> None:
    codes = ju.domestic_tickers(_JPX_CSV, scope="domestic")
    # ETF (1306), REIT (8951) and foreign (4385) are excluded; alphanumeric 130A kept.
    assert codes == ["7203", "8306", "2585", "9468", "130A"]


def test_scope_filters_by_market_segment() -> None:
    assert ju.domestic_tickers(_JPX_CSV, scope="prime") == ["7203", "8306"]
    assert ju.domestic_tickers(_JPX_CSV, scope="standard") == ["2585"]
    assert ju.domestic_tickers(_JPX_CSV, scope="growth") == ["9468", "130A"]


def test_bom_and_pre_suffixed_codes_are_normalized() -> None:
    bom_csv = "﻿コード,銘柄名,市場・商品区分\n7203.T,トヨタ,プライム（内国株式）\n"
    assert ju.domestic_tickers(bom_csv, scope="domestic") == ["7203"]


def test_crlf_and_lone_cr_line_endings_parse() -> None:
    header = "コード,銘柄名,市場・商品区分"
    body = ["7203,トヨタ,プライム（内国株式）", "8306,三菱UFJ,プライム（内国株式）"]
    crlf = "\r\n".join([header, *body]) + "\r\n"
    lone_cr = "\r".join([header, *body]) + "\r"  # Excel/Mac exports; previously crashed
    assert ju.domestic_tickers(crlf, scope="domestic") == ["7203", "8306"]
    assert ju.domestic_tickers(lone_cr, scope="domestic") == ["7203", "8306"]


def test_build_universe_from_lone_cr_file(tmp_path: Path) -> None:
    header = "コード,銘柄名,市場・商品区分"
    text = "\r".join([header, "7203,トヨタ,プライム（内国株式）"]) + "\r"
    src = tmp_path / "data_j.csv"
    src.write_bytes(text.encode("cp932"))
    out = tmp_path / "uni.csv"
    summary = ju.build_domestic_universe_csv(src, output_path=out, scope="domestic")
    assert summary["ticker_count"] == 1
    assert ju.load_domestic_universe_tickers(out, scope="domestic") == ["7203"]


def test_build_and_reload_universe_csv_round_trips(tmp_path: Path) -> None:
    # Source written as CP932 (Shift_JIS), as the real JPX export is.
    src = tmp_path / "data_j.csv"
    src.write_bytes(_JPX_CSV.encode("cp932"))
    out = tmp_path / "domestic_universe.csv"

    summary = ju.build_domestic_universe_csv(src, output_path=out, scope="domestic")
    assert summary["ticker_count"] == 5
    assert out.is_file()

    assert ju.load_domestic_universe_tickers(out, scope="domestic") == [
        "7203",
        "8306",
        "2585",
        "9468",
        "130A",
    ]
    # The stored segment column still supports scope filtering on reload.
    assert ju.load_domestic_universe_tickers(out, scope="prime") == ["7203", "8306"]


def test_webapi_prefers_domestic_universe_over_financials(tmp_path: Path, monkeypatch) -> None:
    from investment_assistant.webapi import market

    src = tmp_path / "data_j.csv"
    src.write_bytes(_JPX_CSV.encode("cp932"))
    universe = tmp_path / "domestic_universe.csv"
    ju.build_domestic_universe_csv(src, output_path=universe, scope="domestic")
    monkeypatch.setenv("MARKET_DOMESTIC_UNIVERSE_PATH", str(universe))

    tickers, registry, source = market._resolve_bars_universe({"universe": "domestic"})
    assert registry is None
    assert source == "domestic_universe:domestic"
    assert tickers == ["7203", "8306", "2585", "9468", "130A"]


def test_webapi_falls_back_to_financials_when_universe_absent(monkeypatch) -> None:
    from investment_assistant.webapi import market

    monkeypatch.setenv("MARKET_DOMESTIC_UNIVERSE_PATH", "local_docs/_no_such_universe.csv")
    tickers, registry, source = market._resolve_bars_universe(
        {"universe": "domestic", "financials_csv": "examples/financials_sample.csv"}
    )
    assert registry is None
    assert source.startswith("financials_csv:")
    assert tickers  # non-empty: prior behavior preserved
