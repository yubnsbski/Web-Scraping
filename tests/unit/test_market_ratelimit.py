from __future__ import annotations

import json

import pytest

from investment_assistant.portfolio._market_common import (
    DEFAULT_RATE_LIMIT,
    RateLimitPolicy,
    fetch_once,
    pause_after,
    request_with_retry,
    unique_tickers,
)
from investment_assistant.portfolio.ohlcv import fetch_ohlcv


def _ohlcv_payload(date: str = "2026-06-15") -> str:
    ts = 1781913600  # arbitrary; only count matters here
    return json.dumps(
        {"chart": {"result": [{"meta": {"gmtoffset": 0}, "timestamp": [ts],
                               "indicators": {"quote": [{"open": [1.0], "high": [1.0],
                                                         "low": [1.0], "close": [1.0],
                                                         "volume": [1]}]}}], "error": None}}
    )


def test_default_policy_is_conservative() -> None:
    assert DEFAULT_RATE_LIMIT.sleep_between >= 2.0
    assert DEFAULT_RATE_LIMIT.max_retries >= 2


def test_unique_tickers_trims_dedupes_and_preserves_order() -> None:
    assert unique_tickers([" 8306 ", "7203", "8306", "", "  "]) == ["8306", "7203"]


def test_request_with_retry_retries_on_exception_then_succeeds() -> None:
    calls = {"n": 0}
    waits: list[float] = []

    def flaky(url: str) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "OK"

    policy = RateLimitPolicy(max_retries=3, retry_base_wait=10.0)
    body = request_with_retry(flaky, "u", policy=policy, sleeper=waits.append)

    assert body == "OK"
    assert calls["n"] == 3
    # Linear backoff between attempts: 10, 20 (no wait after the final success).
    assert waits == [10.0, 20.0]


def test_request_with_retry_treats_empty_body_as_rate_limit() -> None:
    waits: list[float] = []
    policy = RateLimitPolicy(max_retries=2, retry_base_wait=5.0)
    # Always-empty responses exhaust retries and return "" (no exception raised).
    body = request_with_retry(lambda u: "   ", "u", policy=policy, sleeper=waits.append)
    assert body == ""
    assert waits == [5.0]  # one backoff between the two attempts


def test_request_with_retry_raises_after_exhausting_exceptions() -> None:
    policy = RateLimitPolicy(max_retries=2, retry_base_wait=0.0)

    def always_fail(url: str) -> str:
        raise TimeoutError("nope")

    with pytest.raises(TimeoutError):
        request_with_retry(always_fail, "u", policy=policy, sleeper=lambda _s: None)


def test_pause_after_uses_batch_pause_on_boundaries() -> None:
    waits: list[float] = []
    policy = RateLimitPolicy(sleep_between=2.0, batch_size=2, sleep_between_batches=30.0)
    # total=5; pause after each item except the last.
    for i in range(5):
        pause_after(i, 5, policy=policy, sleeper=waits.append)
    # boundaries after index 1 and 3 -> batch pause; others -> per-request; none after last.
    assert waits == [2.0, 30.0, 2.0, 30.0]


def test_fetch_once_raw_when_no_policy() -> None:
    seen: list[str] = []
    assert fetch_once(lambda u: (seen.append(u), "body")[1], "u", policy=None) == "body"
    assert seen == ["u"]


def test_fetch_ohlcv_with_policy_spaces_requests_and_retries() -> None:
    waits: list[float] = []
    attempts: dict[str, int] = {}

    def fetch(url: str) -> str:
        attempts[url] = attempts.get(url, 0) + 1
        if "7203" in url and attempts[url] == 1:
            raise ConnectionError("429-ish")  # first attempt fails, retried
        return _ohlcv_payload()

    policy = RateLimitPolicy(sleep_between=2.0, max_retries=2, retry_base_wait=10.0)
    result = fetch_ohlcv(["8306", "7203"], fetch=fetch, rate_limit=policy, sleeper=waits.append)

    assert result["counts"] == {"8306": 1, "7203": 1}
    # 8306: ok (no retry). Between tickers: one 2.0 spacing. 7203: one retry backoff 10.0.
    assert 2.0 in waits and 10.0 in waits
    url_7203 = "https://query1.finance.yahoo.com/v8/finance/chart/7203.T?range=1mo&interval=1d"
    assert attempts[url_7203] == 2  # first attempt failed, retried once
