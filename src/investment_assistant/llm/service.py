"""LLM service that centralizes cache, budget, and fallback behavior."""

from __future__ import annotations

from dataclasses import dataclass

from investment_assistant.llm.budget_guard import BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.gemini_client import TextGenerationClient


@dataclass(frozen=True)
class FallbackConfig:
    """Fallback behavior for Gemini failures and limits."""

    on_daily_limit: str = "local_summary"
    on_monthly_limit: str = "skip_llm"
    on_error: str = "cached_or_skip"


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

        _ = priority  # Reserved for later priority-aware budgeting.
        cache_key = self.cache.make_key(task_type, self.model, prompt)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=True)
            return LlmResponse(cached, "cache", cache_key)

        decision = self.budget_guard.check(task_type)
        if not decision.allowed:
            return self._fallback_response(decision.reason, prompt, cache_key)

        try:
            text = self.client.generate(prompt, model=self.model)
        except Exception:  # noqa: BLE001 - central service must shield callers and fallback.
            return self._fallback_response("error", prompt, cache_key)

        self.cache.set(cache_key, text)
        self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=False)
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
    def _local_summary(prompt: str, *, max_chars: int = 240) -> str:
        normalized = " ".join(prompt.split())
        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[: max_chars - 1]}…"
