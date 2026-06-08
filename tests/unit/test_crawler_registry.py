from __future__ import annotations

from pathlib import Path

from investment_assistant.crawler.registry import build_crawl_targets_from_registry

_REGISTRY = """
sources:
  - name: "8306_MUFG_ir_crawl"
    ticker: "8306"
    source_type: "issuer_ir"
    method: "crawl"
    allowed: true
    url: "https://www.mufg.jp/ir/"
    url_prefix: "https://www.mufg.jp/ir/"
    allowed_domains: "www.mufg.jp"
  - name: "html_fetch_job_not_crawl"
    ticker: "9432"
    source_type: "issuer_ir"
    method: "html"
    allowed: true
    url: "https://group.ntt/jp/ir/"
  - name: "blocked_not_allowed"
    ticker: "0000"
    source_type: "issuer_ir"
    method: "crawl"
    allowed: false
    url: "https://www.example.com/ir/"
  - name: "broker_crawl_blocked"
    source_type: "broker_public"
    method: "crawl"
    allowed: true
    url: "https://broker.example/ranking/"
"""


def test_build_crawl_targets_selects_only_allowed_issuer_crawl(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(_REGISTRY, encoding="utf-8")

    targets = build_crawl_targets_from_registry(path)
    names = {str(t["name"]) for t in targets}
    assert names == {"8306_MUFG_ir_crawl"}


def test_shipped_crawl_example_parses() -> None:
    example = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "source_registry_crawl_sample.yaml"
    )
    targets = build_crawl_targets_from_registry(example)
    tickers = {str(t.get("ticker")) for t in targets}
    assert tickers == {"8306", "9432"}
