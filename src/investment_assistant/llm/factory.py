"""Factory helpers for constructing the guarded LLM service from YAML config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investment_assistant.config.loader import load_yaml
from investment_assistant.llm.budget_guard import BudgetConfig, BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.codex_client import CodexCliClient, CodexUnavailableError
from investment_assistant.llm.gemini_client import GeminiClient, TextGenerationClient
from investment_assistant.llm.service import FallbackConfig, LlmService
from investment_assistant.observability import get_logger

_logger = get_logger("llm.factory")

DEFAULT_GEMINI_CONFIG_PATH = Path("config/gemini.yaml")
DEFAULT_LLM_CONFIG_PATH = Path("config/llm.yaml")

_DEFAULT_ROLES: dict[str, tuple[str, ...]] = {
    "drafter": ("gemini",),
    "critic": ("gemini",),
    "synthesizer": ("gemini",),
}


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


@dataclass(frozen=True)
class CodexRuntimeConfig:
    """Normalized ``providers.codex_cli`` settings from ``config/llm.yaml``."""

    enabled: bool
    exe: str
    model: str
    timeout_s: int
    usage_db_path: Path
    daily_request_limit: int
    hard_stop_threshold_ratio: float
    cooldown_minutes: int


_DEFAULT_CODEX_CONFIG = CodexRuntimeConfig(
    enabled=False,
    exe="codex",
    model="",
    timeout_s=180,
    usage_db_path=Path("data/runtime/codex_usage.sqlite"),
    daily_request_limit=10,
    hard_stop_threshold_ratio=1.0,
    cooldown_minutes=30,
)


@dataclass(frozen=True)
class LlmRuntimeConfig:
    """Normalized settings from ``config/llm.yaml``: provider + role wiring."""

    codex: CodexRuntimeConfig
    roles: dict[str, tuple[str, ...]]


def load_llm_runtime_config(path: str | Path = DEFAULT_LLM_CONFIG_PATH) -> LlmRuntimeConfig:
    """Load ``config/llm.yaml``.

    An absent file, or an absent ``providers.codex_cli`` block, yields the
    pure-Gemini defaults (codex disabled, every role backed by Gemini alone)
    so existing deployments/tests are unaffected until an owner opts in by
    adding the file and setting ``enabled: true``.
    """

    config_path = Path(path)
    if not config_path.exists():
        return LlmRuntimeConfig(codex=_DEFAULT_CODEX_CONFIG, roles=dict(_DEFAULT_ROLES))

    raw = load_yaml(config_path)
    providers = _mapping(raw.get("providers", {}), "providers")
    codex_raw = providers.get("codex_cli")
    if codex_raw is None:
        codex = _DEFAULT_CODEX_CONFIG
    else:
        codex_mapping = _mapping(codex_raw, "providers.codex_cli")
        codex = CodexRuntimeConfig(
            enabled=bool(codex_mapping.get("enabled", False)),
            exe=str(codex_mapping.get("exe", "codex")),
            model=str(codex_mapping.get("model", "")),
            timeout_s=int(codex_mapping.get("timeout_s", 180)),
            usage_db_path=Path(
                str(codex_mapping.get("usage_db_path", "data/runtime/codex_usage.sqlite"))
            ),
            daily_request_limit=int(codex_mapping.get("daily_request_limit", 10)),
            hard_stop_threshold_ratio=float(
                codex_mapping.get("hard_stop_threshold_ratio", 1.0)
            ),
            cooldown_minutes=int(codex_mapping.get("cooldown_minutes", 30)),
        )

    roles_raw = _mapping(raw.get("roles", {}), "roles")
    roles = {role: _tuple_of_str(providers_list) for role, providers_list in roles_raw.items()}
    if not roles:
        roles = dict(_DEFAULT_ROLES)

    return LlmRuntimeConfig(codex=codex, roles=roles)


def build_codex_service(
    codex_config: CodexRuntimeConfig,
    *,
    cache_db_path: str | Path,
    cache_enabled: bool = True,
    cache_ttl_days: int = 30,
    client: TextGenerationClient | None = None,
) -> LlmService | None:
    """Build the guarded Codex CLI service, or ``None`` if disabled/unavailable.

    Shares the cache database file with Gemini (differentiated by the
    ``codex_cli:<model>`` model label used as part of the cache key -- see
    ``LlmCache.make_key``) but uses its own budget-guard usage database so the
    self-imposed daily cap and cooldown are tracked independently of Gemini's
    free-tier budget.
    """

    if not codex_config.enabled:
        return None

    chosen_client = client
    if chosen_client is None:
        try:
            chosen_client = CodexCliClient(
                exe=codex_config.exe,
                timeout_s=codex_config.timeout_s,
                model=codex_config.model,
            )
        except CodexUnavailableError:
            _logger.warning(
                "codex_cli enabled but binary %r not found; treating as disabled",
                codex_config.exe,
            )
            return None

    model_label = codex_config.model or "default"
    return LlmService(
        model=f"codex_cli:{model_label}",
        client=chosen_client,
        cache=LlmCache(cache_db_path, ttl_days=cache_ttl_days, enabled=cache_enabled),
        budget_guard=BudgetGuard(
            codex_config.usage_db_path,
            BudgetConfig(
                daily_request_limit=codex_config.daily_request_limit,
                # No separate monthly self-cap is configured for codex_cli; derive
                # a generous ceiling so the daily cap remains the binding limit.
                monthly_request_limit=codex_config.daily_request_limit * 62,
                hard_stop_threshold_ratio=codex_config.hard_stop_threshold_ratio,
            ),
        ),
        # Codex is a secondary critic provider in a ChainLlmService: any
        # skip/error here must fall through to Gemini rather than surface raw
        # prompt text, so every fallback mode is "skip_llm".
        fallback=FallbackConfig(
            on_daily_limit="skip_llm", on_monthly_limit="skip_llm", on_error="skip_llm"
        ),
        enforce_budget=True,
        provider="codex_cli",
        cooldown_minutes=codex_config.cooldown_minutes,
        count_failed_attempts=True,
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
