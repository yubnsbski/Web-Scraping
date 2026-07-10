from __future__ import annotations

import importlib
import importlib.util
import types

import pytest

from investment_assistant.llm.gemini_client import (
    GeminiApiError,
    GeminiClient,
    WebSource,
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


# --- generate_grounded (Google Search grounding) ----------------------------


class _FakeWeb:
    def __init__(self, uri: object, title: object) -> None:
        self.uri = uri
        self.title = title


class _FakeChunk:
    def __init__(self, web: object) -> None:
        self.web = web


class _FakeGroundingMetadata:
    def __init__(self, chunks: list[object]) -> None:
        self.grounding_chunks = chunks


class _FakeCandidate:
    def __init__(self, grounding_metadata: object) -> None:
        self.grounding_metadata = grounding_metadata


class _FakeResponse:
    def __init__(self, text: object, candidates: list[object]) -> None:
        self.text = text
        self.candidates = candidates


def _install_fake_genai(monkeypatch, generate_content, *, install_sdk: bool = True):
    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return generate_content(model=model, contents=contents, config=config)

    class _FakeClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.models = _FakeModels()

    fake_module = types.SimpleNamespace(Client=_FakeClient)
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: object() if install_sdk else None
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)


def test_generate_grounded_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiClient().generate_grounded("hello", model="gemini-test")


def test_generate_grounded_reports_missing_optional_sdk(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    with pytest.raises(RuntimeError, match="optional Gemini SDK"):
        GeminiClient().generate_grounded("hello", model="gemini-test")


def test_generate_grounded_extracts_sources_and_passes_google_search_tool(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict[str, object] = {}
    response = _FakeResponse(
        "answer text",
        [
            _FakeCandidate(
                _FakeGroundingMetadata(
                    [
                        _FakeChunk(_FakeWeb("https://a.example/", "A")),
                        _FakeChunk(_FakeWeb("https://b.example/", "B")),
                    ]
                )
            )
        ],
    )

    def generate_content(*, model, contents, config):
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config
        return response

    _install_fake_genai(monkeypatch, generate_content)

    result = GeminiClient().generate_grounded("hello", model="gemini-test")

    assert result.text == "answer text"
    assert result.sources == (
        WebSource(url="https://a.example/", title="A"),
        WebSource(url="https://b.example/", title="B"),
    )
    assert captured["config"] == {"tools": [{"google_search": {}}]}
    assert captured["contents"] == "hello"
    assert captured["model"] == "gemini-test"


def test_generate_grounded_missing_grounding_metadata_returns_empty_sources(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    response = _FakeResponse("answer text", [_FakeCandidate(None)])
    _install_fake_genai(monkeypatch, lambda **_: response)

    result = GeminiClient().generate_grounded("hello", model="gemini-test")

    assert result.text == "answer text"
    assert result.sources == ()


def test_generate_grounded_no_candidates_returns_empty_sources(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    response = _FakeResponse("answer text", [])
    _install_fake_genai(monkeypatch, lambda **_: response)

    result = GeminiClient().generate_grounded("hello", model="gemini-test")

    assert result.sources == ()


def test_generate_grounded_chunk_without_web_attr_is_skipped(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    response = _FakeResponse(
        "answer text",
        [_FakeCandidate(_FakeGroundingMetadata([_FakeChunk(None)]))],
    )
    _install_fake_genai(monkeypatch, lambda **_: response)

    result = GeminiClient().generate_grounded("hello", model="gemini-test")

    assert result.sources == ()


def test_generate_grounded_empty_text_raises_empty_response(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    response = _FakeResponse("   ", [])
    _install_fake_genai(monkeypatch, lambda **_: response)

    with pytest.raises(GeminiApiError) as exc_info:
        GeminiClient().generate_grounded("hello", model="gemini-test")
    assert exc_info.value.reason == "empty_response"


def test_generate_grounded_wraps_client_exception_with_classified_reason(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def generate_content(**_kwargs):
        err = RuntimeError("boom")
        err.code = 503  # type: ignore[attr-defined]
        raise err

    _install_fake_genai(monkeypatch, generate_content)

    with pytest.raises(GeminiApiError) as exc_info:
        GeminiClient().generate_grounded("hello", model="gemini-test")
    assert exc_info.value.reason == "server_error"
