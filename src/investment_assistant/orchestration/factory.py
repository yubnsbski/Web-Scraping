"""Build a MultiModelOrchestrator from config, with an offline fake client."""

from __future__ import annotations

from pathlib import Path

from investment_assistant.llm.factory import DEFAULT_GEMINI_CONFIG_PATH, build_llm_service
from investment_assistant.llm.gemini_client import TextGenerationClient
from investment_assistant.llm.service import LlmService
from investment_assistant.orchestration.orchestrator import (
    DEFAULT_ROLE_MODELS,
    MultiModelOrchestrator,
    OrchestrationConfig,
    RoleModels,
)


class LocalOrchestrationClient:
    """Deterministic, no-network client for dry-run orchestration.

    Detects the pipeline stage from the prompt and returns a concise structured
    response, so the full multi-stage flow can be exercised without Gemini.
    """

    def generate(self, prompt: str, *, model: str) -> str:
        _ = model
        query = _section(prompt, "質問", "ローカル文書コンテキスト")
        context_preview = " ".join(_section(prompt, "ローカル文書コンテキスト", "出力要件").split())
        context_preview = context_preview or " ".join(
            _section(prompt, "ローカル文書コンテキスト", "ドラフト").split()
        )
        context_preview = context_preview[:300]

        if "統合担当" in prompt:
            return "\n".join(
                (
                    "統合最終回答（ローカル擬似・実API未使用）",
                    f"質問: {query}",
                    f"要点: {context_preview} [1]",
                    "不確実性: ローカル文書に一致した範囲のみ。",
                    "信頼度: 中",
                )
            )
        if "厳格なレビュアー" in prompt:
            return "重大な問題なし（ローカル擬似レビュー：引用と不確実性の記載を確認）"
        return "\n".join(
            (
                "ドラフト回答（ローカル擬似・実API未使用）",
                f"質問: {query}",
                f"根拠候補: {context_preview} [1]",
                "不確実性: ローカル文書検索に一致した範囲のみ。",
            )
        )


def build_orchestrator(
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    *,
    role_models: RoleModels = DEFAULT_ROLE_MODELS,
    config: OrchestrationConfig | None = None,
    client: TextGenerationClient | None = None,
    call_real_api: bool = False,
) -> MultiModelOrchestrator:
    """Construct a MultiModelOrchestrator with one guarded service per role.

    All roles share the configured budget guard and cache (same DB paths), so
    multi-model orchestration cannot exceed the free-tier budget. When
    ``call_real_api`` is false and no ``client`` is given, a deterministic local
    client is used so the pipeline runs offline.
    """

    fallback_client = None if call_real_api else LocalOrchestrationClient()

    def make_service(model: str) -> LlmService:
        chosen: TextGenerationClient | None = client if client is not None else fallback_client
        return build_llm_service(config_path, client=chosen, model=model)

    return MultiModelOrchestrator(
        drafter=make_service(role_models.drafter),
        critic=make_service(role_models.critic),
        synthesizer=make_service(role_models.synthesizer),
        config=config,
    )


def _section(text: str, start_heading: str, end_heading: str) -> str:
    _, separator, remainder = text.partition(f"\n{start_heading}\n")
    if not separator:
        return ""
    section, _, _ = remainder.partition(f"\n{end_heading}\n")
    if not section:
        section, _, _ = remainder.partition(f"\n{end_heading}")
    return section.strip()
