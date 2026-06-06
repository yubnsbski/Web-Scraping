"""Multi-model prompting orchestration (draft -> critique -> synthesize).

Coordinates several LLM roles (optionally different models) through the guarded
``LlmService`` so budget limits, caching, and fallback always apply. This is a
research aid: it never places orders and never performs auto-trading.
"""

from investment_assistant.orchestration.orchestrator import (
    DEFAULT_ROLE_MODELS,
    MultiModelOrchestrator,
    OrchestrationConfig,
    RoleModels,
)

__all__ = [
    "DEFAULT_ROLE_MODELS",
    "MultiModelOrchestrator",
    "OrchestrationConfig",
    "RoleModels",
]
