"""Factory helpers for constructing the guarded LLM service from YAML config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investment_assistant.config.loader import load_yaml
from investment_assistant.llm.budget_guard import BudgetConfig, BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.gemini_client import GeminiClient, TextGenerationClient
from investment_assistant.llm.service import FallbackConfig, LlmService
from investment_assistant.observability import get_logger

_logger = get_logger("llm.factory")

DEFAULT_GEMINI_CONFIG_PATH = Path("config/gemini.yaml")


@dataclass(frozen=True)
class GeminiRuntimeConfig:
    """Normalized runtime settings loaded from ``config/gemini.yaml``."""

    enabled: bool
    model: str
    usage_db_path: Path
    cache_db_path: Path
    cache_enabled: bool
    cache_ttl_days: int
    budget: BudgetConfig
    fallback: FallbackConfig


def load_gemini_runtime_config(
    path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
) -> GeminiRuntimeConfig:
    """Load and validate Gemini runtime settings from a YAML config file."""

    raw = load_yaml(path)
    gemini = _mapping(raw.get("gemini"), "gemini")
    cache = _mapping(gemini.get("cache", {}), "gemini.cache")
    fallback = _mapping(gemini.get("fallback", {}), "gemini.fallback")

    return GeminiRuntimeConfig(
        enabled=bool(gemini.get("enabled", True)),
        model=str(gemini.get("model", "gemini-2.0-flash")),
        usage_db_path=Path(str(gemini.get("usage_db_path", "data/runtime/gemini_usage.sqlite"))),
        cache_db_path=Path(str(cache.get("db_path", "data/runtime/llm_cache.sqlite"))),
        cache_enabled=bool(cache.get("enabled", True)),
        cache_ttl_days=int(cache.get("ttl_days", 30)),
        budget=BudgetConfig(
            daily_request_limit=int(gemini.get("daily_request_limit", 40)),
            monthly_request_limit=int(gemini.get("monthly_request_limit", 1000)),
            warning_threshold_ratio=float(gemini.get("warning_threshold_ratio", 0.8)),
            hard_stop_threshold_ratio=float(gemini.get("hard_stop_threshold_ratio", 0.95)),
            allowed_tasks=_tuple_of_str(gemini.get("allowed_tasks", ())),
            blocked_tasks=_tuple_of_str(gemini.get("blocked_tasks", ())),
        ),
        fallback=FallbackConfig(
            on_daily_limit=str(fallback.get("on_daily_limit", "local_summary")),
            on_monthly_limit=str(fallback.get("on_monthly_limit", "skip_llm")),
            on_error=str(fallback.get("on_error", "cached_or_skip")),
        ),
    )


def build_llm_service(
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    *,
    client: TextGenerationClient | None = None,
    model: str | None = None,
    enforce_budget: bool = True,
) -> LlmService:
    """Build the single approved LLM service from ``config/gemini.yaml``.

    Tests and smoke checks can inject a fake ``client``. Production callers that
    omit it receive the isolated ``GeminiClient`` wrapper. ``model`` overrides the
    configured model id, enabling role-based multi-model orchestration while
    sharing the same budget guard and cache.
    """

    config = load_gemini_runtime_config(config_path)
    chosen_client = client or GeminiClient()
    return LlmService(
        model=model or config.model,
        client=chosen_client,
        cache=LlmCache(
            config.cache_db_path,
            ttl_days=config.cache_ttl_days,
            enabled=config.cache_enabled,
        ),
        budget_guard=BudgetGuard(config.usage_db_path, config.budget),
        fallback=config.fallback,
        enforce_budget=enforce_budget,
    )


def _mapping(value: object, name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    msg = f"Expected mapping for {name}"
    raise TypeError(msg)


def _tuple_of_str(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        msg = "Expected a list of strings"
        raise TypeError(msg)
    return tuple(str(item) for item in value)
