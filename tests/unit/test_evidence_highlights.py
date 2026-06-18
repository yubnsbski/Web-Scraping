"""Unit coverage for structured forecast/feature extraction from RAG chunks."""

from __future__ import annotations

from investment_assistant.rag.search import SearchResult, evidence_highlights


def _result(source: str, text: str, *, index: int = 0) -> SearchResult:
    return SearchResult(
        chunk_id=f"{source}#{index}", source=source, chunk_index=index, score=1.0, text=text
    )


_EVIDENCE = (
    "# トヨタ（7203） 市場データ\n"
    "- 株価: 2000 円\n"
    "特徴: 高配当（利回り≥3.5%） / 低PER（割安圏）\n"
    "予測（統計推定・非助言）: +1営業日 2,100 円 / +5営業日 2,120 円（最良モデル drift）\n"
    "出典: Yahoo!ファイナンスの機械集計。\n"
)


def test_extracts_forecast_tags_and_ticker() -> None:
    [item] = evidence_highlights([_result("local_docs/market/rag/7203.md", _EVIDENCE)])
    assert item["ticker"] == "7203"
    assert item["name"] == "トヨタ"
    assert item["forecast"].startswith("+1営業日 2,100 円")
    assert "高配当" in item["tags"]


def test_skips_chunks_without_forecast_or_tags() -> None:
    plain = _result("docs/readme.md", "# README\n\nNo market evidence here.\n")
    assert evidence_highlights([plain]) == []


def test_dedupes_by_source() -> None:
    out = evidence_highlights(
        [
            _result("rag/7203.md", _EVIDENCE, index=0),
            _result("rag/7203.md", _EVIDENCE, index=1),
        ]
    )
    assert len(out) == 1
