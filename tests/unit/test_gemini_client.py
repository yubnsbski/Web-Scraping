from __future__ import annotations

import importlib.util

import pytest

from investment_assistant.llm.gemini_client import (
    GeminiApiError,
    GeminiClient,
    _classify_gemini_error,
)


class _FakeExcWithCode(Exception):
    def __init__(self, code: object) -> None:
        super().__init__("boom")
        self.code = code


class _FakeExcWithStatusCode(Exception):
    def __init__(self, status_code: object) -> None:
        super().__init__("boom")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("code", "expected_reason"),
    [
        (429, "rate_limit"),
        (500, "server_error"),
        (503, "server_error"),
        (599, "server_error"),
        (404, None),
        (None, None),
        # SDK/transport layers sometimes report the status as a string.
        ("429", "rate_limit"),
        ("503", "server_error"),
        ("not-a-code", None),
    ],
)
def test_classify_gemini_error_from_code_attribute(code, expected_reason) -> None:
    assert _classify_gemini_error(_FakeExcWithCode(code)) == expected_reason


@pytest.mark.parametrize(
    ("status_code", "expected_reason"),
    [
        (429, "rate_limit"),
        (503, "server_error"),
        (400, None),
    ],
)
def test_classify_gemini_error_from_status_code_attribute(status_code, expected_reason) -> None:
    assert _classify_gemini_error(_FakeExcWithStatusCode(status_code)) == expected_reason


def test_gemini_api_error_carries_reason() -> None:
    err = GeminiApiError("boom", reason="server_error")
    assert err.reason == "server_error"
    assert isinstance(err, RuntimeError)


def test_gemini_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiClient().generate("hello", model="gemini-test")


def test_gemini_client_reports_missing_optional_sdk(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    with pytest.raises(RuntimeError, match="optional Gemini SDK"):
        GeminiClient().generate("hello", model="gemini-test")
