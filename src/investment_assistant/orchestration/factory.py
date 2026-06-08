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
        query = _normalize_query(query)
        # Bound the context by whichever heading comes first: in the synthesis
        # prompt drafts follow the context (so "ドラフト" is the real boundary),
        # while the draft prompt ends with "出力要件". Preferring "出力要件" here
        # would otherwise swallow the drafts/critique into the context preview
        # and leak internal "ドラフトN" text into the offline answer.
        context_preview = " ".join(
            _section(prompt, "ローカル文書コンテキスト", "ドラフト1").split()
        )
        context_preview = context_preview or " ".join(
            _section(prompt, "ローカル文書コンテキスト", "出力要件").split()
        )
        context_preview = context_preview[:300]

        perspective = _extract_perspective(prompt)

        if "統合担当" in prompt:
            return "\n".join(
                (
                    "1. 弱点指摘（誤り優先）",
                    f"{query}について、ローカル文書で確認できる範囲に限定して整理します。",
                    "",
                    "2. 重大リスク",
                    f"根拠候補: {context_preview} [1]",
                    "",
                    "3. 現実的代替案",
                    "最小案: 追加データを入れず、根拠候補だけで判断保留点を整理する。",
                    "標準案: Data IntakeでIR・決算資料を追加してから再回答する。",
                    "強化案: 競合企業・ETF・指数データも登録して比較する。",
                    "",
                    "4. 【危険ポイント】",
                    "ローカル文書にない情報、未取得ページ、PDF画像部分、最新市況は未検証です。",
                    "",
                    "5. 次アクション",
                    "Data Intakeで根拠資料を追加し、同じ質問を再実行してください。",
                    "",
                    "信頼度: 中",
                )
            )
        if "厳格なレビュアー" in prompt:
            return (
                "レビュー指摘: 引用候補、不確実性、観点分離を確認。"
                " 同一論点の重複がある場合は最終回答で統合してください。"
            )
        return "\n".join(
            (
                f"ドラフト回答（{perspective}）",
                f"質問: {query}",
                f"専用観点: {perspective}",
                f"根拠候補: {context_preview} [1]",
                "弱点: この観点で見ると、未検証情報が残ります。",
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
    head, sep, _ = remainder.partition(f"\n{end_heading}\n")
    if not sep:
        head, sep, _ = remainder.partition(f"\n{end_heading}")
    if not sep:
        # End heading not found: return empty so callers can fall back to
        # another boundary instead of swallowing the rest of the prompt.
        return ""
    return head.strip()


def _normalize_query(query: str) -> str:
    for marker in ("最後の質問:", "最後の質問", "最新の質問:", "最新質問:"):
        if marker in query:
            query = query.rsplit(marker, 1)[-1]
            break
    compact = " ".join(query.split())
    if len(compact) > 220:
        return compact[:220].rstrip() + "..."
    return compact


def _extract_perspective(prompt: str) -> str:
    for line in prompt.splitlines():
        if line.startswith("専用指示:"):
            return line.replace("専用指示:", "").strip()
        if "配当・財務安全性" in line:
            return "配当・財務安全性"
        if "下落リスク・競争環境" in line:
            return "下落リスク・競争環境"
        if "NISA長期保有" in line:
            return "NISA長期保有"
        if "データ不足・判断保留" in line:
            return "データ不足・判断保留"
        if "反対意見・弱気シナリオ" in line:
            return "反対意見・弱気シナリオ"
    return "総合観点"
