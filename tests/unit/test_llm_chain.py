from __future__ import annotations

import pytest

from investment_assistant.llm.chain import ChainLlmService
from investment_assistant.llm.service import LlmResponse

# --- Generic ChainLlmService behavior -------------------------------------


class _StaticService:
    def __init__(self, response: LlmResponse) -> None:
        self.response = response
        self.calls = 0

    def generate(self, *, task_type: str, prompt: str, priority: str = "normal") -> LlmResponse:
        self.calls += 1
        return self.response


def test_chain_requires_at_least_one_service() -> None:
    with pytest.raises(ValueError):
        ChainLlmService([])


def test_chain_returns_first_usable_response() -> None:
    first = _StaticService(LlmResponse("first answer", "local", "k1"))
    second = _StaticService(LlmResponse("second answer", "gemini", "k2"))
    chain = ChainLlmService([first, second])

    result = chain.generate(task_type="t", prompt="p")

    assert result.text == "first answer"
    assert second.calls == 0


def test_chain_falls_through_on_skipped_response() -> None:
    first = _StaticService(LlmResponse("", "fallback:skip_llm:error", "k1", skipped=True))
    second = _StaticService(LlmResponse("second answer", "gemini", "k2"))
    chain = ChainLlmService([first, second])

    result = chain.generate(task_type="t", prompt="p")

    assert result.text == "second answer"
    assert second.calls == 1


def test_chain_falls_through_on_fallback_sourced_response() -> None:
    # Not marked skipped, but fallback-sourced (e.g. local_summary) -- still
    # should not be treated as a genuine provider answer.
    first = _StaticService(LlmResponse("raw prompt text", "fallback:local_summary:error", "k1"))
    second = _StaticService(LlmResponse("second answer", "gemini", "k2"))
    chain = ChainLlmService([first, second])

    result = chain.generate(task_type="t", prompt="p")

    assert result.text == "second answer"


def test_chain_returns_last_response_even_if_fallback() -> None:
    only = _StaticService(LlmResponse("", "fallback:skip_llm:error", "k1", skipped=True))
    chain = ChainLlmService([only])

    result = chain.generate(task_type="t", prompt="p")

    assert result.skipped is True
    assert result.source == "fallback:skip_llm:error"
