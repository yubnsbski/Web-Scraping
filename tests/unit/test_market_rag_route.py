"""Coverage for the webapi route that builds RAG evidence from market CSVs."""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.webapi import market as market_api
from investment_assistant.webapi.errors import ApiError

_FIN_CSV = (
    "ticker,name,price,per,pbr,dps,dividend_yield,dividend_yield_percent,eps,market_cap\n"
    "9433,KDDI,2708,13.5,1.2,140,0.032,3.2,200,6300000000000\n"
    "8306,MUFG,1800,11.0,0.9,60,0.033,3.3,160,1000000000000\n"
)


def test_market_rag_build_writes_and_indexes(tmp_path: Path) -> None:
    fin = tmp_path / "yahoo_financials.csv"
    fin.write_text(_FIN_CSV, encoding="utf-8")
    out = tmp_path / "rag"
    db = tmp_path / "rag.sqlite"

    result = market_api.market_rag_build(
        {
            "financials_csv": str(fin),
            "output_dir": str(out),
            "db_path": str(db),
        }
    )

    assert result["documents_written"] == 2
    assert sorted(p.name for p in out.glob("*.md")) == ["8306.md", "9433.md"]
    # index_after_build defaults to True -> the store is populated.
    assert isinstance(result.get("index"), dict)
    assert result["index"]["files_indexed"] == 2
    assert db.is_file()


def test_market_rag_build_can_skip_indexing(tmp_path: Path) -> None:
    fin = tmp_path / "yahoo_financials.csv"
    fin.write_text(_FIN_CSV, encoding="utf-8")
    out = tmp_path / "rag"

    result = market_api.market_rag_build(
        {"financials_csv": str(fin), "output_dir": str(out), "index_after_build": False}
    )

    assert result["documents_written"] == 2
    assert "index" not in result


def test_market_rag_build_missing_csv_raises() -> None:
    with pytest.raises(ApiError, match="financials CSV not found"):
        market_api.market_rag_build({"financials_csv": "local_docs/_nope_financials.csv"})
