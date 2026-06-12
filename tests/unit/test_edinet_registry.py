from __future__ import annotations

import importlib.util
from pathlib import Path

from investment_assistant.edinet.models import FINANCIAL_DOC_TYPES
from investment_assistant.edinet.registry import build_edinet_targets_from_registry

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_generator():
    path = _REPO_ROOT / "scripts" / "build_nikkei225_edinet_registry.py"
    spec = importlib.util.spec_from_file_location("nikkei225_gen", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_REGISTRY_YAML = """
sources:
  - name: "8306_MUFG_edinet"
    ticker: "8306"
    company: "MUFG"
    source_type: "public_api"
    provider: "edinet"
    method: "api"
    allowed: true
  - name: "7203_toyota_edinet_default_doctypes"
    ticker: "7203"
    company: "トヨタ"
    source_type: "public_api"
    method: "api"
    allowed: true
    doc_types: "120"
    max_periods: 4
  - name: "blocked_not_allowed"
    ticker: "9999"
    source_type: "public_api"
    provider: "edinet"
    method: "api"
    allowed: false
  - name: "ir_html_not_edinet"
    ticker: "9432"
    source_type: "issuer_ir"
    method: "html"
    allowed: true
    url: "https://group.ntt/jp/ir/"
  - name: "other_provider_api"
    ticker: "1111"
    source_type: "public_api"
    provider: "some_other_api"
    method: "api"
    allowed: true
"""


def _write_registry(tmp_path: Path) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(_REGISTRY_YAML, encoding="utf-8")
    return path


def test_build_edinet_targets_selects_only_allowed_edinet_entries(tmp_path: Path) -> None:
    targets = build_edinet_targets_from_registry(_write_registry(tmp_path))
    names = {target.name for target in targets}

    assert names == {"8306_MUFG_edinet", "7203_toyota_edinet_default_doctypes"}


def test_build_edinet_targets_resolves_sec_code_and_doc_types(tmp_path: Path) -> None:
    targets = {t.ticker: t for t in build_edinet_targets_from_registry(_write_registry(tmp_path))}

    mufg = targets["8306"]
    assert mufg.sec_code == "83060"
    assert mufg.company == "MUFG"
    # No explicit doc_types -> defaults to the financial report set.
    assert set(mufg.doc_types) == set(FINANCIAL_DOC_TYPES)

    toyota = targets["7203"]
    assert toyota.doc_types == ("120",)
    assert toyota.max_periods == 4
    # No explicit max_periods -> defaults to 1.
    assert targets["8306"].max_periods == 1


def test_build_edinet_targets_handles_missing_sources(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("other: 1\n", encoding="utf-8")
    assert build_edinet_targets_from_registry(path) == []


def test_shipped_example_registry_parses_with_repo_loader() -> None:
    example = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "source_registry_edinet_sample.yaml"
    )
    targets = {t.ticker: t for t in build_edinet_targets_from_registry(example)}

    assert set(targets) == {"8306", "7203", "9432"}
    assert targets["8306"].doc_types == ("120", "140")
    assert targets["7203"].sec_code == "72030"


def test_shipped_nikkei225_registry_parses_with_repo_loader() -> None:
    example = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "source_registry_nikkei225_edinet.yaml"
    )
    targets = {t.ticker: t for t in build_edinet_targets_from_registry(example)}

    # Near-complete Nikkei 225 coverage, all multi-period annual+quarterly.
    assert len(targets) >= 150
    assert {"7203", "6758", "8306", "9432", "8035", "9984", "4502", "8001"} <= set(targets)
    toyota = targets["7203"]
    assert toyota.doc_types == ("120", "140")
    assert toyota.max_periods == 4
    assert targets["8035"].company == "東京エレクトロン"


def test_nikkei225_registry_is_in_sync_with_generator() -> None:
    generator = _load_generator()
    committed = (
        _REPO_ROOT / "examples" / "source_registry_nikkei225_edinet.yaml"
    ).read_text(encoding="utf-8")
    assert generator.render_yaml() == committed, (
        "examples/source_registry_nikkei225_edinet.yaml is stale; "
        "re-run scripts/build_nikkei225_edinet_registry.py"
    )


def test_nikkei225_generator_has_no_duplicate_tickers() -> None:
    generator = _load_generator()
    tickers = [ticker for ticker, _company in generator.COMPANIES]
    assert len(tickers) == len(set(tickers))


def test_dividend_edinet_run_set_is_valid() -> None:
    # The turnkey dividend run set must keep parsing into usable targets.
    example = _REPO_ROOT / "examples" / "source_registry_dividend_edinet.yaml"
    targets = {t.ticker: t for t in build_edinet_targets_from_registry(example)}
    assert len(targets) == 12
    assert {"8306", "9432", "2914", "8058", "7203"} <= set(targets)
    assert targets["8306"].doc_types == ("120", "140")


def test_dividend_ir_run_set_is_valid() -> None:
    from investment_assistant.crawler.registry import build_crawl_targets_from_registry

    example = _REPO_ROOT / "examples" / "source_registry_dividend_ir.yaml"
    targets = build_crawl_targets_from_registry(example)
    assert len(targets) == 6
    for source in targets:
        url = str(source["url"])
        # Each crawl is locked to its own domain + a same-origin prefix.
        assert str(source["url_prefix"]).startswith("https://")
        assert str(source["allowed_domains"]) in url
        assert url.startswith(str(source["url_prefix"]))




def test_registry_accepts_doc_type_codes_alias(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        """
sources:
  - name: ntt_annual
    ticker: "9432"
    company: NTT
    source_type: public_api
    method: api
    provider: edinet
    allowed: true
    doc_type_codes: ["120"]
    max_periods: 1
""",
        encoding="utf-8",
    )

    targets = build_edinet_targets_from_registry(path)

    assert len(targets) == 1
    assert targets[0].ticker == "9432"
    assert targets[0].doc_types == ("120",)
