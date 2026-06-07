"""LLM service that centralizes cache, budget, and fallback behavior."""

from __future__ import annotations

from dataclasses import dataclass

from investment_assistant.llm.budget_guard import BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.gemini_client import TextGenerationClient
from investment_assistant.observability import get_logger

_logger = get_logger("llm.service")


@dataclass(frozen=True)
class FallbackConfig:
    """Fallback behavior for Gemini failures and limits."""

    on_daily_limit: str = "local_summary"
    on_monthly_limit: str = "skip_llm"
    on_error: str = "local_summary"


@dataclass(frozen=True)
class LlmResponse:
    """Structured service response."""

    text: str
    source: str
    cache_key: str
    warning: bool = False
    skipped: bool = False


class LlmService:
    """Single approved entry point for Gemini-backed text generation."""

    def __init__(
        self,
        *,
        model: str,
        client: TextGenerationClient,
        cache: LlmCache,
        budget_guard: BudgetGuard,
        fallback: FallbackConfig | None = None,
    ) -> None:
        self.model = model
        self.client = client
        self.cache = cache
        self.budget_guard = budget_guard
        self.fallback = fallback or FallbackConfig()

    def generate(self, *, task_type: str, prompt: str, priority: str = "normal") -> LlmResponse:
        """Generate text through cache, budget guard, and fallback controls."""

        _ = priority
        cache_key = self.cache.make_key(task_type, self.model, prompt)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=True)
            _logger.info(
                "llm cache hit task=%s model=%s key=%s", task_type, self.model, cache_key[:12]
            )
            return LlmResponse(cached, "cache", cache_key)

        decision = self.budget_guard.check(task_type)
        if not decision.allowed:
            _logger.warning(
                "llm budget blocked task=%s reason=%s daily=%d monthly=%d",
                task_type,
                decision.reason,
                decision.daily_count,
                decision.monthly_count,
            )
            return self._fallback_response(decision.reason, prompt, cache_key)

        try:
            text = self.client.generate(prompt, model=self.model)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "llm call failed task=%s model=%s error=%s; using fallback",
                task_type,
                self.model,
                type(exc).__name__,
            )
            return self._fallback_response("error", prompt, cache_key)

        self.cache.set(cache_key, text)
        self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=False)
        _logger.info(
            "llm call ok task=%s model=%s warning=%s", task_type, self.model, decision.warning
        )
        return LlmResponse(text, "gemini", cache_key, warning=decision.warning)

    def _fallback_response(self, reason: str, prompt: str, cache_key: str) -> LlmResponse:
        if reason == "daily_limit_reached":
            mode = self.fallback.on_daily_limit
        elif reason == "monthly_limit_reached":
            mode = self.fallback.on_monthly_limit
        else:
            mode = self.fallback.on_error

        if mode == "local_summary":
            text = self._local_summary(prompt)
            return LlmResponse(text, f"fallback:{mode}:{reason}", cache_key, warning=True)
        return LlmResponse("", f"fallback:{mode}:{reason}", cache_key, warning=True, skipped=True)

    @staticmethod
    def _local_summary(prompt: str, *, max_chars: int = 4000) -> str:
        """Do not expose internal prompts as user answers."""
        if (
            "あなたはアシスタントです" in prompt
            or "以下のドラフト群とレビュー指摘" in prompt
            or "最終回答を作成してください" in prompt
            or "ローカル文書コンテキスト" in prompt
            or "生成プロセス" in prompt
        ):
            return ""

        normalized = " ".join(prompt.split())
        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[: max_chars - 1]}…"


        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[: max_chars - 1]}…"
