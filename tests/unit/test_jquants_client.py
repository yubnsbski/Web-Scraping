from __future__ import annotations

from collections.abc import Mapping

from investment_assistant.jquants.client import JQuantsClient, normalize_equity_code


def test_normalize_equity_code_appends_issue_type_digit() -> None:
    assert normalize_equity_code("8306") == "83060"
    assert normalize_equity_code("86970") == "86970"


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
