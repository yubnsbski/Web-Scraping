"""LLM service that centralizes cache, budget, and fallback behavior."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from investment_assistant.llm.budget_guard import BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.gemini_client import (
    GroundedGenerationClient,
    TextGenerationClient,
    WebSource,
)
from investment_assistant.observability import get_logger

# Reasons worth a short local retry. Only server_error (5xx): the request
# never succeeded, so retrying does not double-spend free-tier quota. An
# empty_response is an HTTP 200 that already consumed quota -- retrying it
# would conflict with the free-tier budget mandate (AGENTS.md), so it falls
# through to the fallback like any other failure. rate_limit needs a
# cooldown, not a retry.
_RETRYABLE_REASONS = frozenset({"server_error"})

_logger = get_logger("llm.service")

_T = TypeVar("_T")


def _call_with_retry(
    call: Callable[[], _T],
    *,
    max_retries: int,
    sleep_fn: Callable[[float], None],
    on_retry: Callable[[int, Exception], None] | None = None,
) -> tuple[_T | None, Exception | None]:
    """Call ``call``, retrying while the failure ``reason`` is retryable.

    Shared by :class:`LlmService` and :class:`GroundedLlmService` so both
    guarded providers apply identical retry/backoff semantics. Returns
    ``(result, None)`` on success, or ``(None, last_exception)`` once
    attempts (``max_retries + 1`` total) are exhausted.
    """

    total_attempts = max_retries + 1
    last_exc: Exception | None = None
    for attempt_index in range(1, total_attempts + 1):
        try:
            return call(), None
        except Exception as exc:  # noqa: BLE001 - classified via getattr below
            last_exc = exc
            reason = getattr(exc, "reason", None)
            if reason in _RETRYABLE_REASONS and attempt_index < total_attempts:
                if on_retry is not None:
                    on_retry(attempt_index, exc)
                sleep_fn(attempt_index * 1.0)
                continue
            break
    return None, last_exc


def _today_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


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


class LlmServiceProtocol(Protocol):
    """Structural type shared by ``LlmService`` and ``ChainLlmService``.

    Orchestration roles depend on this instead of the concrete ``LlmService``
    class so a role can be backed by a single guarded provider or a chain of
    them (see ``llm.chain.ChainLlmService``) without changing call sites.
    """

    def generate(self, *, task_type: str, prompt: str, priority: str = "normal") -> LlmResponse:
        """Generate text for ``task_type``/``prompt``."""


class LlmService:
    """Single approved entry point for guarded (cache/budget/fallback) text generation."""

    def __init__(
        self,
        *,
        model: str,
        client: TextGenerationClient,
        cache: LlmCache,
        budget_guard: BudgetGuard,
        fallback: FallbackConfig | None = None,
        enforce_budget: bool = True,
        provider: str = "gemini",
        cooldown_minutes: int | None = None,
        count_failed_attempts: bool = False,
        max_retries: int = 0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.model = model
        self.client = client
        self.cache = cache
        self.budget_guard = budget_guard
        self.fallback = fallback or FallbackConfig()
        # The budget guard protects the real Gemini free-tier quota. Offline /
        # local clients never call Gemini, so they must not be throttled or
        # counted — otherwise the offline pseudo-AI stops producing output once
        # the daily count is reached.
        self.enforce_budget = enforce_budget
        # Label surfaced on successful responses (``response.source``). Defaults
        # to "gemini" to keep existing callers/tests (which assert that literal
        # string) unchanged; other providers pass their own label.
        self.provider = provider
        # When set, a client error classified as "rate_limit" (via a ``reason``
        # attribute on the raised exception) puts this service's budget guard
        # into cooldown for this many minutes so subsequent calls are skipped
        # without spawning/calling the client.
        self.cooldown_minutes = cooldown_minutes
        # When true, a failed client call is recorded against the daily/monthly
        # budget too (not just successes/cache hits). Off by default so the
        # existing Gemini budget semantics are unchanged.
        self.count_failed_attempts = count_failed_attempts
        # Extra attempts (beyond the first) for transient client failures
        # (reason "server_error" only -- see ``gemini_client.GeminiApiError``
        # and ``_RETRYABLE_REASONS``). 0 (default) preserves today's
        # single-attempt behavior. rate_limit never retries (cooldown instead)
        # and empty_response never retries (it already consumed quota).
        self.max_retries = max_retries
        self.sleep_fn = sleep_fn or time.sleep

    def generate(self, *, task_type: str, prompt: str, priority: str = "normal") -> LlmResponse:
        """Generate text through cache, budget guard, and fallback controls."""

        _ = priority
        cache_key = self.cache.make_key(task_type, self.model, prompt)
        cached = self.cache.get(cache_key)
        if cached is not None:
            if self.enforce_budget:
                self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=True)
            _logger.info(
                "llm cache hit task=%s model=%s key=%s", task_type, self.model, cache_key[:12]
            )
            return LlmResponse(cached, "cache", cache_key)

        warning = False
        if self.enforce_budget:
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
            warning = decision.warning

        def _on_retry(attempt_index: int, exc: Exception) -> None:
            _logger.warning(
                "llm call failed task=%s model=%s attempt=%d reason=%s; retrying",
                task_type,
                self.model,
                attempt_index,
                getattr(exc, "reason", None),
            )

        text, last_exc = _call_with_retry(
            lambda: self.client.generate(prompt, model=self.model),
            max_retries=self.max_retries,
            sleep_fn=self.sleep_fn,
            on_retry=_on_retry,
        )

        if last_exc is not None:
            reason = getattr(last_exc, "reason", None)
            _logger.warning(
                "llm call failed task=%s model=%s error=%s reason=%s; using fallback",
                task_type,
                self.model,
                type(last_exc).__name__,
                reason,
            )
            if self.enforce_budget and self.count_failed_attempts:
                self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=False)
            if self.cooldown_minutes and reason == "rate_limit":
                self.budget_guard.record_cooldown(self.cooldown_minutes)
            return self._fallback_response(reason or "error", prompt, cache_key)

        assert text is not None  # loop only exits with last_exc is None after a success
        self.cache.set(cache_key, text)
        if self.enforce_budget:
            self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=False)
        _logger.info(
            "llm call ok task=%s model=%s warning=%s", task_type, self.model, warning
        )
        return LlmResponse(text, self.provider, cache_key, warning=warning)

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


@dataclass(frozen=True)
class GroundedLlmResponse:
    """Structured response from :class:`GroundedLlmService`, with sources."""

    text: str
    source: str
    cache_key: str
    sources: tuple[WebSource, ...] = ()
    warning: bool = False
    skipped: bool = False


def _encode_grounded_cache_value(text: str, sources: tuple[WebSource, ...]) -> str:
    """Serialize text+sources into the single string ``LlmCache`` stores."""

    return json.dumps(
        {"text": text, "sources": [{"url": s.url, "title": s.title} for s in sources]}
    )


def _decode_grounded_cache_value(raw: str) -> tuple[str, tuple[WebSource, ...]]:
    """Inverse of :func:`_encode_grounded_cache_value`.

    Tolerant of legacy/foreign cache rows that are not the expected JSON
    shape (returns the raw string as text with no sources) so a cache
    format change never turns into a hard failure.
    """

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return raw, ()
    if not isinstance(payload, dict):
        return raw, ()
    text = str(payload.get("text", ""))
    sources_raw = payload.get("sources")
    sources: list[WebSource] = []
    if isinstance(sources_raw, list):
        for item in sources_raw:
            if isinstance(item, dict) and item.get("url"):
                sources.append(WebSource(url=str(item["url"]), title=str(item.get("title", ""))))
    return text, tuple(sources)


class GroundedLlmService:
    """Guarded (cache/budget/fallback) entry point for Web-grounded generation.

    Mirrors :class:`LlmService` (same cache/budget/fallback/retry/cooldown
    semantics, sharing ``_call_with_retry``) but calls
    ``GroundedGenerationClient.generate_grounded`` and carries ``WebSource``
    citations through the cache. The cache key additionally binds
    ``today_fn()`` (UTC date by default) so grounded answers are cached
    per-day rather than for the RAG path's much longer TTL -- Web search
    results go stale daily in a way local RAG documents do not.
    """

    def __init__(
        self,
        *,
        model: str,
        client: GroundedGenerationClient,
        cache: LlmCache,
        budget_guard: BudgetGuard,
        fallback: FallbackConfig | None = None,
        enforce_budget: bool = True,
        provider: str = "gemini_web",
        cooldown_minutes: int | None = None,
        count_failed_attempts: bool = False,
        max_retries: int = 0,
        sleep_fn: Callable[[float], None] | None = None,
        today_fn: Callable[[], str] | None = None,
    ) -> None:
        self.model = model
        self.client = client
        self.cache = cache
        self.budget_guard = budget_guard
        self.fallback = fallback or FallbackConfig()
        self.enforce_budget = enforce_budget
        self.provider = provider
        self.cooldown_minutes = cooldown_minutes
        self.count_failed_attempts = count_failed_attempts
        self.max_retries = max_retries
        self.sleep_fn = sleep_fn or time.sleep
        self.today_fn = today_fn or _today_str

    def generate_grounded(
        self, *, task_type: str, prompt: str, priority: str = "normal"
    ) -> GroundedLlmResponse:
        """Generate Web-grounded text through cache, budget, and fallback controls."""

        _ = priority
        # Freshness: bind today's date into the cache key material so the
        # same query is re-searched daily instead of reusing a stale
        # (up to ``cache_ttl_days``-old) Web answer.
        cache_material = f"{self.today_fn()}\0{prompt}"
        cache_key = self.cache.make_key(task_type, self.model, cache_material)
        cached = self.cache.get(cache_key)
        if cached is not None:
            if self.enforce_budget:
                self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=True)
            _logger.info(
                "llm grounded cache hit task=%s model=%s key=%s",
                task_type,
                self.model,
                cache_key[:12],
            )
            text, sources = _decode_grounded_cache_value(cached)
            return GroundedLlmResponse(text, "cache", cache_key, sources=sources)

        warning = False
        if self.enforce_budget:
            decision = self.budget_guard.check(task_type)
            if not decision.allowed:
                _logger.warning(
                    "llm grounded budget blocked task=%s reason=%s daily=%d monthly=%d",
                    task_type,
                    decision.reason,
                    decision.daily_count,
                    decision.monthly_count,
                )
                return self._fallback_response(decision.reason, cache_key)
            warning = decision.warning

        def _on_retry(attempt_index: int, exc: Exception) -> None:
            _logger.warning(
                "llm grounded call failed task=%s model=%s attempt=%d reason=%s; retrying",
                task_type,
                self.model,
                attempt_index,
                getattr(exc, "reason", None),
            )

        result, last_exc = _call_with_retry(
            lambda: self.client.generate_grounded(prompt, model=self.model),
            max_retries=self.max_retries,
            sleep_fn=self.sleep_fn,
            on_retry=_on_retry,
        )

        if last_exc is not None:
            reason = getattr(last_exc, "reason", None)
            _logger.warning(
                "llm grounded call failed task=%s model=%s error=%s reason=%s; using fallback",
                task_type,
                self.model,
                type(last_exc).__name__,
                reason,
            )
            if self.enforce_budget and self.count_failed_attempts:
                self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=False)
            if self.cooldown_minutes and reason == "rate_limit":
                self.budget_guard.record_cooldown(self.cooldown_minutes)
            return self._fallback_response(reason or "error", cache_key)

        assert result is not None  # loop only exits with last_exc is None after a success
        self.cache.set(cache_key, _encode_grounded_cache_value(result.text, result.sources))
        if self.enforce_budget:
            self.budget_guard.record_call(task_type, self.model, cache_key, cache_hit=False)
        _logger.info(
            "llm grounded call ok task=%s model=%s warning=%s sources=%d",
            task_type,
            self.model,
            warning,
            len(result.sources),
        )
        return GroundedLlmResponse(
            result.text, self.provider, cache_key, sources=result.sources, warning=warning
        )

    def _fallback_response(self, reason: str, cache_key: str) -> GroundedLlmResponse:
        # Unlike LlmService, a Web-grounded fallback never synthesizes a
        # local_summary text (there is no local context to summarize into a
        # citation-free answer) -- it always skips, and the caller
        # (``websearch.answer.generate_web_answer``) supplies the graceful
        # Japanese fallback message.
        if reason == "daily_limit_reached":
            mode = self.fallback.on_daily_limit
        elif reason == "monthly_limit_reached":
            mode = self.fallback.on_monthly_limit
        else:
            mode = self.fallback.on_error
        return GroundedLlmResponse(
            "", f"fallback:{mode}:{reason}", cache_key, warning=True, skipped=True
        )
