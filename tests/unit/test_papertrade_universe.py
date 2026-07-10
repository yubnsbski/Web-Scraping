"""Unit tests for :mod:`investment_assistant.papertrade.universe`.

Uses small synthetic CSV fixtures written to ``tmp_path`` -- never the real
``local_docs`` data files (offline-first, per ``AGENTS.md``).
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.papertrade.universe import (
    DEFENSIVE_SECTORS,
    Bar,
    SectorInfo,
    build_universe,
    is_defensive,
    load_daily_bars,
    load_sector_map,
)

_BARS_CSV = (
    "﻿ticker,date,open,high,low,close,volume\n"
    "1000,2026-01-05,100.0,101.0,99.0,100.0,1000\n"
    "1000,2026-01-06,100.0,101.0,99.0,101.0,1100\n"
    "1000,2026-01-07,101.0,102.0,100.0,,1200\n"  # missing close -> skipped
    "1000,2026-01-08,101.0,102.0,100.0,0,1200\n"  # non-positive close -> skipped
    "1000,2026-01-09,101.0,102.0,100.0,102.0,1300\n"
    "2000,2026-01-06,200.0,201.0,199.0,200.0,500\n"
    "9999,2026-01-06,bad,101.0,99.0,50.0,100\n"  # unparsable open -> skipped
)

_JPX_CSV = (
    "﻿日付,コード,銘柄名,市場・商品区分,33業種コード,33業種区分,17業種コード,17業種区分,規模コード,規模区分\n"
    "20260531,1000,テスト電力,プライム（内国株式）,50,電気・ガス業,1,X,6,Y\n"
    "20260531,2000,テストETF,ETF・ETN,-,-,-,-,-,-\n"
    "20260531,3000,テスト外国株,外国株式,50,-,-,-,-,-\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_daily_bars_skips_missing_and_non_positive_close(tmp_path: Path) -> None:
    csv_path = _write(tmp_path / "daily_bars.csv", _BARS_CSV)
    bars = load_daily_bars(csv_path)

    assert set(bars) == {"1000", "2000"}
    assert [bar.date for bar in bars["1000"]] == ["2026-01-05", "2026-01-06", "2026-01-09"]
    assert bars["1000"][0] == Bar(
        ticker="1000", date="2026-01-05", open=100.0, high=101.0, low=99.0, close=100.0,
        volume=1000,
    )
    assert "9999" not in bars  # unparsable open dropped defensively


def test_load_daily_bars_sorts_by_date(tmp_path: Path) -> None:
    text = (
        "ticker,date,open,high,low,close,volume\n"
        "1000,2026-01-09,1,1,1,10.0,1\n"
        "1000,2026-01-05,1,1,1,5.0,1\n"
        "1000,2026-01-07,1,1,1,7.0,1\n"
    )
    csv_path = _write(tmp_path / "bars.csv", text)
    bars = load_daily_bars(csv_path)
    assert [bar.date for bar in bars["1000"]] == ["2026-01-05", "2026-01-07", "2026-01-09"]


def test_load_sector_map_filters_to_domestic_stock(tmp_path: Path) -> None:
    csv_path = _write(tmp_path / "jpx.csv", _JPX_CSV)
    sectors = load_sector_map(csv_path)

    assert set(sectors) == {"1000"}
    assert sectors["1000"] == SectorInfo(
        ticker="1000", name="テスト電力", sector33="電気・ガス業", market="プライム（内国株式）"
    )


def test_defensive_sectors_helper() -> None:
    expected = frozenset({"電気・ガス業", "情報・通信業", "食料品", "医薬品", "陸運業"})
    assert expected == DEFENSIVE_SECTORS
    assert is_defensive("電気・ガス業") is True
    assert is_defensive("鉄鋼") is False


def test_build_universe_requires_min_history_before_as_of() -> None:
    bars = {
        "1000": [
            Bar("1000", f"2026-01-{d:02d}", 1, 1, 1, 1, 1) for d in range(1, 11)
        ],
        "2000": [
            Bar("2000", f"2026-01-{d:02d}", 1, 1, 1, 1, 1) for d in range(1, 4)
        ],
        "3000": [
            Bar("3000", f"2026-01-{d:02d}", 1, 1, 1, 1, 1) for d in range(1, 11)
        ],  # not in sectors
    }
    sectors = {
        "1000": SectorInfo("1000", "A", "電気・ガス業", "プライム（内国株式）"),
        "2000": SectorInfo("2000", "B", "鉄鋼", "プライム（内国株式）"),
    }
    universe = build_universe(bars, sectors, min_history=5, as_of="2026-01-10")
    assert universe == ["1000"]


def test_build_universe_only_counts_bars_strictly_before_as_of() -> None:
    bars = {
        "1000": [Bar("1000", f"2026-01-{d:02d}", 1, 1, 1, 1, 1) for d in range(1, 6)],
    }
    sectors = {"1000": SectorInfo("1000", "A", "医薬品", "プライム（内国株式）")}
    # 5 bars total, but as_of=2026-01-05 means only 4 bars are strictly before it.
    assert build_universe(bars, sectors, min_history=5, as_of="2026-01-05") == []
    assert build_universe(bars, sectors, min_history=4, as_of="2026-01-05") == ["1000"]
