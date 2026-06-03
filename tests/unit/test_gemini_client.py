from __future__ import annotations

import importlib.util

import pytest

from investment_assistant.llm.gemini_client import GeminiClient


def test_gemini_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiClient().generate("hello", model="gemini-test")


def test_gemini_client_reports_missing_optional_sdk(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    with pytest.raises(RuntimeError, match="optional Gemini SDK"):
        GeminiClient().generate("hello", model="gemini-test")
