from __future__ import annotations

import json
from pathlib import Path

from investment_assistant.webapi.data_quality_profile_artifacts import (
    DataQualityProfileArtifactConfig,
    build_data_quality_profile_artifacts,
)


def _write_profile_sources(root: Path) -> dict[str, str]:
    date_col = "\u65e5\u4ed8"
    code_col = "\u30b3\u30fc\u30c9"
    name_col = "\u9283\u67c4\u540d"
    segment_col = "\u5e02\u5834\u30fb\u5546\u54c1\u533a\u5206"
    sector_col = "33\u696d\u7a2e\u533a\u5206"

    jpx = root / "listed_issues.csv"
    jpx.write_text(
        f'"{date_col}","{code_col}","{name_col}","{segment_col}","{sector_col}"\n'
        f'"20260630","1301","Kyokuyo","\u30d7\u30e9\u30a4\u30e0\uff08\u5185\u56fd\u682a\u5f0f\uff09","Foods"\n'
        f'"20260630","1302","Missing","\u30b9\u30bf\u30f3\u30c0\u30fc\u30c9\uff08\u5185\u56fd\u682a\u5f0f\uff09","Foods"\n'
        '"20260630","1305","ETF","ETF\u30fbETN","-"\n',
        encoding="utf-8",
    )
    company = root / "company_master.csv"
    company.write_text(
        "ticker,name,market_segment_raw,as_of,is_domestic_stock\n"
        "1301,Kyokuyo,Prime domestic,20260630,true\n"
        "1302,Missing,Standard domestic,20260630,true\n"
        "1305,ETF,ETF,20260630,false\n",
        encoding="utf-8",
    )
    universe = root / "domestic_universe.csv"
    universe.write_text(
        "ticker,name,as_of\n1301,Kyokuyo,20260630\n1302,Missing,20260630\n",
        encoding="utf-8",
    )
    prices = root / "current_prices.csv"
    prices.write_text(
        "ticker,price,as_of\n1301,100,2026-07-01\n9999,10,2026-07-01\n",
        encoding="utf-8",
    )
    financials = root / "yahoo_financials.csv"
    financials.write_text("ticker,name,price\n1301,Kyokuyo,100\n", encoding="utf-8")
    bars = root / "daily_bars.csv"
    bars.write_text(
        "ticker,date,open,high,low,close,volume\n"
        "1301,2026-07-01,1,1,1,1,100\n",
        encoding="utf-8-sig",
    )
    return {
        "jpx_listed_issues_path": str(jpx),
        "company_master_path": str(company),
        "domestic_universe_path": str(universe),
        "current_prices_path": str(prices),
        "market_financials_path": str(financials),
        "daily_bars_path": str(bars),
    }


def test_data_quality_profile_artifacts_write_ascii_json_and_mirrors(
    tmp_path: Path,
) -> None:
    request_body = _write_profile_sources(tmp_path)
    output_dir = tmp_path / "public"
    mirror_dir = tmp_path / "mirror"

    payload = build_data_quality_profile_artifacts(
        DataQualityProfileArtifactConfig(
            output_dir=output_dir,
            mirror_dirs=(mirror_dir,),
            request_body=request_body,
            generated_at="2026-07-05T00:00:00+09:00",
        )
    )

    assert payload["summary"]["dimension_count"] == 6
    assert payload["summary"]["jpx_domestic_stock_count"] == 2
    assert payload["external_fetch_executed"] is False
    raw_json = (output_dir / "data_quality_profile.json").read_text(encoding="utf-8")
    assert all(ord(character) < 128 for character in raw_json)
    assert json.loads(raw_json)["title"] == "Data Quality Profile"

    for suffix in ("json", "csv", "html", "md"):
        filename = f"data_quality_profile.{suffix}"
        assert (output_dir / filename).exists()
        assert (mirror_dir / filename).exists()
        assert (output_dir / filename).read_bytes() == (mirror_dir / filename).read_bytes()

    html = (output_dir / "data_quality_profile.html").read_text(encoding="utf-8")
    assert "Data Quality Profile" in html
    assert "No write, no external fetch" in html
