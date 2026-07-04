"""Regression coverage for the bulk daily-bars universe path in webapi.market.

Kept in a separate file (additive / conflict-light) since it pins behavior of
internal helpers that back 「データ更新 → 株価四本値・出来高」.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.webapi import market as market_api
from investment_assistant.webapi.errors import ApiError


@pytest.fixture(autouse=True)
def _isolated_domestic_universe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default to a nonexistent domestic-universe CSV.

    Prevents tests in this module from silently depending on an operator's
    real ``local_docs/market/domestic_universe.csv`` file. Tests that want to
    exercise the domestic-universe branch should override the env var
    themselves.
    """

    monkeypatch.setenv(
        "MARKET_DOMESTIC_UNIVERSE_PATH", str(tmp_path / "no_domestic_universe.csv")
    )


def test_resolve_universe_explicit_tickers() -> None:
    tickers, registry, source = market_api._resolve_bars_universe({"tickers": "8306, 7203"})
    assert tickers == ["8306", "7203"] and registry is None and source == "tickers"


def test_resolve_universe_registry_path() -> None:
    tickers, registry, source = market_api._resolve_bars_universe({"registry_path": "x.yaml"})
    assert tickers == [] and registry == "x.yaml" and source == "registry_path"


def test_resolve_universe_nikkei225_maps_to_bundled_registry() -> None:
    for scope in ("nikkei225", "nikkei_225", "日経225"):
        _, registry, source = market_api._resolve_bars_universe({"universe": scope})
        assert registry is not None and registry.endswith(".yaml")
        assert source == "nikkei225_registry"


def test_resolve_universe_financials_csv_expands_tickers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MARKET_DOMESTIC_UNIVERSE_PATH", str(tmp_path / "no_universe.csv"))
    tickers, registry, source = market_api._resolve_bars_universe(
        {"universe": "all", "financials_csv": "examples/financials_sample.csv"}
    )
    assert registry is None
    assert source.startswith("financials_csv:")
    assert len(tickers) >= 1 and tickers == list(dict.fromkeys(tickers))  # de-duplicated


def test_resolve_universe_unknown_scope_raises() -> None:
    with pytest.raises(ApiError):
        market_api._resolve_bars_universe({"universe": "not-a-real-universe"})


def test_attach_daily_bars_csv_writes_flat_table(tmp_path: Path) -> None:
    out = tmp_path / "daily_bars.csv"
    result = {
        "ohlcv": {
            "8306": [{"date": "2026-06-15", "open": 1.0, "high": 2.0,
                      "low": 0.5, "close": 1.5, "volume": 100}],
            "7203": [{"date": "2026-06-15", "open": 3.0, "high": 4.0,
                      "low": 2.5, "close": 3.5, "volume": 50}],
        }
    }
    market_api._attach_daily_bars_csv(result, str(out))

    assert result["daily_bars_count"] == 2
    assert result["daily_bars_path"] == str(out)
    lines = out.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "ticker,date,open,high,low,close,volume"
    assert "8306,2026-06-15,1.0,2.0,0.5,1.5,100" in lines


def test_attach_daily_bars_csv_without_series_reports_zero(tmp_path: Path) -> None:
    result: dict[str, object] = {"notes": {}}
    market_api._attach_daily_bars_csv(result, str(tmp_path / "x.csv"))
    assert result["daily_bars_count"] == 0
