from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from investment_assistant.llm.budget_guard import BudgetConfig, BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.chain import ChainLlmService
from investment_assistant.llm.codex_client import CodexUnavailableError
from investment_assistant.llm.factory import CodexRuntimeConfig, build_codex_service
from investment_assistant.llm.service import LlmResponse, LlmService


@dataclass
class FakeCodexClient:
    """No subprocess involved -- a plain fake standing in for CodexCliClient."""

    calls: int = 0
    raise_reason: str | None = None
    marker: str = "CODEX_MARKER 批評result"
    prompts: list[str] = field(default_factory=list)

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self.raise_reason is not None:
            raise CodexUnavailableError(self.raise_reason)
        return self.marker


@dataclass
class FakeGeminiClient:
    calls: int = 0

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        return "GEMINI fallback answer"


def _codex_config(tmp_path: Path, **overrides: object) -> CodexRuntimeConfig:
    defaults = dict(
        enabled=True,
        exe="codex",
        model="",
        timeout_s=180,
        usage_db_path=tmp_path / "codex_usage.sqlite",
        daily_request_limit=10,
        hard_stop_threshold_ratio=1.0,
        cooldown_minutes=30,
    )
    defaults.update(overrides)
    return CodexRuntimeConfig(**defaults)  # type: ignore[arg-type]


def _gemini_fallback_service(tmp_path: Path, client: FakeGeminiClient) -> LlmService:
    return LlmService(
        model="gemini-test",
        client=client,
        cache=LlmCache(tmp_path / "gemini_cache.sqlite"),
        budget_guard=BudgetGuard(
            tmp_path / "gemini_usage.sqlite",
            BudgetConfig(daily_request_limit=1000, monthly_request_limit=10000),
        ),
    )


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
    first = _StaticService(LlmResponse("first answer", "codex_cli", "k1"))
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


# --- Codex provider: success / rate-limit cooldown / daily cap / auth ------


def test_chain_returns_codex_answer_when_codex_succeeds(tmp_path: Path) -> None:
    codex_client = FakeCodexClient()
    codex_service = build_codex_service(
        _codex_config(tmp_path), cache_db_path=tmp_path / "cache.sqlite", client=codex_client
    )
    assert codex_service is not None
    gemini_client = FakeGeminiClient()
    chain = ChainLlmService([codex_service, _gemini_fallback_service(tmp_path, gemini_client)])

    result = chain.generate(task_type="important_report_summary", prompt="critique this")

    assert result.text == "CODEX_MARKER 批評result"
    assert result.source == "codex_cli"
    assert gemini_client.calls == 0


def test_rate_limit_triggers_cooldown_then_skips_without_invoking_codex(tmp_path: Path) -> None:
    codex_client = FakeCodexClient(raise_reason="rate_limit")
    codex_service = build_codex_service(
        _codex_config(tmp_path), cache_db_path=tmp_path / "cache.sqlite", client=codex_client
    )
    assert codex_service is not None
    gemini_client = FakeGeminiClient()
    chain = ChainLlmService([codex_service, _gemini_fallback_service(tmp_path, gemini_client)])

    first = chain.generate(task_type="t", prompt="p1")
    assert first.text == "GEMINI fallback answer"
    assert first.source == "gemini"
    assert codex_client.calls == 1

    # Second call (different prompt, so cache cannot be why codex is skipped)
    # falls to gemini without invoking the codex client at all: cooldown.
    second = chain.generate(task_type="t", prompt="p2 (different prompt)")
    assert second.text == "GEMINI fallback answer"
    assert codex_client.calls == 1  # unchanged: codex was not spawned again


def test_auth_error_falls_through_without_cooldown(tmp_path: Path) -> None:
    codex_client = FakeCodexClient(raise_reason="auth")
    codex_service = build_codex_service(
        _codex_config(tmp_path), cache_db_path=tmp_path / "cache.sqlite", client=codex_client
    )
    assert codex_service is not None
    gemini_client = FakeGeminiClient()
    chain = ChainLlmService([codex_service, _gemini_fallback_service(tmp_path, gemini_client)])

    first = chain.generate(task_type="t", prompt="p1")
    assert first.source == "gemini"
    assert codex_client.calls == 1

    # No cooldown recorded for auth errors, so a second (distinct) prompt
    # reaches the codex client again.
    second = chain.generate(task_type="t", prompt="p2 (different prompt)")
    assert second.source == "gemini"
    assert codex_client.calls == 2


def test_daily_cap_reached_skips_codex_and_falls_to_gemini(tmp_path: Path) -> None:
    codex_client = FakeCodexClient()
    codex_service = build_codex_service(
        _codex_config(tmp_path, daily_request_limit=10),
        cache_db_path=tmp_path / "cache.sqlite",
        client=codex_client,
    )
    assert codex_service is not None
    gemini_client = FakeGeminiClient()
    chain = ChainLlmService([codex_service, _gemini_fallback_service(tmp_path, gemini_client)])

    for index in range(10):
        result = chain.generate(task_type="t", prompt=f"unique prompt {index}")
        assert result.source == "codex_cli"
    assert codex_client.calls == 10

    # 11th distinct prompt: daily cap reached, codex must be skipped (not
    # invoked) and the chain falls through to gemini.
    result = chain.generate(task_type="t", prompt="unique prompt 10")
    assert result.source == "gemini"
    assert codex_client.calls == 10


def test_codex_service_none_when_disabled(tmp_path: Path) -> None:
    service = build_codex_service(
        _codex_config(tmp_path, enabled=False), cache_db_path=tmp_path / "cache.sqlite"
    )
    assert service is None


def test_codex_service_none_when_binary_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "investment_assistant.llm.factory.CodexCliClient",
        _RaisingCodexCliClient,
    )
    service = build_codex_service(_codex_config(tmp_path), cache_db_path=tmp_path / "cache.sqlite")
    assert service is None


class _RaisingCodexCliClient:
    def __init__(self, *_: object, **__: object) -> None:
        raise CodexUnavailableError("error")
