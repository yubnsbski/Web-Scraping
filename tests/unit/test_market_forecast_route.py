"""Coverage for the webapi forecast route."""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_assistant.webapi import market as market_api
from investment_assistant.webapi.errors import ApiError

_HEADER = "ticker,date,open,high,low,close,volume\n"


def _bars(tmp_path: Path) -> Path:
    lines = [_HEADER.rstrip("\n")]
    for i in range(20):
        c = 1000 + i * 10
        lines.append(f"7203,2026-05-{i + 1:02d},{c},{c + 5},{c - 5},{c},1000")
    path = tmp_path / "daily_bars.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_market_forecast_route_returns_forecast(tmp_path: Path) -> None:
    path = _bars(tmp_path)
    result = market_api.market_forecast(
        {"ticker": "7203", "daily_bars_csv": str(path), "horizon": 3, "include_ml": False}
    )
    assert result["ticker"] == "7203"
    assert len(result["forecast"]) == 3
    assert result["auto_trading"] is False


def test_market_forecast_route_requires_ticker(tmp_path: Path) -> None:
    with pytest.raises(ApiError, match="ticker is required"):
        market_api.market_forecast({"daily_bars_csv": str(_bars(tmp_path))})


def test_market_forecast_route_missing_csv_raises() -> None:
    with pytest.raises(ApiError, match="daily bars CSV not found"):
        market_api.market_forecast({"ticker": "7203", "daily_bars_csv": "local_docs/_nope.csv"})


def test_market_forecast_route_short_series_is_api_error(tmp_path: Path) -> None:
    path = tmp_path / "daily_bars.csv"
    path.write_text(_HEADER + "7203,2026-05-01,1,1,1,1000,1\n", encoding="utf-8")
    with pytest.raises(ApiError, match="not enough observations"):
        market_api.market_forecast({"ticker": "7203", "daily_bars_csv": str(path)})


def test_market_forecast_screen_route_ranks(tmp_path: Path) -> None:
    lines = [_HEADER.rstrip("\n")]
    for i in range(20):
        up = 1000 + i * 20
        down = 3000 - i * 15
        lines.append(f"7203,2026-05-{i + 1:02d},{up},{up},{up},{up},1")
        lines.append(f"9999,2026-05-{i + 1:02d},{down},{down},{down},{down},1")
    path = tmp_path / "daily_bars.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = market_api.market_forecast_screen(
        {"daily_bars_csv": str(path), "horizon": 5}
    )
    assert result["ranked_count"] == 2
    assert [r["ticker"] for r in result["results"]] == ["7203", "9999"]
    assert result["auto_trading"] is False


def test_market_forecast_screen_route_missing_csv_raises() -> None:
    with pytest.raises(ApiError, match="daily bars CSV not found"):
        market_api.market_forecast_screen({"daily_bars_csv": "local_docs/_nope.csv"})
