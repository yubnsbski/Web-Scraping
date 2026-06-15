from __future__ import annotations

from collections.abc import Mapping

from investment_assistant.jquants.client import (
    JQuantsApiError,
    JQuantsClient,
    candidate_equity_codes,
    normalize_equity_code,
)


def test_normalize_equity_code_appends_issue_type_digit() -> None:
    assert normalize_equity_code("8306") == "83060"
    assert normalize_equity_code("86970") == "86970"


def test_candidate_equity_codes_include_visible_and_issue_type_codes() -> None:
    assert candidate_equity_codes("9433") == ("94330", "9433")
    assert candidate_equity_codes("9433.T") == ("94330", "9433")
    assert candidate_equity_codes("86970") == ("86970", "8697")


def test_fetch_latest_prices_uses_v2_api_key_and_latest_close() -> None:
    captured: dict[str, object] = {}

    def fake_fetch(
        path: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> dict[str, object]:
        captured["path"] = path
        captured["params"] = dict(params)
        captured["headers"] = dict(headers)
        return {
            "bars": [
                {"Code": "83060", "Date": "2026-06-12", "Close": 1200},
                {"Code": "83060", "Date": "2026-06-15", "Close": 1234.5},
            ],
        }

    client = JQuantsClient(api_key="unit-key", fetch_json=fake_fetch)

    result = client.fetch_latest_prices(["8306"], lookback_days=3)

    assert result["prices"] == {"8306": 1234.5}
    assert result["as_of"] == {"8306": "2026-06-15"}
    assert captured["path"] == "/equities/bars/daily"
    assert captured["params"]["code"] == "83060"  # type: ignore[index]
    assert captured["headers"]["x-api-key"] == "unit-key"  # type: ignore[index]
    assert result["auto_trading"] is False


def test_fetch_latest_prices_falls_back_to_visible_four_digit_code() -> None:
    tried: list[str] = []

    def fake_fetch(
        path: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> dict[str, object]:
        tried.append(params["code"])
        if params["code"] == "94330":
            raise JQuantsApiError("J-Quants API returned HTTP 400 for test")
        return {
            "daily_bars": [
                {"Code": "9433", "Date": "2026-06-12", "Close": 4970},
            ],
        }

    client = JQuantsClient(api_key="unit-key", fetch_json=fake_fetch)

    result = client.fetch_latest_prices(["9433"], lookback_days=3)

    assert tried == ["94330", "9433"]
    assert result["prices"] == {"9433": 4970.0}
    assert result["as_of"] == {"9433": "2026-06-12"}


def test_fetch_latest_prices_retries_inside_subscription_window() -> None:
    tried: list[dict[str, str]] = []

    def fake_fetch(
        path: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> dict[str, object]:
        _ = path, headers
        tried.append(dict(params))
        if params.get("to") != "20260324":
            raise JQuantsApiError(
                "Your subscription covers the following dates: 2024-03-24 ~ 2026-03-24."
            )
        return {
            "bars": [
                {"Code": "72030", "Date": "2026-03-24", "Close": 2890},
            ],
        }

    client = JQuantsClient(api_key="unit-key", fetch_json=fake_fetch)

    result = client.fetch_latest_prices(["7203"], lookback_days=5)

    assert tried[0]["code"] == "72030"
    assert tried[1]["from"] == "20260319"
    assert tried[1]["to"] == "20260324"
    assert result["prices"] == {"7203": 2890.0}
    assert result["as_of"] == {"7203": "2026-03-24"}
    assert "subscription_window_used" in result["notes"]["7203"]  # type: ignore[index]


def test_fetch_daily_bars_returns_normalized_ohlcv_summary() -> None:
    captured: dict[str, object] = {}

    def fake_fetch(
        path: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> dict[str, object]:
        captured["path"] = path
        captured["params"] = dict(params)
        captured["headers"] = dict(headers)
        return {
            "data": [
                {
                    "Date": "2026-06-12",
                    "Code": "94330",
                    "O": 4900,
                    "H": 5010,
                    "L": 4890,
                    "C": 4970,
                    "Vo": 1200000,
                    "Va": 5964000000,
                    "AdjC": 4970,
                },
                {
                    "Date": "2026-06-15",
                    "Code": "94330",
                    "O": 4970,
                    "H": 5020,
                    "L": 4950,
                    "C": 5000,
                    "Vo": 1300000,
                    "Va": 6500000000,
                    "AdjC": 5000,
                },
            ],
        }

    client = JQuantsClient(api_key="unit-key", fetch_json=fake_fetch)

    result = client.fetch_daily_bars(["9433"], lookback_days=5)

    assert captured["path"] == "/equities/bars/daily"
    assert captured["params"]["code"] == "94330"  # type: ignore[index]
    assert len(result["bars"]) == 2
    assert result["bars"][0]["ticker"] == "9433"
    assert result["bars"][0]["volume"] == 1200000.0
    summary = result["summary"]["tickers"]["9433"]  # type: ignore[index]
    assert summary["latest_close"] == 5000.0
    assert summary["return_pct"] == 0.603622


def test_fetch_daily_bars_bulk_uses_date_range_and_pagination() -> None:
    calls: list[dict[str, str]] = []

    def fake_fetch(
        path: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> dict[str, object]:
        _ = path, headers
        calls.append(dict(params))
        if "pagination_key" not in params:
            return {
                "data": [
                    {"Date": "2026-06-15", "Code": "72030", "C": 3271, "Vo": 100},
                    {"Date": "2026-06-15", "Code": "99990", "C": 100, "Vo": 10},
                ],
                "pagination_key": "next-page",
            }
        return {
            "data": [
                {"Date": "2026-06-15", "Code": "94330", "C": 2677.5, "Vo": 200},
            ],
        }

    client = JQuantsClient(api_key="unit-key", fetch_json=fake_fetch)

    result = client.fetch_daily_bars_bulk(["7203", "9433"], lookback_days=3)

    assert len(calls) == 2
    assert "code" not in calls[0]
    assert calls[1]["pagination_key"] == "next-page"
    assert result["fetch_mode"] == "bulk_date_range"
    assert result["pages_fetched"] == 2
    assert result["rows_returned"] == 3
    assert result["matched_ticker_count"] == 2
    assert [row["ticker"] for row in result["bars"]] == ["7203", "9433"]


def test_fetch_daily_bars_retries_inside_subscription_window() -> None:
    tried: list[dict[str, str]] = []

    def fake_fetch(
        path: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> dict[str, object]:
        _ = path, headers
        tried.append(dict(params))
        if params.get("to") != "20260324":
            raise JQuantsApiError(
                "Your subscription covers the following dates: 2024-03-24 ~ 2026-03-24."
            )
        return {
            "data": [
                {
                    "Date": "2026-03-24",
                    "Code": "94330",
                    "O": 4800,
                    "H": 5010,
                    "L": 4790,
                    "C": 4970,
                    "Vo": 1200000,
                    "AdjC": 4970,
                },
            ],
        }

    client = JQuantsClient(api_key="unit-key", fetch_json=fake_fetch)

    result = client.fetch_daily_bars(["9433"], lookback_days=7)

    assert tried[1]["from"] == "20260317"
    assert tried[1]["to"] == "20260324"
    assert len(result["bars"]) == 1
    assert result["bars"][0]["date"] == "2026-03-24"
    assert "subscription_window_used" in result["notes"]["9433"]  # type: ignore[index]
