from __future__ import annotations

from investment_assistant.portfolio import _market_common as market_common


class _Doc:
    html = "body"


def test_default_market_fetch_respects_robots_by_default(monkeypatch) -> None:
    calls: list[bool] = []

    class FakeFetcher:
        def fetch_document(self, url: str, *, respect_robots: bool = True) -> _Doc:
            calls.append(respect_robots)
            return _Doc()

    monkeypatch.delenv(market_common.MARKET_ROBOTS_BYPASS_ENV, raising=False)
    monkeypatch.setattr(market_common, "SafeFetcher", FakeFetcher)

    assert market_common.default_fetch("https://query1.finance.yahoo.com/x") == "body"
    assert calls == [True]


def test_default_market_fetch_can_opt_into_personal_use_robots_bypass(monkeypatch) -> None:
    calls: list[bool] = []

    class FakeFetcher:
        def fetch_document(self, url: str, *, respect_robots: bool = True) -> _Doc:
            calls.append(respect_robots)
            return _Doc()

    monkeypatch.setenv(market_common.MARKET_ROBOTS_BYPASS_ENV, "1")
    monkeypatch.setattr(market_common, "SafeFetcher", FakeFetcher)

    assert market_common.robots_bypass_enabled() is True
    assert market_common.default_fetch("https://query1.finance.yahoo.com/x") == "body"
    assert calls == [False]
