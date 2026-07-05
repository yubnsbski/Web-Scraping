from __future__ import annotations

import csv
import json
from pathlib import Path

from investment_assistant.webapi.source_cleansing_preview import (
    SourceCleansingPreviewConfig,
    build_source_cleansing_preview,
)


def _write_sources(root: Path) -> dict[str, Path]:
    reference = root / "domestic_universe.csv"
    reference.write_text(
        "ticker,name,segment\n"
        "1301,Kyokuyo,Prime\n"
        "1302,Needs Fill,Standard\n",
        encoding="utf-8",
    )
    current_prices = root / "current_prices.csv"
    current_prices.write_text(
        "ticker,price,as_of\n"
        "1301,100,2026-07-01\n"
        "9999,10,2026-07-01\n"
        "9999,11,2026-07-02\n",
        encoding="utf-8",
    )
    market_financials = root / "yahoo_financials.csv"
    market_financials.write_text(
        "ticker,name,price\n"
        "1301,Kyokuyo,100\n"
        "1302,Needs Fill,200\n",
        encoding="utf-8",
    )
    return {
        "reference": reference,
        "current_prices": current_prices,
        "market_financials": market_financials,
    }


def test_source_cleansing_preview_filters_to_reference_without_touching_raw(
    tmp_path: Path,
) -> None:
    paths = _write_sources(tmp_path)
    raw_before = paths["current_prices"].read_text(encoding="utf-8")
    output_dir = tmp_path / "public"
    mirror_dir = tmp_path / "mirror"

    payload = build_source_cleansing_preview(
        SourceCleansingPreviewConfig(
            output_dir=output_dir,
            reference_universe_path=paths["reference"],
            current_prices_path=paths["current_prices"],
            market_financials_path=paths["market_financials"],
            mirror_dirs=(mirror_dir,),
            generated_at="2026-07-05T00:00:00+09:00",
        )
    )

    assert payload["status"] == "needs_attention"
    assert payload["summary"]["reference_count"] == 2
    assert payload["summary"]["source_count"] == 2
    assert payload["summary"]["total_dropped_row_count"] == 2
    assert payload["summary"]["total_dropped_ticker_count"] == 1
    assert payload["summary"]["total_missing_ticker_count"] == 1
    assert payload["summary"]["source_data_write_executed"] is False
    assert payload["summary"]["external_fetch_executed"] is False
    assert payload["summary"]["auto_trading"] is False
    assert payload["summary"]["call_real_api"] is False

    current = {source["source_id"]: source for source in payload["sources"]}[
        "current_prices"
    ]
    assert current["raw_row_count"] == 3
    assert current["clean_preview_row_count"] == 1
    assert current["dropped_row_count"] == 2
    assert current["dropped_ticker_count"] == 1
    assert current["missing_ticker_sample"] == ["1302"]
    assert current["dropped_ticker_sample"] == ["9999"]
    assert current["source_data_write_executed"] is False

    preview_path = output_dir / "current_prices_jpx_domestic_clean_preview.csv"
    with preview_path.open(encoding="utf-8", newline="") as handle:
        preview_rows = list(csv.DictReader(handle))
    assert [row["ticker"] for row in preview_rows] == ["1301"]
    assert paths["current_prices"].read_text(encoding="utf-8") == raw_before

    raw_json = (output_dir / "source_cleansing_preview.json").read_text(
        encoding="utf-8"
    )
    assert all(ord(character) < 128 for character in raw_json)
    assert json.loads(raw_json)["title"] == "Source Cleansing Preview"
    assert "Source Cleansing Preview" in (
        output_dir / "source_cleansing_preview.html"
    ).read_text(encoding="utf-8")

    for filename in (
        "source_cleansing_preview.json",
        "source_cleansing_preview.csv",
        "source_cleansing_preview.html",
        "source_cleansing_preview.md",
        "current_prices_jpx_domestic_clean_preview.csv",
        "market_financials_jpx_domestic_clean_preview.csv",
    ):
        assert (output_dir / filename).exists()
        assert (mirror_dir / filename).exists()
        assert (output_dir / filename).read_bytes() == (
            mirror_dir / filename
        ).read_bytes()


def test_source_cleansing_preview_passes_when_sources_match_reference(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "domestic_universe.csv"
    reference.write_text("ticker,name\n1301,Kyokuyo\n1302,Other\n", encoding="utf-8")
    current_prices = tmp_path / "current_prices.csv"
    current_prices.write_text(
        "ticker,price\n1301,100\n1302,200\n",
        encoding="utf-8",
    )
    market_financials = tmp_path / "yahoo_financials.csv"
    market_financials.write_text(
        "ticker,price\n1301,100\n1302,200\n",
        encoding="utf-8",
    )

    payload = build_source_cleansing_preview(
        SourceCleansingPreviewConfig(
            output_dir=tmp_path / "public",
            reference_universe_path=reference,
            current_prices_path=current_prices,
            market_financials_path=market_financials,
            generated_at="2026-07-05T00:00:00+09:00",
        )
    )

    assert payload["status"] == "ready"
    assert payload["summary"]["source_with_changes_count"] == 0
    assert payload["summary"]["total_dropped_row_count"] == 0
    assert payload["summary"]["total_missing_ticker_count"] == 0
